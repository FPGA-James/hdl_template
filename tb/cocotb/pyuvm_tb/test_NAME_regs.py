"""Pure-Python unit test for <<NAME>>_regs.py's register/field address
resolution -- no simulator involved (matches how
scripts/tests/test_gen_regs.py tests gen_regs.py's own TOML parsing)."""

from pyuvm_tb.<<NAME>>_regs import load_register_map


def test_register_addresses_match_register_map():
    """Byte address = 4 * register index in regs/<<NAME>>_regs.toml (cross-check
    against out/regs/c/<<NAME>>_regs.h after `make regs` if the map changes)."""
    regs = load_register_map()
    assert regs["conf"].address == 0x0
    assert regs["command"].address == 0x4
    assert regs["status"].address == 0x8


def test_field_bit_positions_match_register_map():
    regs = load_register_map()
    assert regs["conf"].fields["enable"].shift == 0
    assert regs["conf"].fields["increment"].shift == 1
    assert regs["conf"].fields["increment"].width == 8
    assert regs["command"].fields["reset_count"].shift == 0
    assert regs["status"].fields["enabled"].shift == 0
    assert regs["status"].fields["pulse_count"].shift == 1
    assert regs["status"].fields["pulse_count"].width == 16
