"""cocotb testbench for <<NAME>>_top.

Drives the design through its real AXI-Lite register interface (via
cocotbext-axi) rather than <<NAME>>_core's plain ports directly -- this
exercises the auto-wired register integration, not just the core counter
logic. Runs against both the VHDL and SystemVerilog implementations via
the same test suite -- AXI-Lite signal names are identical across both
(VHDL is driven through tb/cocotb/vhdl/<<NAME>>_cocotb_top.vhd, a thin
flattening wrapper -- see tb/cocotb/Makefile for why).

Run via the top-level Makefile:
    make sim FRAMEWORK=cocotb SIM=ghdl       TOPLEVEL_HDL=vhdl
    make sim FRAMEWORK=cocotb SIM=verilator  TOPLEVEL_HDL=sv
    make sim FRAMEWORK=cocotb SIM=icarus     TOPLEVEL_HDL=sv

Note on read timing: axil.read()/axil.write() are real multi-cycle AXI-Lite
bus transactions (via cocotbext-axi's AxiLiteMaster), not single-cycle
register peeks. If the counter is enabled and actively counting *during* a
transaction, it keeps counting for the transaction's whole duration, so a
naive "assert pulse_count == N" after N RisingEdge waits does not hold once
a bus read/write is involved. This was measured empirically: with this
project's generated register file (a single-cycle-ready AXI-Lite slave),
and cocotbext-axi's default AxiLiteMaster
(no injected backpressure), two consecutive read_status() calls separated by
W pure RisingEdge waits always satisfy:
    count_after - count_before == (W + READ_TO_READ_OVERHEAD_CYCLES) * step
READ_TO_READ_OVERHEAD_CYCLES was measured as exactly 4, completely
deterministically (zero jitter over W in {0,1,2,3,5,7,10} and step in
{1,5}), identically across GHDL/VHDL, Verilator/SV and Icarus/SV. This lets
test_count_up/test_increment_step keep exact per-step equality checks
(rather than degrading to a ">=" or tolerance-band check) despite the
interleaved live counting.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from cocotbext.axi import AxiLiteBus, AxiLiteMaster

CONF_ADDR = 0
COMMAND_ADDR = 4
STATUS_ADDR = 8

# See the module docstring: empirically measured, deterministic extra clock
# edges consumed by a read_status() call, on top of any explicit RisingEdge
# waits placed around it.
READ_TO_READ_OVERHEAD_CYCLES = 4


async def setup(dut) -> AxiLiteMaster:
    """Start the clock, release reset, return a ready-to-use AXI-Lite master."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.rst_n.value = 0
    dut.pulse_i.value = 0
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi"), dut.clk, dut.rst_n, reset_active_level=False)
    for _ in range(5):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    return axil


async def write_conf(axil: AxiLiteMaster, enable: bool, increment: int) -> None:
    value = (1 if enable else 0) | (increment << 1)
    await axil.write(CONF_ADDR, value.to_bytes(4, "little"))


async def write_command_reset_count(axil: AxiLiteMaster, asserted: bool) -> None:
    await axil.write(COMMAND_ADDR, (1 if asserted else 0).to_bytes(4, "little"))


async def read_status(axil: AxiLiteMaster) -> tuple[int, int]:
    """Return (enabled, pulse_count)."""
    data = await axil.read(STATUS_ADDR, 4)
    value = int.from_bytes(data.data, "little")
    enabled = value & 0x1
    pulse_count = (value >> 1) & 0xFFFF
    return enabled, pulse_count


@cocotb.test()
async def test_count_up(dut):
    """Counter increments by the configured step on each clock when enabled.

    Each loop iteration is (RisingEdge, read_status) -- a fixed, known shape
    -- so the exact expected count is prev + (1 + READ_TO_READ_OVERHEAD_CYCLES)
    for increment=1. This keeps a genuine per-step equality check (able to
    catch "counts too fast/slow" bugs at every step), unlike a coarser
    baseline-vs-final-value-only check.
    """
    axil = await setup(dut)
    await write_conf(axil, enable=True, increment=1)

    _, prev_count = await read_status(axil)
    enabled = None
    for step in range(1, 9):
        await RisingEdge(dut.clk)
        enabled, count = await read_status(axil)
        expected = prev_count + 1 + READ_TO_READ_OVERHEAD_CYCLES
        assert count == expected, (
            f"step {step}: expected count={expected} "
            f"(prev={prev_count} + 1 RisingEdge + "
            f"{READ_TO_READ_OVERHEAD_CYCLES}-cycle read overhead), got {count}"
        )
        prev_count = count
    assert enabled == 1, "enabled should be high when counting"


@cocotb.test()
async def test_increment_step(dut):
    """Counter adds the configured step (not just 1) per clock.

    Same exact-equality pattern as test_count_up, scaled by `step`: the
    read-transaction overhead advances the counter by
    READ_TO_READ_OVERHEAD_CYCLES clock edges, each worth `step` counts.
    """
    axil = await setup(dut)
    step = 5
    await write_conf(axil, enable=True, increment=step)

    _, prev_count = await read_status(axil)
    for i in range(1, 5):
        await RisingEdge(dut.clk)
        _, count = await read_status(axil)
        expected = prev_count + (1 + READ_TO_READ_OVERHEAD_CYCLES) * step
        assert count == expected, (
            f"iteration {i}: expected count={expected} "
            f"(prev={prev_count} + (1 + {READ_TO_READ_OVERHEAD_CYCLES}) * "
            f"{step}), got {count}"
        )
        prev_count = count


@cocotb.test()
async def test_reset_count(dut):
    """command.reset_count clears the counter (write-1-then-write-0 pulse).

    The counter is disabled before checking the reset (disabling is
    independently verified by test_disable_holds_count to freeze the count
    exactly), so the post-reset read is quiescent -- no bus transaction races
    a live counter -- and can assert an exact value.
    """
    axil = await setup(dut)
    await write_conf(axil, enable=True, increment=1)
    for _ in range(5):
        await RisingEdge(dut.clk)

    await write_conf(axil, enable=False, increment=1)
    enabled, pre_reset_count = await read_status(axil)
    assert enabled == 0, "enabled should be low right after disabling"
    assert pre_reset_count > 0, "sanity check: counter should have advanced before reset"

    await write_command_reset_count(axil, True)
    await RisingEdge(dut.clk)
    await write_command_reset_count(axil, False)
    await RisingEdge(dut.clk)

    _, pulse_count = await read_status(axil)
    assert pulse_count == 0, "count should be 0 after reset pulse"


@cocotb.test()
async def test_disable_holds_count(dut):
    """Count holds its value when enable is deasserted.

    The count is captured via a read taken *after* the disabling write has
    already committed (enabled == 0 observed directly), so its value is
    known-quiescent -- no live counter to race -- letting the subsequent
    "still equal" check after further waiting be a plain exact comparison.
    """
    axil = await setup(dut)
    await write_conf(axil, enable=True, increment=1)
    for _ in range(4):
        await RisingEdge(dut.clk)

    await write_conf(axil, enable=False, increment=1)
    enabled, held_count = await read_status(axil)
    assert enabled == 0, "enabled should be low when disabled"
    assert held_count > 0, "sanity check: counter should have advanced while enabled"

    for _ in range(4):
        await RisingEdge(dut.clk)

    enabled, pulse_count = await read_status(axil)
    assert pulse_count == held_count, "count should hold when disabled"
    assert enabled == 0, "enabled should still be low when disabled"


@cocotb.test()
async def test_saturation(dut):
    """Counter saturates at (2**COUNT_W)-1 rather than wrapping.

    Only a single read, taken well after saturation is guaranteed to have
    already occurred, so it is not racing a live counter (once saturated,
    further enabled cycles don't change the value) -- this check was
    already exact in the original design, no redesign needed.
    """
    axil = await setup(dut)
    max_val = (1 << 16) - 1  # 65535 for C_COUNT_W=16
    await write_conf(axil, enable=True, increment=255)

    cycles_to_saturate = max_val // 255 + 4
    for _ in range(cycles_to_saturate):
        await RisingEdge(dut.clk)

    _, pulse_count = await read_status(axil)
    assert pulse_count == max_val, f"Expected saturation at {max_val}, got {pulse_count}"
