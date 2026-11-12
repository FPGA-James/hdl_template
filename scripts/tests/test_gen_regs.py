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


def test_parse_sv_ports_captures_interface_ports(tmp_path):
    core_file = tmp_path / "demo_core.sv"
    core_file.write_text(
        "module demo_core (\n"
        "    input  logic clk,\n"
        "    input  logic rst_n,\n"
        "    axis_if.slave  s_axis,\n"
        "    axis_if.master m_axis\n"
        ");\n"
        "endmodule : demo_core\n"
    )
    ports = gen_regs.parse_sv_ports(core_file)
    assert set(ports) == {"clk", "rst_n", "s_axis", "m_axis"}
    assert ports["s_axis"].direction == "interface"
    assert ports["s_axis"].type_str == "axis_if.slave"
    assert ports["m_axis"].direction == "interface"
    assert ports["m_axis"].type_str == "axis_if.master"


def test_build_passthrough_mappings_connects_interface_ports_by_name(demo_register_list):
    mappings = gen_regs.build_field_mappings(demo_register_list)
    core_ports = {
        "clk": gen_regs.Port("clk", "input", "logic"),
        "rst_n": gen_regs.Port("rst_n", "input", "logic"),
        "enable_i": gen_regs.Port("enable_i", "input", "logic"),
        "increment_i": gen_regs.Port("increment_i", "input", "int unsigned"),
        "reset_count_i": gen_regs.Port("reset_count_i", "input", "logic"),
        "enabled_o": gen_regs.Port("enabled_o", "output", "logic"),
        "pulse_count_o": gen_regs.Port("pulse_count_o", "output", "logic [15:0]"),
        "s_axis": gen_regs.Port("s_axis", "interface", "axis_if.slave"),
        "m_axis": gen_regs.Port("m_axis", "interface", "axis_if.master"),
    }
    top_ports = {
        "clk": gen_regs.Port("clk", "input", "logic"),
        "rst_n": gen_regs.Port("rst_n", "input", "logic"),
        "s_axis": gen_regs.Port("s_axis", "interface", "axis_if.slave"),
        "m_axis": gen_regs.Port("m_axis", "interface", "axis_if.master"),
    }
    passthrough = gen_regs.build_passthrough_mappings(core_ports, mappings, top_ports)
    assert passthrough["s_axis"] == "s_axis"
    assert passthrough["m_axis"] == "m_axis"


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
        '[command]\nmode = "r_wpulse"\n[command.reset_count]\ntype = "bit"\n'
        'default_value = "0"\n'
    )
    register_list = from_toml(name="demo", toml_file=toml_file)
    with pytest.raises(ValueError, match="r_wpulse"):
        gen_regs.build_field_mappings(register_list)


def test_build_field_mappings_supports_wpulse_mode(tmp_path):
    """wpulse is a real hdl_registers write-pulse mode (hardware sees an
    already-pulsed signal, no core-side edge detection needed) -- wired the
    same as plain 'w': down direction, '_i' suffix."""
    from hdl_registers.parser.toml import from_toml

    toml_file = tmp_path / "regs.toml"
    toml_file.write_text('[irq_clear]\nmode = "wpulse"\n[irq_clear.clear]\ntype = "bit"\n')
    register_list = from_toml(name="demo", toml_file=toml_file)

    mappings = gen_regs.build_field_mappings(register_list)
    assert len(mappings) == 1
    assert mappings[0].direction == "down"
    assert mappings[0].port_name == "clear_i"


def test_build_field_mappings_skips_no_core_wiring_registers(tmp_path, monkeypatch):
    """A register named in NO_CORE_WIRING_REGISTERS produces no FieldMapping at
    all -- no <<NAME>>_core port is ever required for it."""
    from hdl_registers.parser.toml import from_toml

    monkeypatch.setattr(gen_regs, "NO_CORE_WIRING_REGISTERS", {"gpio"})
    monkeypatch.setattr(gen_regs, "FIXED_VALUE_REGISTERS", {})

    toml_file = tmp_path / "regs.toml"
    toml_file.write_text('[gpio]\nmode = "r_w"\n[gpio.value]\ntype = "bit_vector"\nwidth = 32\n')
    register_list = from_toml(name="demo", toml_file=toml_file)

    assert gen_regs.build_field_mappings(register_list) == []


def test_build_field_mappings_skips_fixed_value_registers(tmp_path, monkeypatch):
    """A register named in FIXED_VALUE_REGISTERS produces no FieldMapping either
    -- it's driven by a compile-time constant in <name>_top, not <<NAME>>_core."""
    from hdl_registers.parser.toml import from_toml

    monkeypatch.setattr(gen_regs, "FIXED_VALUE_REGISTERS", {"module_id": 0x12345678})
    monkeypatch.setattr(gen_regs, "NO_CORE_WIRING_REGISTERS", set())

    toml_file = tmp_path / "regs.toml"
    toml_file.write_text('[module_id]\nmode = "r"\n[module_id.value]\ntype = "bit_vector"\nwidth = 32\n')
    register_list = from_toml(name="demo", toml_file=toml_file)

    assert gen_regs.build_field_mappings(register_list) == []


def test_build_fixed_value_lines_sv(tmp_path, monkeypatch):
    from hdl_registers.parser.toml import from_toml

    monkeypatch.setattr(gen_regs, "FIXED_VALUE_REGISTERS", {"module_id": 0x12345678})

    toml_file = tmp_path / "regs.toml"
    toml_file.write_text('[module_id]\nmode = "r"\n[module_id.value]\ntype = "bit_vector"\nwidth = 32\n')
    register_list = from_toml(name="demo", toml_file=toml_file)

    lines = gen_regs.build_fixed_value_lines(register_list, "sv")
    assert lines == ["    assign hwif_in.module_id.value.next = 32'h12345678;"]


def test_build_fixed_value_lines_vhdl(tmp_path, monkeypatch):
    from hdl_registers.parser.toml import from_toml

    monkeypatch.setattr(gen_regs, "FIXED_VALUE_REGISTERS", {"module_id": 0x12345678})

    toml_file = tmp_path / "regs.toml"
    toml_file.write_text('[module_id]\nmode = "r"\n[module_id.value]\ntype = "bit_vector"\nwidth = 32\n')
    register_list = from_toml(name="demo", toml_file=toml_file)

    lines = gen_regs.build_fixed_value_lines(register_list, "vhdl")
    assert lines == ["    regs_up.module_id.value <= to_unsigned(16#12345678#, 32);"]


def test_build_fixed_value_lines_skips_registers_not_present(tmp_path, monkeypatch):
    """FIXED_VALUE_REGISTERS naming a register this project's TOML doesn't
    define is simply skipped, not an error -- lets the constant dict be a
    superset across projects/templates."""
    from hdl_registers.parser.toml import from_toml

    monkeypatch.setattr(gen_regs, "FIXED_VALUE_REGISTERS", {"module_id": 0x1, "version": 0x2})

    toml_file = tmp_path / "regs.toml"
    toml_file.write_text('[module_id]\nmode = "r"\n[module_id.value]\ntype = "bit_vector"\nwidth = 32\n')
    register_list = from_toml(name="demo", toml_file=toml_file)

    lines = gen_regs.build_fixed_value_lines(register_list, "sv")
    assert len(lines) == 1


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


def test_rewrite_marker_region_preserves_end_marker_indentation(tmp_path):
    # Real project files indent the END marker to match surrounding code
    # (e.g. 4 spaces inside a VHDL architecture body) -- the rewrite must
    # preserve whatever indentation the file actually uses, not assume one.
    path = tmp_path / "f.vhd"
    path.write_text("    -- BEGIN X\n    old\n    -- END X\n")
    gen_regs.rewrite_marker_region(path, "-- BEGIN X", "-- END X", "new")
    assert "    -- END X" in path.read_text()
    assert "        -- END X" not in path.read_text()


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


def test_render_sv_wiring_block_includes_fixed_value_lines(demo_register_list):
    """fixed_value_lines (from build_fixed_value_lines) are included in the
    autogen region alongside the core instantiation, not silently dropped."""
    mappings = gen_regs.build_field_mappings(demo_register_list)
    block = gen_regs.render_sv_wiring_block(
        "demo", mappings, {}, fixed_value_lines=["    assign hwif_in.module_id.value.next = 32'h12345678;"]
    )
    assert "assign hwif_in.module_id.value.next = 32'h12345678;" in block
    assert "demo_core u_core (" in block


def test_render_vhdl_wiring_block_includes_fixed_value_lines(demo_register_list):
    mappings = gen_regs.build_field_mappings(demo_register_list)
    block = gen_regs.render_vhdl_wiring_block(
        "demo", mappings, {}, fixed_value_lines=["    regs_up.module_id.value <= to_unsigned(16#12345678#, 32);"]
    )
    assert "regs_up.module_id.value <= to_unsigned(16#12345678#, 32);" in block
    assert "u_core : entity work.demo_core" in block


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


def test_make_sv_synthesizable_packs_top_level_struct():
    text = "typedef struct {\n    logic value;\n} demo__out_t;\n"
    result = gen_regs._make_sv_synthesizable(text)
    assert "typedef struct packed {" in result
    assert "typedef struct {" not in result


def test_make_sv_synthesizable_packs_nested_anonymous_structs():
    # PeakRDL-regblock nests anonymous `struct { ... }` blocks inside a
    # named typedef -- every level must be packed, not just the outer one,
    # since SV forbids an unpacked member inside a packed struct.
    text = (
        "typedef struct {\n"
        "    struct {\n"
        "        logic value;\n"
        "    } enable;\n"
        "} field_storage_t;\n"
    )
    result = gen_regs._make_sv_synthesizable(text)
    assert result.count("struct packed {") == 2
    assert "struct {" not in result


def test_make_sv_synthesizable_does_not_double_pack_already_packed_struct():
    text = "typedef struct packed {\n    logic value;\n} rd_data_t;\n"
    result = gen_regs._make_sv_synthesizable(text)
    assert result.count("packed") == 1


def test_make_sv_synthesizable_strips_automatic_keyword():
    text = (
        "always_comb begin\n"
        "    automatic logic is_valid_addr;\n"
        "    automatic logic is_valid_rw;\n"
        "    is_valid_addr = '1;\n"
        "end\n"
    )
    result = gen_regs._make_sv_synthesizable(text)
    assert "automatic" not in result
    assert "logic is_valid_addr;" in result
    assert "logic is_valid_rw;" in result


def test_make_sv_synthesizable_leaves_unrelated_text_untouched():
    text = "module demo_top;\n    logic clk;\nendmodule\n"
    assert gen_regs._make_sv_synthesizable(text) == text


def test_render_sv_address_constants_computes_byte_addresses(demo_register_list):
    # Deliberately lowercase names (demo_conf_addr, not DEMO_CONF_ADDR) --
    # matching this project's own existing VHDL constant convention
    # (<name>_regs_pkg.vhd's demo_conf/demo_command/demo_status are
    # lowercase too), and critically so a <<NAME>>-template-substituted
    # testbench file can reference them: <<NAME>>_conf_addr becomes
    # myproject_conf_addr post-init, matching this exactly. An uppercased
    # name could never be produced by <<NAME>> substitution, which is a
    # literal, case-preserving text replacement.
    text = gen_regs.render_sv_address_constants(demo_register_list)
    assert "localparam int unsigned demo_conf_addr = 4 * 0;" in text
    assert "localparam int unsigned demo_command_addr = 4 * 1;" in text
    assert "localparam int unsigned demo_status_addr = 4 * 2;" in text


def test_render_sv_address_constants_wraps_in_named_package(demo_register_list):
    text = gen_regs.render_sv_address_constants(demo_register_list)
    assert text.startswith("package demo_regs_addr_pkg;")
    assert text.strip().endswith("endpackage")


def test_render_sv_address_constants_uses_real_index_across_a_register_array(
    demo_register_list_with_array,
):
    # A RegisterArray consumes multiple indices (one per array element) but
    # is a single entry in register_objects -- positional enumerate() would
    # give "status" index 1 (wrong; the real index is 5, since "chan" has
    # array_length=4) and would also emit a meaningless address for "chan"
    # itself. Regression test for the bug this caught: an earlier version
    # used enumerate() and silently produced wrong addresses for every
    # register following an array.
    text = gen_regs.render_sv_address_constants(demo_register_list_with_array)
    assert "localparam int unsigned demo_conf_addr = 4 * 0;" in text
    assert "localparam int unsigned demo_status_addr = 4 * 5;" in text
    assert "chan" not in text


def test_render_sv_address_constants_emits_address_width_when_given(demo_register_list):
    # The generated register file's address ports are this many bits wide. Its own
    # package names the constant in UPPERCASE (DEMO_REGISTER_FILE_AXI_LITE_MIN_ADDR_WIDTH),
    # which <<NAME>> substitution cannot produce, so the top slices s_axil.awaddr with
    # this lowercase copy instead.
    text = gen_regs.render_sv_address_constants(demo_register_list, addr_width=4)
    assert "localparam int unsigned demo_addr_width = 4;" in text


def test_render_sv_address_constants_omits_address_width_by_default(demo_register_list):
    assert "addr_width" not in gen_regs.render_sv_address_constants(demo_register_list)


def test_generate_sv_address_package_carries_the_register_files_own_address_width(
    demo_register_list, tmp_path
):
    gen_regs.generate_sv(demo_register_list, tmp_path)
    reg_pkg = (tmp_path / "demo_register_file_axi_lite_pkg.sv").read_text()
    width = int(reg_pkg.split("MIN_ADDR_WIDTH = ")[1].split(";")[0])
    addr_pkg = (tmp_path / "demo_regs_addr_pkg.sv").read_text()
    assert f"localparam int unsigned demo_addr_width = {width};" in addr_pkg
