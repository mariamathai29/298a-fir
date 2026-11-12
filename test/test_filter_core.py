import random

import cocotb

from core_tb import S_FIN, S_IDLE, S_MAC, S_UPD, AfCoreTB
import filter_golden

filter_golden.N_TAPS = 4

STEP_CLK = 23                             # go cycle + 17 MAC + FIN + 4 UPD


def model_from(taps, weights, adapt=False, mu_sel=0):
    # init software reference model
    m = filter_golden.AdaptiveFilter(mu_q=1 << mu_sel)
    m.adapt_en = adapt
    m.x = list(taps)
    m.w = list(weights)
    return m


async def check_step(tb, taps, weights, r, adapt=False, mu_sel=0):
    # compare step output with reference model
    tb.set_ctl(int(adapt), mu_sel)
    tb.set_taps(taps[1:] + [0])
    tb.set_weights(weights)
    m = model_from(taps[1:] + [0], weights, adapt, mu_sel)
    exp = m.step(taps[0], r)
    got = await tb.step(taps[0], r)
    ctx = f"taps {taps} weights {weights} r {r} adapt {int(adapt)} mu_sel {mu_sel}"
    assert got == exp, f"{ctx}: got (y, e) {got}, expected {exp}"
    assert tb.weights() == m.w, f"{ctx}: weights after {tb.weights()}, expected {m.w}"
    return m


@cocotb.test()
async def test_reset(dut):
    # verify tb reset 
    tb = AfCoreTB(dut)
    await tb.reset()

    assert tb.state() == S_IDLE
    assert tb.taps() == [0, 0, 0, 0]
    assert tb.weights() == [0, 0, 0, 0]
    assert dut.t_load.value == 0
    assert dut.sat_flag.value == 0
    assert dut.ovf_flag.value == 0

    await tb.wait(100)
    assert tb.state() == S_IDLE
    assert tb.outputs == []
    assert dut.sat_flag.value == 0
    assert dut.ovf_flag.value == 0


@cocotb.test()
async def test_step_timing(dut):
    tb = AfCoreTB(dut)
    await tb.reset()

    # fill taps, set weights
    for s in (11, 22, 33, 44):
        await tb.send(s, 0)
        await tb.wait(30)
    tb.outputs.clear()
    w = [100, -200, 300, -400]
    tb.set_weights(w)
    await tb.wait(1)

    # send sample 
    u = 55
    taps = [u] + tb.taps()[:3]            # after the step: newest first
    tracer = cocotb.start_soon(tb.trace(40))
    await tb.send(u, 0)
    rows = await tracer

    # step starts on the go cycle
    first = next(i for i, row in enumerate(rows) if row["go"])
    step = rows[first:first + STEP_CLK]
    assert sum(row["go"] for row in rows) == 1, "go must pulse once"

    # verify number of cycles spent in each state matches expected
    expect = ([(S_IDLE, None)] + [(S_MAC, k) for k in range(17)] +
              [(S_FIN, None)] + [(S_UPD, k) for k in range(4)])
    got = [(row["state"], row["cnt"] if exp[1] is not None else None)
           for row, exp in zip(step, expect)]
    assert got == expect, f"state sequence {got}"
    assert rows[first + STEP_CLK]["state"] == S_IDLE, "not idle after 23 clk"

    # 20 rotations, in MAC 0-15 and UPD 0-3 only
    rot = [row["rot"] for row in step]
    assert rot == [0] + [1] * 16 + [0, 0] + [1] * 4, f"rot pattern {rot}"
    assert sum(row["rot"] for row in rows) == 20

    # transmit load signal on first update cycle
    loads = [i for i, row in enumerate(rows) if row["tx_load"]]
    assert loads == [first + 19], f"tx_load at {loads}, expected {first + 19}"

    # position 0 during MAC issue k and UPD k: tap k % 4 and weight k % 4
    for k in range(16):
        row = step[1 + k]
        assert row["x"][0] == taps[k % 4] and row["w"][0] == w[k % 4], \
            f"MAC {k}: x0 {row['x'][0]}, w0 {row['w'][0]}"
    for k in range(4):
        row = step[19 + k]
        assert row["x"][0] == taps[k] and row["w"][0] == w[k], \
            f"UPD {k}: x0 {row['x'][0]}, w0 {row['w'][0]}"

    # once rotations are complete, verify original order restored
    assert tb.taps() == taps
    assert tb.weights() == w
    assert len(tb.outputs) == 1
    assert dut.ovf_flag.value == 0


# Weight register values (Q2.12) for the single-tap sweep. The multiplier uses
# w[13:4] (Q2.8): 15 has only the ignored low bits set, and -1 truncates to -1.
W_SWEEP = [0, 16, -16, 15, -1, 8191, -8192, 1234, -3001, 4096, -4096]


@cocotb.test()
async def test_mac_single_tap(dut):
    # verify MAC
    tb = AfCoreTB(dut)
    await tb.reset()
    rng = random.Random(1)
    for pos in range(4):
        for wv in W_SWEEP:
            weights = [0, 0, 0, 0]
            weights[pos] = wv
            for xv in range(-128, 128):
                taps = [rng.randint(-128, 127) for _ in range(4)]
                taps[pos] = xv
                await check_step(tb, taps, weights, rng.randint(-128, 127))


@cocotb.test()
async def test_rounding(dut):
    # check MAC rounding, 1.7 x 2.8 = 3.15, drop 8 frac
    tb = AfCoreTB(dut)
    await tb.reset()
    rng = random.Random(2)
    edges = [b + d for b in (-6144, -2048, 2048, 6144) for d in (-1, 0, 1)]
    for xv in (1, -1):
        for wv in [(wm << 4) | rng.randint(0, 15) for wm in range(-512, 512)] + edges:
            await check_step(tb, [xv, 0, 0, 0], [wv, 0, 0, 0], 0)

@cocotb.test()
async def test_saturation(dut):
    # check error and output saturate correctly
    full = [-128, -128, -128, -128]
    w_max, w_min = [8191] * 4, [-8192] * 4
    cases = [
        # taps, weights, r, sat_flag
        ([0, 0, 0, 0],   [0] * 4, 0,    False),   # nothing saturates
        ([64, 0, 0, 0],  [4096, 0, 0, 0], 127, False),  # y = 64, e = 63
        (full,           w_min,   0,    True),    # y = +4 * 128 * 512 / 256 -> 127
        (full,           w_max,   0,    True),    # y -> -128
        ([-128, 0, 0, 0], [-8192, 0, 0, 0], 0, True),  # one tap: 128 * 512 / 256 = 256 -> 127
        ([127, 0, 0, 0], [8191, 0, 0, 0], -128, True), # y = 127 (sat), e = -255 -> -128
        ([0, 0, 0, 0],   [0] * 4, 127,  False),   # e = 127, no saturation
        ([-128, 0, 0, 0], [4096, 0, 0, 0], 127, True), # y = -128, e = 255 -> 127
        ([127, 0, 0, 0], [4096, 0, 0, 0], -128, True), # y = 127 (exact), e = -255 -> -128
    ]
    for taps, weights, r, sat in cases:
        tb = AfCoreTB(dut)
        await tb.reset()
        m = await check_step(tb, taps, weights, r)
        assert m.sat_flag == sat, f"model sat_flag {m.sat_flag}, case expects {sat}"
        assert int(dut.sat_flag.value) == sat, \
            f"taps {taps} weights {weights} r {r}: sat_flag {int(dut.sat_flag.value)}, expected {int(sat)}"
        assert dut.ovf_flag.value == 0


@cocotb.test()
async def test_mac_random(dut):
    # compare random inputs for MAC against sw model
    tb = AfCoreTB(dut)
    await tb.reset()
    rng = random.Random(2)
    for _ in range(2000):
        taps = [rng.randint(-128, 127) for _ in range(4)]
        weights = [rng.randint(-8192, 8191) for _ in range(4)]
        await check_step(tb, taps, weights, rng.randint(-128, 127))


# ---------------- Weight update ----------------
SIGN_TAPS = [3, -3, 0, 127]
SIGN_W = [160, -160, 32, 0]


def sgn(v):
    return (v > 0) - (v < 0)


@cocotb.test()
async def test_update_sign_table(dut):
    # check model and weights and update table match
    tb = AfCoreTB(dut)
    await tb.reset()
    for base in ([3, -3, 0, 127], [-1, 0, 5, -128]):
        for rot in range(4):
            taps = base[rot:] + base[:rot]
            for r in (5, 0, -5):
                m = await check_step(tb, taps, [0, 0, 0, 0], r, adapt=True, mu_sel=2)
                # Independent of the model: the update table itself
                expect = [4 * sgn(r) * sgn(x) for x in taps]
                assert m.w == expect and tb.weights() == expect, \
                    f"taps {taps} r {r}: weights {tb.weights()}, expected {expect}"


@cocotb.test()
async def test_update_mu(dut):
    # Verify all LR values
    tb = AfCoreTB(dut)
    await tb.reset()
    for mu_sel in range(8):
        for r in (10, -10):
            await check_step(tb, SIGN_TAPS, SIGN_W, r, adapt=True, mu_sel=mu_sel)
            mu = 1 << mu_sel
            expect = [w + mu * sgn(r) * sgn(x) for w, x in zip(SIGN_W, SIGN_TAPS)]
            assert tb.weights() == expect, f"mu_sel {mu_sel} r {r}: {tb.weights()}, expected {expect}"


@cocotb.test()
async def test_update_saturation(dut):
    # check weights saturate at 2^13
    cases = [
        # weights, r, sat_flag      (taps all +1, mu = 128)
        ([8091, -8092, 8063, 8191], 127, True),    # 8091 + 128 and 8191 + 128 clamp
        ([8063, 0, 0, 0], 127, False),             # 8063 + 128 = 8191 exactly
        ([-8100, -8192, -8064, 0], -128, True),    # -8100 - 128 and -8192 - 128 clamp
        ([-8064, 0, 0, 0], -128, False),           # -8064 - 128 = -8192 exactly
    ]
    for weights, r, sat in cases:
        tb = AfCoreTB(dut)
        await tb.reset()
        m = await check_step(tb, [1, 1, 1, 1], weights, r, adapt=True, mu_sel=7)
        assert m.sat_flag == sat, f"model sat_flag {m.sat_flag}, case expects {sat}"
        assert int(dut.sat_flag.value) == sat, \
            f"weights {weights} r {r}: sat_flag {int(dut.sat_flag.value)}, expected {int(sat)}"
        assert all(-8192 <= w <= 8191 for w in tb.weights())


@cocotb.test()
async def test_adapt_en_sampling(dut):
    # test adaptation when adapt_en is enabled in various states; should follow adapt_en as in FIN state
    tb = AfCoreTB(dut)
    await tb.reset()
    updated = [w + 8 * sgn(5) * sgn(x) for w, x in zip(SIGN_W, SIGN_TAPS)]
    cases = [
        # switch adapt_en in this state, from -> to, update expected
        (S_MAC, 0, 1, True),
        (S_FIN, 1, 0, False),
        (S_FIN, 0, 1, True),
        (S_UPD, 1, 0, True),
        (S_UPD, 0, 1, False),
    ]
    for at, before, after, upd in cases:
        tb.set_ctl(before, 3)
        tb.set_taps(SIGN_TAPS[1:] + [0])
        tb.set_weights(SIGN_W)
        task = cocotb.start_soon(tb.step(SIGN_TAPS[0], 5))
        await tb.until_state(at)
        tb.set_ctl(after, 3)
        await task
        expect = updated if upd else SIGN_W
        assert tb.weights() == expect, \
            f"adapt_en {before} -> {after} in state {at}: weights {tb.weights()}, expected {expect}"


@cocotb.test()
async def test_update_random(dut):
    # test outputs and adaptation against ref model
    tb = AfCoreTB(dut)
    await tb.reset()
    rng = random.Random(3)
    weights = [rng.randint(-8192, 8191) for _ in range(4)]
    tb.set_weights(weights)
    m = model_from([0, 0, 0, 0], weights)
    for i in range(3000):
        u, r = rng.randint(-128, 127), rng.randint(-128, 127)
        adapt, mu_sel = rng.random() < 0.9, rng.randint(0, 7)
        tb.set_ctl(int(adapt), mu_sel)
        m.adapt_en, m.mu_q = adapt, 1 << mu_sel
        exp = m.step(u, r)
        got = await tb.step(u, r)
        assert got == exp, f"step {i}: got (y, e) {got}, expected {exp}"
        assert tb.weights() == m.w, f"step {i}: weights {tb.weights()}, expected {m.w}"
        assert int(dut.sat_flag.value) == m.sat_flag, f"step {i}: sat_flag differs"


# ---------------- Sample handling ----------------
def accepted(times):
    # check difference between last accepted sample cycle and current timestep, accepted if greater than num cycles for 1 step
    last, out = None, []
    for t in times:
        ok = last is None or (t + 1) - last >= STEP_CLK
        out.append(ok)
        if ok:
            last = t + 1
    return out

async def run_schedule(tb, samples, weights, mu_sel=4):
    # send samples at scheduled times, check number accepted against model
    tb.set_ctl(1, mu_sel)
    tb.set_weights(weights)
    m = model_from([0, 0, 0, 0], weights, adapt=True, mu_sel=mu_sel)
    n = len(tb.outputs)
    await tb.send_schedule(samples)
    await tb.wait(STEP_CLK + 5)
    acc = accepted([t for t, _, _ in samples])
    exp = [m.step(u, r) for (_, u, r), ok in zip(samples, acc) if ok]
    got = [(y, e) for _, y, e, _ in tb.outputs[n:]]
    assert got == exp, f"outputs {got}, expected {exp} (accepted {acc})"
    assert tb.weights() == m.w, f"weights {tb.weights()}, expected {m.w}"
    return acc.count(False)


@cocotb.test()
async def test_sample_spacing(dut):
    # space across multiple cycle values
    w = [1234, -2345, 3456, -4567]
    for s in range(2, 31):
        tb = AfCoreTB(dut)
        await tb.reset()
        dropped = await run_schedule(tb, [(0, 50, -30), (s, -70, 90)], w)
        assert dropped == (1 if s < STEP_CLK else 0)
        assert int(dut.ovf_flag.value) == dropped, \
            f"spacing {s}: ovf_flag {int(dut.ovf_flag.value)}, expected {dropped}"


@cocotb.test()
async def test_max_rate(dut):
    # send samples at highest rate possible, at STEP_CLK
    tb = AfCoreTB(dut)
    await tb.reset()
    rng = random.Random(4)
    samples = [(STEP_CLK * i, rng.randint(-128, 127), rng.randint(-128, 127)) for i in range(500)]
    dropped = await run_schedule(tb, samples, [0, 0, 0, 0])
    assert dropped == 0
    assert dut.ovf_flag.value == 0


@cocotb.test()
async def test_overrun_random(dut):
    # send samples at multiple random lengths, check that dropped flag asserts
    tb = AfCoreTB(dut)
    await tb.reset()
    rng = random.Random(5)
    t, samples = 0, []
    for _ in range(1000):
        samples.append((t, rng.randint(-128, 127), rng.randint(-128, 127)))
        t += rng.randint(10, 40)
    dropped = await run_schedule(tb, samples, [500, -500, 250, -250])
    assert 0 < dropped < len(samples), f"{dropped} dropped: the run does not exercise both cases"
    assert dut.ovf_flag.value == 1


# ---------------- Reset and flags ----------------

async def check_clean_after_reset(tb, where):
    d = tb.dut
    assert tb.state() == S_IDLE, f"reset {where}: state {tb.state()}"
    assert tb.taps() == [0] * 4 and tb.weights() == [0] * 4, f"reset {where}: rings not cleared"
    assert d.ovf_flag.value == 0 and d.sat_flag.value == 0, f"reset {where}: flags not cleared"
    tb.outputs.clear()
    await tb.wait(100)
    assert tb.outputs == [], f"reset {where}: output after reset {tb.outputs}"
    m = model_from([0] * 4, [0] * 4, adapt=True, mu_sel=3)
    for u, r in ((60, -60), (-25, 90)):
        tb.set_ctl(1, 3)
        assert await tb.step(u, r) == m.step(u, r), f"reset {where}: step after reset wrong"
    assert tb.weights() == m.w
    tb.set_ctl(0, 0)


async def pulse_reset(tb):
    tb.dut.rst.value = 1
    await tb.wait(3)
    tb.dut.rst.value = 0
    await tb.wait(1)


@cocotb.test()
async def test_reset_mid_operation(dut):
    tb = AfCoreTB(dut)
    await tb.reset()

    async def fill():
        tb.set_taps([-128] * 4)
        tb.set_weights([-8192] * 4)
        await tb.step(-128, 0)            # y saturates: sat_flag
        await tb.send(1, 1)
        await tb.wait(3)
        await tb.send(2, 2)               # inside the step: dropped, ovf_flag
        await tb.wait(STEP_CLK)
        assert dut.sat_flag.value == 1 and dut.ovf_flag.value == 1
        tb.set_weights(MON_W)

    for at in (S_MAC, S_FIN, S_UPD):
        # reset in each operating state
        await fill()
        task = cocotb.start_soon(tb.send(10, 20))
        await tb.until_state(at)
        await pulse_reset(tb)
        task.cancel()
        dut.d_pre.value = 0
        dut.d_stb.value = 0
        await check_clean_after_reset(tb, f"in state {at}")


@cocotb.test()
async def test_flags_sticky(dut):
    # assert sticky flags until reset
    tb = AfCoreTB(dut)
    await tb.reset()
    rng = random.Random(7)

    async def clean_activity():
        tb.set_taps([0] * 4)
        tb.set_weights([0] * 4)
        for _ in range(20):
            await tb.step(rng.randint(-60, 60), rng.randint(-60, 60))

    # sat_flag alone
    tb.set_taps([-128] * 4)
    tb.set_weights([-8192] * 4)
    await tb.step(-128, 0)
    assert (int(dut.sat_flag.value), int(dut.ovf_flag.value)) == (1, 0)
    await clean_activity()
    assert (int(dut.sat_flag.value), int(dut.ovf_flag.value)) == (1, 0), "sat_flag did not stay set"

    # then ovf_flag
    await tb.send(1, 1)
    await tb.wait(5)
    await tb.send(2, 2)
    await tb.wait(STEP_CLK)
    assert (int(dut.sat_flag.value), int(dut.ovf_flag.value)) == (1, 1)
    await clean_activity()
    assert (int(dut.sat_flag.value), int(dut.ovf_flag.value)) == (1, 1), "a flag did not stay set"

    # ovf_flag alone, from reset
    await pulse_reset(tb)
    await tb.send(1, 1)
    await tb.wait(5)
    await tb.send(2, 2)
    await tb.wait(STEP_CLK)
    assert (int(dut.sat_flag.value), int(dut.ovf_flag.value)) == (0, 1)
    await clean_activity()
    assert (int(dut.sat_flag.value), int(dut.ovf_flag.value)) == (0, 1), "ovf_flag did not stay set"

    await pulse_reset(tb)
    assert (int(dut.sat_flag.value), int(dut.ovf_flag.value)) == (0, 0)


# ---------------- Weight monitor lane ----------------
MON_W = [3072, -8192, 8191, -65]          # 0.75, -2, max; -65 checks truncation


def mon(w):
    """A weight register as the monitor lane shows it: top 8 bits."""
    return w >> 6


@cocotb.test()
async def test_monitor_frozen(dut):
    # check weight monitor lane works by disabling adaptation
    tb = AfCoreTB(dut)
    await tb.reset()
    tb.set_weights(MON_W)
    m = model_from([0] * 4, MON_W)
    rng = random.Random(8)
    for n in range(12):
        u, r = rng.randint(-128, 127), rng.randint(-128, 127)
        assert await tb.step(u, r) == m.step(u, r)
        w = tb.outputs[-1][3]
        assert w == mon(MON_W[n % 4]), f"output {n}: weight {w}, expected weight {n % 4} = {mon(MON_W[n % 4])}"


@cocotb.test()
async def test_monitor_adapting(dut):
    # test weights while adapting, before adaptation step
    tb = AfCoreTB(dut)
    await tb.reset()
    rng = random.Random(9)
    m = model_from([0] * 4, [0] * 4)
    for n in range(3000):
        u, r = rng.randint(-128, 127), rng.randint(-128, 127)
        adapt, mu_sel = rng.random() < 0.9, rng.randint(0, 7)
        tb.set_ctl(int(adapt), mu_sel)
        m.adapt_en, m.mu_q = adapt, 1 << mu_sel
        before = m.w[n % 4]
        assert await tb.step(u, r) == m.step(u, r), f"output {n}: (y, e) differs"
        w = tb.outputs[-1][3]
        assert w == mon(before), f"output {n}: weight {w}, expected weight {n % 4} before update = {mon(before)}"


@cocotb.test()
async def test_monitor_snapshot(dut):
    # adapt for 301 cycles, turn adaptation off, filter 4 cycles, compare weights against sw model
    tb = AfCoreTB(dut)
    await tb.reset()
    rng = random.Random(10)
    m = model_from([0] * 4, [0] * 4, adapt=True, mu_sel=7)
    n = 0
    for _ in range(3):
        tb.set_ctl(1, 7)
        m.adapt_en = True
        for _ in range(301):
            u, r = rng.randint(-128, 127), rng.randint(-128, 127)
            assert await tb.step(u, r) == m.step(u, r)
            n += 1
        tb.set_ctl(0, 7)
        m.adapt_en = False
        snap = {}
        for _ in range(4):
            u, r = rng.randint(-128, 127), rng.randint(-128, 127)
            assert await tb.step(u, r) == m.step(u, r)
            snap[n % 4] = tb.outputs[-1][3]
            n += 1
        got = [snap[k] for k in range(4)]
        assert got == [mon(w) for w in m.w], f"snapshot {got}, expected {[mon(w) for w in m.w]}"


@cocotb.test()
async def test_monitor_dropped_samples(dut):
    # send samples with variable timing
    # verify weight readout advances for output generated, not input accepted. dropped inputs should not impact weight readout
    tb = AfCoreTB(dut)
    await tb.reset()
    tb.set_weights(MON_W)
    rng = random.Random(11)
    t, samples = 0, []
    for _ in range(400):
        samples.append((t, rng.randint(-128, 127), rng.randint(-128, 127)))
        t += rng.randint(10, 40)
    await tb.send_schedule(samples)
    await tb.wait(STEP_CLK + 5)
    n_acc = accepted([t for t, _, _ in samples]).count(True)
    assert 0 < n_acc < len(samples), "the run does not exercise dropped samples"
    got = [w for _, _, _, w in tb.outputs]
    assert len(got) == n_acc
    assert got == [mon(MON_W[n % 4]) for n in range(n_acc)], "weight index out of step after a drop"
    assert dut.ovf_flag.value == 1


@cocotb.test()
async def test_monitor_reset(dut):
    # after reset, weight readout should start from first weight
    tb = AfCoreTB(dut)
    await tb.reset()
    for done in range(1, 4):              # outputs since reset before the next reset
        for at in (S_MAC, S_UPD):
            tb.set_weights(MON_W)
            for _ in range(done):
                await tb.step(1, 1)
            task = cocotb.start_soon(tb.send(1, 1))
            await tb.until_state(at)
            await pulse_reset(tb)
            task.cancel()
            dut.d_pre.value = 0
            dut.d_stb.value = 0
            await tb.wait(2)
            tb.set_weights(MON_W)
            tb.outputs.clear()
            for n in range(4):
                await tb.step(2, 2)
            got = [w for _, _, _, w in tb.outputs]
            assert got == [mon(w) for w in MON_W], \
                f"reset after {done} outputs, in state {at}: weights {got}, expected {[mon(w) for w in MON_W]}"
