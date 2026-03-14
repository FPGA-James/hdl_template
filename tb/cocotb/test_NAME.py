"""cocotb testbench for <<NAME>>_core.

Tests the pulse counter core directly without the AXI-Lite register block.
Runs against both the VHDL and SystemVerilog implementations via the same
test suite — port names are identical across both languages.

Run via the top-level Makefile:
    make sim FRAMEWORK=cocotb SIM=ghdl       TOPLEVEL_HDL=vhdl
    make sim FRAMEWORK=cocotb SIM=verilator  TOPLEVEL_HDL=sv
    make sim FRAMEWORK=cocotb SIM=icarus     TOPLEVEL_HDL=sv
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


async def reset_dut(dut, cycles: int = 5) -> None:
    """Assert rst_n low for *cycles* clock edges then release."""
    dut.rst_n.value = 0
    dut.enable_i.value = 0
    dut.increment_i.value = 1
    dut.reset_count_i.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_count_up(dut):
    """Counter increments by increment_i on each clock when enabled."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    dut.enable_i.value = 1
    dut.increment_i.value = 1

    for expected in range(1, 9):
        await RisingEdge(dut.clk)
        assert int(dut.pulse_count_o.value) == expected, (
            f"Expected count={expected}, got {int(dut.pulse_count_o.value)}"
        )
    assert int(dut.enabled_o.value) == 1, "enabled_o should be high when counting"


@cocotb.test()
async def test_increment_step(dut):
    """Counter adds increment_i (not just 1) per clock."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    step = 5
    dut.enable_i.value = 1
    dut.increment_i.value = step

    for i in range(1, 5):
        await RisingEdge(dut.clk)
        assert int(dut.pulse_count_o.value) == i * step, (
            f"Expected count={i * step}, got {int(dut.pulse_count_o.value)}"
        )


@cocotb.test()
async def test_reset_count(dut):
    """reset_count_i clears the counter in one cycle."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    dut.enable_i.value = 1
    dut.increment_i.value = 1
    for _ in range(5):
        await RisingEdge(dut.clk)

    assert int(dut.pulse_count_o.value) == 5, "pre-reset count should be 5"

    dut.reset_count_i.value = 1
    await RisingEdge(dut.clk)
    dut.reset_count_i.value = 0
    await RisingEdge(dut.clk)

    assert int(dut.pulse_count_o.value) == 0, "count should be 0 after reset pulse"


@cocotb.test()
async def test_disable_holds_count(dut):
    """Count holds its value when enable_i is deasserted."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    dut.enable_i.value = 1
    dut.increment_i.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)

    assert int(dut.pulse_count_o.value) == 4

    dut.enable_i.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)

    assert int(dut.pulse_count_o.value) == 4, "count should hold when disabled"
    assert int(dut.enabled_o.value) == 0, "enabled_o should be low when disabled"


@cocotb.test()
async def test_saturation(dut):
    """Counter saturates at (2**COUNT_W)-1 rather than wrapping."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    max_val = (1 << 16) - 1  # 65535 for C_COUNT_W=16
    dut.enable_i.value = 1
    dut.increment_i.value = 255

    # Run enough cycles to guarantee saturation
    cycles_to_saturate = max_val // 255 + 4
    for _ in range(cycles_to_saturate):
        await RisingEdge(dut.clk)

    assert int(dut.pulse_count_o.value) == max_val, (
        f"Expected saturation at {max_val}, got {int(dut.pulse_count_o.value)}"
    )
