"""pyuvm testbench for <<NAME>>_top -- drives the DUT through its real AXI4-Lite
register interface and checks it against the CounterModel reference model.

Run via the top-level Makefile (either language):
    make sim FRAMEWORK=cocotb SIM=verilator TOPLEVEL_HDL=sv  PYUVM=1
    make sim FRAMEWORK=cocotb SIM=ghdl      TOPLEVEL_HDL=vhdl PYUVM=1

Timing note: a register read is a multi-cycle bus transaction during which an
enabled counter keeps counting, so tests compare exact values only while the
counter is disabled (it holds), and use bounds while it runs.
"""

import cocotb
import pyuvm
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from pyuvm import uvm_test

from pyuvm_tb.<<NAME>>_golden_model import MAX_COUNT, CounterModel
from pyuvm_tb.<<NAME>>_top_env import CounterEnv
from pyuvm_tb.<<NAME>>_top_sequences import ConfigureSeq, ResetCountSeq

# Clock edges a count can advance by between the "disable" write landing and the
# status read sampling it, beyond the waited cycles (bus latency headroom).
BUS_SLACK_CYCLES = 24


async def _reset(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.pulse_i.value = 0
    dut.s_axi_awvalid.value = 0
    dut.s_axi_wvalid.value = 0
    dut.s_axi_bready.value = 0
    dut.s_axi_arvalid.value = 0
    dut.s_axi_rready.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 1)


class _CounterTest(uvm_test):
    def build_phase(self):
        self.env = CounterEnv("env", self)

    async def configure(self, reg, enable: bool, increment: int) -> None:
        await ConfigureSeq("configure", reg, enable, increment).start()


@pyuvm.test()
class TestRegisterSanity(_CounterTest):
    """Reset values, then a conf write reads back field-for-field."""

    async def run_phase(self):
        self.raise_objection()
        await _reset(cocotb.top)
        reg = self.env.reg_agent.driver

        assert await reg.read("status") == 0, "status is 0 after reset (disabled, count 0)"
        assert await reg.read_field("conf", "enable") == 0
        assert await reg.read_field("conf", "increment") == 1, "conf.increment resets to its default, 1"

        await reg.write_fields("conf", enable=0, increment=200)
        assert await reg.read_field("conf", "enable") == 0
        assert await reg.read_field("conf", "increment") == 200
        self.drop_objection()


@pyuvm.test()
class TestCountsThenHoldsWhenDisabled(_CounterTest):
    """Counting advances by whole increments, within bounds from the model;
    once disabled the count holds exactly."""

    async def run_phase(self):
        self.raise_objection()
        await _reset(cocotb.top)
        reg = self.env.reg_agent.driver
        model = CounterModel()

        await self.configure(reg, enable=True, increment=5)
        model.configure(enable=True, increment=5)
        await ClockCycles(cocotb.top.clk, 20)
        model.tick(20)
        await self.configure(reg, enable=False, increment=5)

        held = await reg.read_field("status", "pulse_count")
        assert held % 5 == 0, f"count {held} is not a whole number of increments"
        assert model.count <= held <= model.count + 5 * BUS_SLACK_CYCLES, f"count {held} outside model bounds"

        await ClockCycles(cocotb.top.clk, 20)
        assert await reg.read_field("status", "pulse_count") == held, "count must hold while disabled"
        self.drop_objection()


@pyuvm.test()
class TestSaturates(_CounterTest):
    """Largest increment saturates at the model's MAX_COUNT and stays there."""

    async def run_phase(self):
        self.raise_objection()
        await _reset(cocotb.top)
        reg = self.env.reg_agent.driver
        model = CounterModel()

        await self.configure(reg, enable=True, increment=255)
        model.configure(enable=True, increment=255)
        await ClockCycles(cocotb.top.clk, 300)  # 257 cycles reach 65535
        model.tick(10_000)
        await self.configure(reg, enable=False, increment=255)

        assert await reg.read_field("status", "pulse_count") == model.count == MAX_COUNT
        self.drop_objection()


@pyuvm.test()
class TestResetCount(_CounterTest):
    """command.reset_count clears the count (checked while disabled, so it stays 0)."""

    async def run_phase(self):
        self.raise_objection()
        await _reset(cocotb.top)
        reg = self.env.reg_agent.driver

        await self.configure(reg, enable=True, increment=3)
        await ClockCycles(cocotb.top.clk, 10)
        await self.configure(reg, enable=False, increment=3)
        assert await reg.read_field("status", "pulse_count") > 0, "counter should have counted"

        await ResetCountSeq("reset", reg).start()
        assert await reg.read_field("status", "pulse_count") == 0, "reset_count must clear the count"
        self.drop_objection()


@pyuvm.test()
class TestOverlappedRegisterAccess(_CounterTest):
    """Several AxiLiteMaster transactions in flight at once, then every value
    read back. The SV register file's decode stage is registered
    (scripts/gen_regs.py, _register_sv_decode), so a request is still being
    applied while the next one sits in the AXI skid registers; this checks each
    write lands with its own data, in order. The counter stays disabled so
    status is stable."""

    async def run_phase(self):
        self.raise_objection()
        await _reset(cocotb.top)
        reg = self.env.reg_agent.driver

        # Back-to-back conf writes issued together: the last one must win.
        writes = [
            cocotb.start_soon(reg.write_fields("conf", enable=0, increment=3)),
            cocotb.start_soon(reg.write_fields("conf", enable=0, increment=9)),
            cocotb.start_soon(reg.write_fields("conf", enable=0, increment=77)),
        ]
        for w in writes:
            await w
        assert await reg.read_field("conf", "increment") == 77, "last of the in-flight writes must win"

        # A write and a read of a different register in flight together.
        w = cocotb.start_soon(reg.write_fields("conf", enable=0, increment=12))
        r = cocotb.start_soon(reg.read("status"))
        await w
        assert await r == 0, "interleaved status read returned the wrong value"
        assert await reg.read_field("conf", "increment") == 12
        self.drop_objection()
