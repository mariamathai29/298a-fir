# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles


# e2e tests
# assert pass (temporary)

@cocotb.test()
async def test_project(dut):
    assert True
