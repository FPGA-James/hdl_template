"""Thin pyuvm sequence wrappers for <<NAME>>_top scenarios. They call the
register driver directly rather than going through a uvm_sequencer -- see
<<NAME>>_top_env.py's module docstring for why."""

from pyuvm import uvm_sequence


class ConfigureSeq(uvm_sequence):
    def __init__(self, name: str, reg_driver, enable: bool, increment: int):
        super().__init__(name)
        self.reg_driver = reg_driver
        self.enable = enable
        self.increment = increment

    async def body(self):
        await self.reg_driver.write_fields("conf", enable=int(self.enable), increment=self.increment)


class ResetCountSeq(uvm_sequence):
    """command.reset_count is a held level: write 1, then 0."""

    def __init__(self, name: str, reg_driver):
        super().__init__(name)
        self.reg_driver = reg_driver

    async def body(self):
        await self.reg_driver.write_fields("command", reset_count=1)
        await self.reg_driver.write_fields("command", reset_count=0)
