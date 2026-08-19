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


def test_rewrite_marker_region_replaces_only_between_markers(tmp_path):
    original = (
        "line before\n"
        "-- BEGIN X\n"
        "old content\n"
        "-- END X\n"
        "line after\n"
    )
    path = tmp_path / "f.vhd"
    path.write_text(original)

    gen_regs.rewrite_marker_region(path, "-- BEGIN X", "-- END X", "new content")

    result = path.read_text()
    assert "line before" in result
    assert "line after" in result
    assert "old content" not in result
    assert "new content" in result


def test_rewrite_marker_region_raises_if_markers_missing(tmp_path):
    path = tmp_path / "f.vhd"
    path.write_text("no markers here\n")
    with pytest.raises(ValueError, match="Could not find marker"):
        gen_regs.rewrite_marker_region(path, "-- BEGIN X", "-- END X", "content")


def test_rewrite_marker_region_is_idempotent(tmp_path):
    path = tmp_path / "f.vhd"
    path.write_text("-- BEGIN X\nold\n-- END X\n")
    gen_regs.rewrite_marker_region(path, "-- BEGIN X", "-- END X", "same content")
    first = path.read_text()
    gen_regs.rewrite_marker_region(path, "-- BEGIN X", "-- END X", "same content")
    second = path.read_text()
    assert first == second


def test_render_vhdl_signals_block_only_includes_cast_fields(demo_register_list):
    mappings = gen_regs.build_field_mappings(demo_register_list)
    block = gen_regs.render_vhdl_signals_block(mappings)
    assert "pulse_count" in block
    assert "std_logic_vector(16 - 1 downto 0)" in block
    assert "enable" not in block  # Bit fields never need a bridging signal


def test_render_vhdl_wiring_block_contains_expected_connections(demo_register_list):
    mappings = gen_regs.build_field_mappings(demo_register_list)
    passthrough = {"clk": "clk", "rst_n": "rst_n"}
    block = gen_regs.render_vhdl_wiring_block("demo", mappings, passthrough)
    assert "u_core : entity work.demo_core" in block
    assert "clk => clk" in block
    assert "rst_n => rst_n" in block
    assert "enable_i" in block and "regs_down.conf.enable" in block
    assert "reset_count_i" in block and "regs_down.command.reset_count" in block
    assert "enabled_o" in block and "regs_up.status.enabled" in block
    # BitVector "up" field connects to the bridging signal, not the record directly.
    assert "pulse_count_o" in block and "=> pulse_count" in block
    assert "regs_up.status.pulse_count <= unsigned(pulse_count)" in block


def test_render_vhdl_wiring_block_casts_down_bitvector_inline(tmp_path):
    # This project's current register map has no 'down' BitVector field, but
    # the renderer must still handle one correctly: input-port associations
    # accept an arbitrary expression in VHDL, so this needs an inline
    # std_logic_vector(...) cast, not a bridging signal (verified empirically
    # with GHDL -- see the note above render_vhdl_wiring_block).
    from hdl_registers.parser.toml import from_toml

    toml_file = tmp_path / "demo_regs.toml"
    toml_file.write_text(
        '[conf]\nmode = "w"\n[conf.mask]\ntype = "bit_vector"\nwidth = 8\n'
        'default_value = "00000000"\n'
    )
    register_list = from_toml(name="demo", toml_file=toml_file)
    mappings = gen_regs.build_field_mappings(register_list)

    block = gen_regs.render_vhdl_wiring_block("demo", mappings, {})

    assert "mask_i => std_logic_vector(regs_down.conf.mask)" in block
    # No bridging signal for the 'down' direction.
    assert "regs_down.conf.mask <=" not in block


def test_render_sv_wiring_block_contains_expected_connections(demo_register_list):
    mappings = gen_regs.build_field_mappings(demo_register_list)
    passthrough = {"clk": "clk", "rst_n": "rst_n"}
    block = gen_regs.render_sv_wiring_block("demo", mappings, passthrough)
    assert "demo_core u_core (" in block
    assert ".clk(clk)" in block
    assert ".rst_n(rst_n)" in block
    assert ".enable_i(hwif_out.conf.enable.value)" in block
    assert ".reset_count_i(hwif_out.command.reset_count.value)" in block
    assert ".enabled_o(hwif_in.status.enabled.next)" in block
    # SV struct fields are directly compatible -- no bridging signal needed.
    assert ".pulse_count_o(hwif_in.status.pulse_count.next)" in block


def test_detect_language_flat_vhdl(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo_core.vhd").write_text("-- stub\n")
    assert gen_regs.detect_language(tmp_path) == "vhdl"


def test_detect_language_flat_sv(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo_core.sv").write_text("// stub\n")
    assert gen_regs.detect_language(tmp_path) == "sv"


def test_detect_language_nested_pre_init_prefers_vhdl(tmp_path):
    (tmp_path / "src" / "vhdl").mkdir(parents=True)
    (tmp_path / "src" / "sv").mkdir(parents=True)
    (tmp_path / "src" / "vhdl" / "demo_core.vhd").write_text("-- stub\n")
    (tmp_path / "src" / "sv" / "demo_core.sv").write_text("// stub\n")
    assert gen_regs.detect_language(tmp_path) == "vhdl"


def test_detect_language_raises_when_nothing_found(tmp_path):
    (tmp_path / "src").mkdir()
    with pytest.raises(ValueError, match="run `make init` first"):
        gen_regs.detect_language(tmp_path)


def test_flat_core_and_top_exist_true_when_both_present(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo_core.vhd").write_text("-- stub\n")
    (tmp_path / "src" / "demo_top.vhd").write_text("-- stub\n")
    assert gen_regs._flat_core_and_top_exist(tmp_path, "demo", "vhdl") is True


def test_flat_core_and_top_exist_false_for_nested_layout(tmp_path):
    # Simulates the pre-init repo layout: core exists, but nested, not flat.
    (tmp_path / "src" / "vhdl").mkdir(parents=True)
    (tmp_path / "src" / "vhdl" / "demo_core.vhd").write_text("-- stub\n")
    (tmp_path / "src" / "vhdl" / "demo_top.vhd").write_text("-- stub\n")
    assert gen_regs._flat_core_and_top_exist(tmp_path, "demo", "vhdl") is False


def test_flat_core_and_top_exist_false_when_top_missing(tmp_path):
    # Simulates a second regs/*.toml with no matching top file.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "other_core.vhd").write_text("-- stub\n")
    assert gen_regs._flat_core_and_top_exist(tmp_path, "other", "vhdl") is False
