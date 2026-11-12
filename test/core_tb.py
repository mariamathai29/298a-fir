import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

TCLK_NS = 25                              # 40 MHz
S_IDLE, S_MAC, S_FIN, S_UPD = 0, 1, 2, 3


def s8(v):
    # 8-bit signed taps
    v = int(v) & 0xFF
    return v - 256 if v & 0x80 else v


def s14(v):
    # 14-bit signed weights
    v = int(v) & 0x3FFF
    return v - 0x4000 if v & 0x2000 else v


class AfCoreTB:
    def __init__(self, dut):
        self.dut = dut
        self.cycle = 0                    # falling edges since start()
        self.outputs = []                 # (cycle, y, e, w), signed

    async def start(self):
        # everything idle, reset
        d = self.dut
        d.rst.value = 1
        d.adapt_en.value = 0
        d.mu_sel.value = 0
        d.d_pre.value = 0
        d.d_stb.value = 0
        d.d_u.value = 0
        d.d_r.value = 0
        # start core clock, 40 mhz
        Clock(d.clk, TCLK_NS, "ns").start(start_high=False)
        cocotb.start_soon(self._monitor())

    async def reset(self, cycles=5):
        # init sequence, wait 5 falling, deassert reset
        await self.start()
        await ClockCycles(self.dut.clk, cycles, rising=False)
        self.dut.rst.value = 0
        await FallingEdge(self.dut.clk)

    async def _monitor(self):
        # check if frame will be transmitted, monitor output, error, weight lanes
        d = self.dut
        while True:
            await FallingEdge(d.clk)
            self.cycle += 1
            if d.t_load.value == 1:
                self.outputs.append((self.cycle, s8(d.t_y.value), s8(d.t_e.value),
                                     s8(d.t_w.value)))

    async def wait(self, cycles):
        # wait n cycles
        await ClockCycles(self.dut.clk, cycles, rising=False)

    async def send(self, u, r):
        # one input sample
        # send interfered sample (r), reference sample (u), assert pre-capture signal, then capture signal
        d = self.dut
        d.d_u.value = u & 0xFF
        d.d_r.value = r & 0xFF
        d.d_pre.value = 1
        await FallingEdge(d.clk)
        d.d_pre.value = 0
        d.d_stb.value = 1
        await FallingEdge(d.clk)
        d.d_stb.value = 0

    async def send_schedule(self, samples):
        """Present samples on a cycle schedule: (t, u, r) puts d_pre on cycle t
        and d_stb on t + 1, counted in falling edges from now. Times must be at
        least 2 apart (as from the SPI receiver, where they are >= 16)."""
        pre = {t: (u, r) for t, u, r in samples}
        d = self.dut
        for c in range(max(pre) + 2):
            if c in pre:
                d.d_u.value = pre[c][0] & 0xFF
                d.d_r.value = pre[c][1] & 0xFF
            d.d_pre.value = int(c in pre)
            d.d_stb.value = int(c - 1 in pre)
            await FallingEdge(d.clk)
        d.d_stb.value = 0

    def set_ctl(self, adapt_en, mu_sel):
        # adapt? LR value
        self.dut.adapt_en.value = adapt_en
        self.dut.mu_sel.value = mu_sel

    # DUT internal reads

    def state(self):
        return int(self.dut.cur.value)

    def taps(self):
        return [s8(self.dut.x[k].value) for k in range(4)]

    def weights(self):
        return [s14(self.dut.w[k].value) for k in range(4)]

    def set_weights(self, w):
        for k in range(4):
            self.dut.w[k].value = w[k] & 0x3FFF

    def set_taps(self, x):
        for k in range(4):
            self.dut.x[k].value = x[k] & 0xFF

    async def until_state(self, s, limit=100):
        # wait for falling edge when operating in some state
        for _ in range(limit):
            await FallingEdge(self.dut.clk)
            if self.state() == s:
                return
        raise AssertionError(f"state {s} not reached in {limit} cycles")

    async def step(self, u, r):
        # run a full step from idle to output smaple
        assert self.state() == S_IDLE, "step() must start from idle"
        n = len(self.outputs)
        await self.send(u, r)
        for _ in range(40):
            if len(self.outputs) > n:
                break
            await FallingEdge(self.dut.clk)
        else:
            raise AssertionError(f"no output for sample u={u} r={r}")
        await self.wait(4)                # rest of UPD
        _, y, e, _ = self.outputs[n]
        return y, e

    def snapshot(self):
        # control signals, state, cycle, tap + weight rings
        d = self.dut
        return {
            "cycle":   self.cycle,
            "state":   self.state(),
            "cnt":     int(d.cnt.value),
            "go":      int(d.go.value),
            "rot":      int(d.rot.value),
            "tx_load": int(d.t_load.value),
            "x":       self.taps(),
            "w":       self.weights(),
        }

    async def trace(self, cycles):
        # snapshot multiple cycles
        rows = []
        for _ in range(cycles):
            await FallingEdge(self.dut.clk)
            rows.append(self.snapshot())
        return rows
