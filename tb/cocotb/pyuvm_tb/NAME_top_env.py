"""pyuvm environment for <<NAME>>_top. RegAgent wraps cocotbext-axi's
AxiLiteMaster (register reads/writes) on the flat s_axi_* signals both language
wrappers expose (tb/cocotb/<<NAME>>_top_cocotb_top.sv, vhdl/<<NAME>>_cocotb_top.vhd).

Deliberately lean sequencer layer: with one agent and no concurrency to
arbitrate, a full uvm_sequencer (get_next_item/item_done handshake) is more
ceremony than value -- sequences call driver methods directly. The ceiling
this accepts: the agent can't arbitrate multiple concurrent sequences; add a
sequencer when a second agent (e.g. a pulse driver) needs one.
"""

import cocotb
from cocotb.triggers import with_timeout
from cocotbext.axi import AxiLiteBus, AxiLiteMaster
from pyuvm import uvm_agent, uvm_driver, uvm_env

from pyuvm_tb.<<NAME>>_regs import load_register_map

# Generous bound on one register access: a bare await can hang forever against
# a DUT that never asserts a handshake signal.
TIMEOUT_NS = 2000


class RegDriver(uvm_driver):
    def build_phase(self):
        self.dut = cocotb.top
        self.regs = load_register_map()
        self.axil_master = AxiLiteMaster(
            AxiLiteBus.from_prefix(self.dut, "s_axi"), self.dut.clk, self.dut.rst_n, reset_active_level=False
        )

    async def write(self, name: str, value: int) -> None:
        await with_timeout(self.axil_master.write_dword(self.regs[name].address, value), TIMEOUT_NS, "ns")

    async def read(self, name: str) -> int:
        return await with_timeout(self.axil_master.read_dword(self.regs[name].address), TIMEOUT_NS, "ns")

    async def write_fields(self, reg: str, **values: int) -> None:
        """Write a whole register from named field values (unnamed fields are 0)."""
        word = 0
        for name, value in values.items():
            word |= value << self.regs[reg].fields[name].shift
        await self.write(reg, word)

    async def read_field(self, reg: str, field: str) -> int:
        f = self.regs[reg].fields[field]
        return ((await self.read(reg)) >> f.shift) & ((1 << f.width) - 1)


class RegAgent(uvm_agent):
    def build_phase(self):
        self.driver = RegDriver("driver", self)


class CounterEnv(uvm_env):
    def build_phase(self):
        self.reg_agent = RegAgent("reg_agent", self)
