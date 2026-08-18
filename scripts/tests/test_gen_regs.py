"""Unit tests for scripts/gen_regs.py's port-parsing, field-mapping,
type-bridging, and marker-rewrite logic."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gen_regs  # noqa: E402


def test_parse_vhdl_ports_extracts_all_ports(vhdl_core_file):
    ports = gen_regs.parse_vhdl_ports(vhdl_core_file)
    assert set(ports) == {
        "clk", "rst_n", "enable_i", "increment_i",
        "reset_count_i", "enabled_o", "pulse_count_o",
    }


def test_parse_vhdl_ports_direction_and_type(vhdl_core_file):
    ports = gen_regs.parse_vhdl_ports(vhdl_core_file)
    assert ports["enable_i"].direction == "in"
    assert ports["enabled_o"].direction == "out"
    assert ports["increment_i"].type_str == "integer range 1 to 255"
    assert ports["pulse_count_o"].type_str == "std_logic_vector(15 downto 0)"


def test_parse_vhdl_ports_missing_port_clause_raises(tmp_path):
    bad_file = tmp_path / "bad.vhd"
    bad_file.write_text("entity demo_core is\nend entity demo_core;\n")
    with pytest.raises(ValueError, match="No entity port clause"):
        gen_regs.parse_vhdl_ports(bad_file)


def test_parse_sv_ports_extracts_all_ports(sv_core_file):
    ports = gen_regs.parse_sv_ports(sv_core_file)
    assert set(ports) == {
        "clk", "rst_n", "enable_i", "increment_i",
        "reset_count_i", "enabled_o", "pulse_count_o",
    }


def test_parse_sv_ports_direction_and_type(sv_core_file):
    ports = gen_regs.parse_sv_ports(sv_core_file)
    assert ports["enable_i"].direction == "input"
    assert ports["enabled_o"].direction == "output"
    assert ports["increment_i"].type_str == "int unsigned"
    assert ports["pulse_count_o"].type_str == "logic [COUNT_W-1:0]"


def test_parse_sv_ports_missing_module_raises(tmp_path):
    bad_file = tmp_path / "bad.sv"
    bad_file.write_text("// no module here\n")
    with pytest.raises(ValueError, match="No module port clause"):
        gen_regs.parse_sv_ports(bad_file)


def test_build_field_mappings_derives_port_names_and_directions(demo_register_list):
    mappings = gen_regs.build_field_mappings(demo_register_list)
    by_field = {(m.register_name, m.field_name): m for m in mappings}

    enable = by_field[("conf", "enable")]
    assert enable.direction == "down"
    assert enable.port_name == "enable_i"
    assert enable.needs_cast is False

    reset_count = by_field[("command", "reset_count")]
    assert reset_count.direction == "down"
    assert reset_count.port_name == "reset_count_i"

    pulse_count = by_field[("status", "pulse_count")]
    assert pulse_count.direction == "up"
    assert pulse_count.port_name == "pulse_count_o"
    assert pulse_count.needs_cast is True
    assert pulse_count.width == 16

    increment = by_field[("conf", "increment")]
    assert increment.needs_cast is False


def test_build_field_mappings_rejects_unsupported_mode(tmp_path):
    from hdl_registers.parser.toml import from_toml

    toml_file = tmp_path / "bad_regs.toml"
    toml_file.write_text(
        '[command]\nmode = "wpulse"\n[command.reset_count]\ntype = "bit"\n'
        'default_value = "0"\n'
    )
    register_list = from_toml(name="demo", toml_file=toml_file)
    with pytest.raises(ValueError, match="wpulse"):
        gen_regs.build_field_mappings(register_list)


def test_resolve_port_mappings_passes_when_all_fields_match(demo_register_list, vhdl_core_file):
    mappings = gen_regs.build_field_mappings(demo_register_list)
    core_ports = gen_regs.parse_vhdl_ports(vhdl_core_file)
    gen_regs.resolve_port_mappings(mappings, core_ports)  # must not raise


def test_resolve_port_mappings_raises_on_missing_port(demo_register_list):
    mappings = gen_regs.build_field_mappings(demo_register_list)
    core_ports = {}  # no ports at all
    with pytest.raises(ValueError, match="enable_i"):
        gen_regs.resolve_port_mappings(mappings, core_ports)


def test_resolve_port_mappings_raises_on_direction_mismatch(demo_register_list, vhdl_core_file):
    mappings = gen_regs.build_field_mappings(demo_register_list)
    core_ports = gen_regs.parse_vhdl_ports(vhdl_core_file)
    core_ports["enable_i"].direction = "out"  # flip it
    with pytest.raises(ValueError, match="enable_i"):
        gen_regs.resolve_port_mappings(mappings, core_ports)


def test_build_passthrough_mappings_matches_clk_and_rst_n(demo_register_list, vhdl_core_file):
    mappings = gen_regs.build_field_mappings(demo_register_list)
    core_ports = gen_regs.parse_vhdl_ports(vhdl_core_file)
    top_ports = {
        "clk": gen_regs.Port("clk", "in", "std_logic"),
        "rst_n": gen_regs.Port("rst_n", "in", "std_logic"),
    }
    passthrough = gen_regs.build_passthrough_mappings(core_ports, mappings, top_ports)
    assert passthrough == {"clk": "clk", "rst_n": "rst_n"}


def test_build_passthrough_mappings_raises_on_unmatched_port(demo_register_list, vhdl_core_file):
    mappings = gen_regs.build_field_mappings(demo_register_list)
    core_ports = gen_regs.parse_vhdl_ports(vhdl_core_file)
    core_ports["extra_i"] = gen_regs.Port("extra_i", "in", "std_logic")
    top_ports = {
        "clk": gen_regs.Port("clk", "in", "std_logic"),
        "rst_n": gen_regs.Port("rst_n", "in", "std_logic"),
    }
    with pytest.raises(ValueError, match="extra_i"):
        gen_regs.build_passthrough_mappings(core_ports, mappings, top_ports)
