"""Resolves <<NAME>>_top's register/field addresses and bit positions directly
from regs/<<NAME>>_regs.toml, via the same hdl_registers API scripts/gen_regs.py
already uses -- so nothing in this testbench hardcodes an address or bit
shift that could silently desync from a future register-map change.
"""

from dataclasses import dataclass, field
from pathlib import Path

from hdl_registers.parser.toml import from_toml
from hdl_registers.register_array import RegisterArray

_REGS_TOML = Path(__file__).resolve().parents[3] / "regs" / "<<NAME>>_regs.toml"


@dataclass
class FieldInfo:
    shift: int
    width: int


@dataclass
class RegInfo:
    address: int
    fields: dict[str, FieldInfo] = field(default_factory=dict)


def load_register_map() -> dict[str, RegInfo]:
    register_list = from_toml("<<NAME>>", _REGS_TOML)
    regs: dict[str, RegInfo] = {}
    for register in register_list.register_objects:
        if isinstance(register, RegisterArray):
            continue
        reg_info = RegInfo(address=4 * register.index)
        for f in register.fields:
            reg_info.fields[f.name] = FieldInfo(shift=f.base_index, width=f.width)
        regs[register.name] = reg_info
    return regs
