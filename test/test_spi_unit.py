# SPDX-FileCopyrightText: © 2026 Aaron Snider
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for spi_transmit and spi_receive modules.

tx_:  Transmitter 
rx_:  Receiver
lb_:  Loopback 

"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, Timer

HALF = 5  # us, half a clk period (also used for the rx sclk)
FRAME = 16  # clk cycles per frame (fs_o low)

VECTORS = [(0x00, 0x00), (0xFF, 0xFF), (0xFF, 0x00), (0x00, 0xFF),
           (0x01, 0x80), (0x80, 0x01), (0xA5, 0x3C), (0x5A, 0xC3)]


def random_vectors(n, seed):
    rng = random.Random(seed)
    return [(rng.randrange(256), rng.randrange(256)) for _ in range(n)]


def bits(byte):
    """Bits of a byte, LSB first (the order they go out on the wire)."""
    return [(byte >> i) & 1 for i in range(8)]


def to_byte(bit_list):
    return sum(b << i for i, b in enumerate(bit_list))


# transmitter

async def start(dut, p):
    """Start the clock and reset the clocked instance with prefix p ("tx" or "lb")."""
    cocotb.start_soon(Clock(dut.clk, 2 * HALF, unit="us").start())
    getattr(dut, p + "_load").value = 0
    getattr(dut, p + "_d_a").value = 0
    getattr(dut, p + "_d_b").value = 0
    getattr(dut, p + "_rst_n").value = 0
    await ClockCycles(dut.clk, 3)
    await FallingEdge(dut.clk)
    getattr(dut, p + "_rst_n").value = 1
    await FallingEdge(dut.clk)


def sample(dut, p):
    """(sclk, fs, sdo) for the transmitter, plus (d_tog, hold_u, hold_r) for the loopback."""
    s = (int(getattr(dut, p + "_sclk").value),
         int(getattr(dut, p + "_fs").value),
         int(getattr(dut, p + "_sdo").value))
    if p == "lb":
        s += (int(dut.lb_d_tog.value), int(dut.lb_d_hold_u.value), int(dut.lb_d_hold_r.value))
    return s


async def send(dut, a, b, p="tx", poke=None):
    """Pulse load for one clock and record one sample per clock until fs_o goes high"""
    getattr(dut, p + "_d_a").value = a
    getattr(dut, p + "_d_b").value = b
    getattr(dut, p + "_load").value = 1
    await FallingEdge(dut.clk)
    getattr(dut, p + "_load").value = 0

    trace = []
    for i in range(40):
        trace.append(sample(dut, p))
        if trace[-1][1] == 1:
            return trace
        if poke:
            poke(i)
        await FallingEdge(dut.clk)
    assert False, "frame never finished"


async def send_held(dut, frames, p="tx"):
    """Keep load high for several frames in a row"""
    dut_a, dut_b = getattr(dut, p + "_d_a"), getattr(dut, p + "_d_b")
    dut_a.value, dut_b.value = frames[0]
    getattr(dut, p + "_load").value = 1
    await FallingEdge(dut.clk)

    trace = []
    total = (FRAME + 1) * len(frames)
    for i in range(total):
        trace.append(sample(dut, p))
        n, pos = divmod(i, FRAME + 1)
        if pos == 0 and n + 1 < len(frames):
            dut_a.value, dut_b.value = frames[n + 1]
        if i == total - 1:
            getattr(dut, p + "_load").value = 0  # no frame after the last one
        await FallingEdge(dut.clk)
    return trace


def check_frame(trace, a, b):
    sclk = [s[0] for s in trace]
    fs = [s[1] for s in trace]
    assert fs == [0] * FRAME + [1], f"fs_o: {fs}"
    assert sclk == [i % 2 for i in range(FRAME + 1)], f"sclk_o: {sclk}"

    # read the data like a slave would: just before each rising edge of sclk
    a_bits, b_bits = [], []
    for i in range(1, len(trace)):
        if sclk[i] and not sclk[i - 1]:
            a_bits.append(trace[i - 1][2] & 1)
            b_bits.append(trace[i - 1][2] >> 1)
    assert to_byte(a_bits) == a, f"a: got {to_byte(a_bits):#04x}, want {a:#04x}"
    assert to_byte(b_bits) == b, f"b: got {to_byte(b_bits):#04x}, want {b:#04x}"


@cocotb.test()
async def test_tx_reset_and_idle(dut):
    await start(dut, "tx")
    assert sample(dut, "tx") == (0, 1, 0)
    # without load nothing should happen, whatever is on the data inputs
    for _ in range(20):
        dut.tx_d_a.value = random.randrange(256)
        dut.tx_d_b.value = random.randrange(256)
        await FallingEdge(dut.clk)
        assert sample(dut, "tx") == (0, 1, 0)


@cocotb.test()
async def test_tx_frames(dut):
    await start(dut, "tx")
    for a, b in VECTORS + random_vectors(10, seed=1):
        check_frame(await send(dut, a, b), a, b)


@cocotb.test()
async def test_tx_data_latched_on_load(dut):
    """Changing d_a/d_b after the load edge must not change the frame."""
    await start(dut, "tx")

    def scramble(i):
        dut.tx_d_a.value = 0xFF if i % 2 else 0x00
        dut.tx_d_b.value = 0x00 if i % 2 else 0xFF

    check_frame(await send(dut, 0x96, 0x69, poke=scramble), 0x96, 0x69)


@cocotb.test()
async def test_tx_load_ignored_while_busy(dut):
    await start(dut, "tx")

    def poke(i):
        if i == 3:
            dut.tx_d_a.value = 0xFF
            dut.tx_d_b.value = 0xFF
            dut.tx_load.value = 1
        elif i == 12:
            dut.tx_load.value = 0

    check_frame(await send(dut, 0x3C, 0xC3, poke=poke), 0x3C, 0xC3)
    for _ in range(20):
        await FallingEdge(dut.clk)
        sclk, fs, _ = sample(dut, "tx")
        assert (sclk, fs) == (0, 1)


@cocotb.test()
async def test_tx_back_to_back(dut):
    """With load held high the frames follow each other, fs_o high for one clock between."""
    await start(dut, "tx")
    frames = [(0x5A, 0xC3), (0x00, 0xFF), (0xFF, 0x00)]
    trace = await send_held(dut, frames)
    for n, (a, b) in enumerate(frames):
        check_frame(trace[n * (FRAME + 1):(n + 1) * (FRAME + 1)], a, b)


@cocotb.test()
async def test_tx_async_reset(dut):
    """Reset in the middle of a frame (sclk high, sdo high) takes effect without a clock edge."""
    await start(dut, "tx")
    dut.tx_d_a.value = 0xFF
    dut.tx_d_b.value = 0xFF
    dut.tx_load.value = 1
    await FallingEdge(dut.clk)
    dut.tx_load.value = 0
    await ClockCycles(dut.clk, 5)
    await FallingEdge(dut.clk)
    assert sample(dut, "tx") == (1, 0, 0b11)

    dut.tx_rst_n.value = 0
    await Timer(1, unit="us")
    assert sample(dut, "tx") == (0, 1, 0)

    await ClockCycles(dut.clk, 2)
    await FallingEdge(dut.clk)
    dut.tx_rst_n.value = 1
    await FallingEdge(dut.clk)
    check_frame(await send(dut, 0xC3, 0x3C), 0xC3, 0x3C)

# receiver

async def rx_reset(dut):
    dut.rx_sclk.value = 0
    dut.rx_cs_n.value = 1
    dut.rx_mosi_u.value = 0
    dut.rx_mosi_r.value = 0
    dut.rx_rst_n.value = 0
    await Timer(2 * HALF, unit="us")
    dut.rx_rst_n.value = 1
    await Timer(HALF, unit="us")


async def select(dut):
    dut.rx_cs_n.value = 0
    await Timer(HALF, unit="us")


async def deselect(dut):
    dut.rx_cs_n.value = 1
    await Timer(1, unit="us")


def rx_state(dut):
    """(d_tog, d_hold_u, d_hold_r)"""
    return (int(dut.rx_d_tog.value), int(dut.rx_d_hold_u.value), int(dut.rx_d_hold_r.value))


async def rx_bit(dut, u, r):
    """Clock one bit in on each line. Returns rx_state() just after the rising edge."""
    dut.rx_mosi_u.value = u
    dut.rx_mosi_r.value = r
    await Timer(HALF, unit="us")
    dut.rx_sclk.value = 1
    await Timer(1, unit="us")
    state = rx_state(dut)
    await Timer(HALF - 1, unit="us")
    dut.rx_sclk.value = 0
    return state


async def rx_byte(dut, u, r):
    return [await rx_bit(dut, ub, rb) for ub, rb in zip(bits(u), bits(r))]


def check_byte(states, old, new):
    """d_hold stays at old for the first 7 edges, then takes new with d_tog on the 8th."""
    for i, (tog, hu, hr) in enumerate(states[:7]):
        assert (tog, hu, hr) == (0, *old), f"edge {i + 1}: {(tog, hu, hr)}"
    assert states[7] == (1, *new), f"edge 8: {states[7]}, want {(1, *new)}"


@cocotb.test()
async def test_rx_byte(dut):
    await rx_reset(dut)
    assert rx_state(dut) == (0, 0, 0)

    await select(dut)
    check_byte(await rx_byte(dut, 0xA5, 0x3C), (0, 0), (0xA5, 0x3C))
    await deselect(dut)
    # cs_n going high drops d_tog straight away, the data stays
    assert rx_state(dut) == (0, 0xA5, 0x3C)


@cocotb.test()
async def test_rx_data(dut):
    """Both lines, LSB first, including single-bit values at each end."""
    await rx_reset(dut)
    old = (0, 0)
    for u, r in VECTORS + random_vectors(10, seed=2):
        await select(dut)
        check_byte(await rx_byte(dut, u, r), old, (u, r))
        await deselect(dut)
        old = (u, r)


@cocotb.test()
async def test_rx_two_bytes_in_one_frame(dut):
    """With cs_n held low the counter wraps and d_tog pulses once per byte."""
    await rx_reset(dut)
    await select(dut)
    check_byte(await rx_byte(dut, 0x11, 0xEE), (0, 0), (0x11, 0xEE))
    check_byte(await rx_byte(dut, 0x22, 0xDD), (0x11, 0xEE), (0x22, 0xDD))
    await deselect(dut)


@cocotb.test()
async def test_rx_ignores_sclk_when_deselected(dut):
    await rx_reset(dut)
    await select(dut)
    await rx_byte(dut, 0x77, 0x88)
    await deselect(dut)

    for _ in range(20):
        assert await rx_bit(dut, random.randrange(2), random.randrange(2)) == (0, 0x77, 0x88)

    # those clocks must not have moved the bit counter
    await select(dut)
    check_byte(await rx_byte(dut, 0x35, 0xCA), (0x77, 0x88), (0x35, 0xCA))
    await deselect(dut)


@cocotb.test()
async def test_rx_aborted_frame(dut):
    """Deasserting cs part way through a byte discards partial data"""
    await rx_reset(dut)
    old = (0, 0)
    for n in range(1, 8):
        await select(dut)
        for _ in range(n):
            await rx_bit(dut, 1, 1)
        await deselect(dut)
        assert rx_state(dut) == (0, *old)

        new = (0x40 + n, 0x80 - n)
        await select(dut)
        check_byte(await rx_byte(dut, *new), old, new)
        await deselect(dut)
        old = new


@cocotb.test()
async def test_rx_async_reset(dut):
    await rx_reset(dut)
    await select(dut)
    await rx_byte(dut, 0xF0, 0x0F)

    dut.rx_rst_n.value = 0
    await Timer(1, unit="us")
    assert rx_state(dut) == (0, 0, 0)
    dut.rx_rst_n.value = 1

    # reset part way through a byte (cs_n still low) starts the next byte clean
    for _ in range(4):
        await rx_bit(dut, 1, 1)
    dut.rx_rst_n.value = 0
    await Timer(2, unit="us")
    dut.rx_rst_n.value = 1
    check_byte(await rx_byte(dut, 0x2D, 0xD2), (0, 0), (0x2D, 0xD2))
    await deselect(dut)


# loopback


def check_loopback(trace, old, new):
    """d_hold changes on the 8th sclk edge, d_tog is high for that one clock."""
    for i, (_, _, _, tog, hu, hr) in enumerate(trace):
        assert (hu, hr) == (old if i < 15 else new), f"clock {i}: d_hold = {(hu, hr)}"
        assert tog == (i == 15), f"clock {i}: d_tog = {tog}"


@cocotb.test()
async def test_loopback_frames(dut):
    await start(dut, "lb")
    old = (0, 0)
    for a, b in VECTORS + random_vectors(20, seed=3):
        trace = await send(dut, a, b, p="lb")
        check_frame(trace, a, b)
        check_loopback(trace, old, (a, b))
        old = (a, b)


@cocotb.test()
async def test_loopback_back_to_back(dut):
    await start(dut, "lb")
    frames = [(0xDE, 0xAD), (0xBE, 0xEF), (0x00, 0xFF), (0xA5, 0x5A)]
    trace = await send_held(dut, frames, p="lb")
    old = (0, 0)
    for n, new in enumerate(frames):
        chunk = trace[n * (FRAME + 1):(n + 1) * (FRAME + 1)]
        check_frame(chunk, *new)
        check_loopback(chunk, old, new)
        old = new