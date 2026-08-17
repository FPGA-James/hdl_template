# Register Auto-Instantiation & Auto-Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `scripts/gen_regs.py` to generate register files for both VHDL and SystemVerilog, and to auto-wire the generated register↔hardware signals to `<<NAME>>_core`'s ports inside a marker-delimited region of `<<NAME>>_top`, so adding/removing/renaming a register field only requires editing the TOML and re-running `make regs`.

**Architecture:** `scripts/gen_regs.py` gains two new responsibilities per language: (1) generate the register file via `hdl_registers` (VHDL: existing 3 generators; SV: new `SystemVerilogAxiLiteGenerator` backed by PeakRDL-regblock), and (2) parse `<<NAME>>_core`'s port list, match each register field to a core port by naming convention, and rewrite a marker-delimited block in `<<NAME>>_top` with the resulting instantiation. VHDL needs two marker regions (declarative + statement, for an intermediate bridging signal GHDL requires on `BitVector`-typed output fields — verified empirically, see Task 1 note); SV needs one (its struct fields are directly type-compatible with `_core`'s ports, no bridging needed).

**Tech Stack:** Python 3.13, `hdl_registers>=8.0` (already a dependency), new dependency `peakrdl-regblock`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-17-register-autowiring-design.md`

## Global Constraints

- Naming convention is strict, no TOML annotation: core port name = `<register-field leaf name>` + `_i` (register mode `w`/`r_w`) or `_o` (register mode `r`). No fallback matching.
- Every register field must resolve to an existing core port, or generation fails with an error naming the exact field and reason. This is a hard requirement — never silently skip a field.
- Core ports not covered by a register field must resolve to an identically-named port on `<<NAME>>_top` (passthrough, e.g. `clk`, `rst_n`), or generation fails.
- SV's register-file generator only supports register modes `r`/`w`/`r_w` — never `wpulse` or signed integers. `build_field_mappings` must raise a clear error if it encounters an unsupported mode, rather than silently mis-generating.
- The marker-delimited region in `<<NAME>>_top` is the only part of that file `gen_regs.py` may modify. Never touch text outside `BEGIN AUTOGEN.../END AUTOGEN...` pairs.
- New pytest suite lives under `scripts/tests/`, per explicit user instruction — not `tests/` or alongside `submodules/HDLAutoDoc`'s own tests.
- `_core`'s public port list (names, types, directions) must not change for any of the four existing fields (`enable_i`, `increment_i`, `reset_count_i`, `enabled_o`, `pulse_count_o`) — all three existing testbenches (VUnit, cocotb, native) depend on it unchanged.

---

## File Structure

- Modify: `regs/NAME_regs.toml` — rename `command.reset_counter` → `command.reset_count`, mode `wpulse` → `w`.
- Modify: `src/vhdl/NAME_core.vhd` — add rising-edge detector on `reset_count_i`.
- Modify: `src/sv/NAME_core.sv` — same, in SV.
- Modify: `requirements.txt` — add `peakrdl-regblock`.
- Modify: `scripts/gen_regs.py` — the single generation driver; gains port parsing, field-mapping, type-bridging, marker-rewrite, and SV-generation logic.
- Create: `scripts/tests/__init__.py`, `scripts/tests/conftest.py`, `scripts/tests/test_gen_regs.py` — unit tests for all new `gen_regs.py` logic.
- Modify: `src/vhdl/NAME_top.vhd` — restructure existing hand-written wiring into the two marker regions.
- Modify: `src/sv/NAME_top.sv` — replace the `// TODO` stub with a real register-file instantiation, hand-written bus-side wiring, and one marker region for the core port map.
- Modify: `pytest.ini` — add `scripts/tests` to `testpaths` and `scripts` to `pythonpath`.

---

## Task 1: Register map rename + `_core` edge-detector (both languages)

**Files:**
- Modify: `regs/NAME_regs.toml`
- Modify: `src/vhdl/NAME_core.vhd`
- Modify: `src/sv/NAME_core.sv`

**Interfaces:**
- Produces: `reset_count_i` on both cores now expects a **held level** (asserted until software writes it back to `0`), not a hardware-pulsed bit. Internally, both cores derive a one-cycle `reset_count_pulse` via edge detection and use that (not the raw port) to clear the counter. No port name, type, or direction changes — `enable_i`, `increment_i`, `reset_count_i`, `enabled_o`, `pulse_count_o` are unchanged from every downstream consumer's perspective (testbenches, future `_top` wiring).

This was verified empirically against GHDL/VUnit (VHDL) and Verilator (SV) before writing this plan: the unmodified existing `tb/vunit/vhdl/NAME_tb.vhd` and `tb/native/sv/NAME_tb.sv` both pass 4/4 against the edge-detector implementations below, and a held-high-for-3-cycles scenario confirms the counter clears exactly once, not repeatedly.

- [ ] **Step 1: Update the register map**

Edit `regs/NAME_regs.toml`. Change:

```toml
[command]
mode = "wpulse"
description = "One-shot command register. Each field pulses high for one clock cycle on write."

[command.reset_counter]
type = "bit"
description = "Write 1 to reset the pulse count to zero. Automatically clears."
default_value = "0"
```

to:

```toml
[command]
mode = "w"
description = "One-shot command register. Field is a held level; <<NAME>>_core derives a one-cycle internal pulse from it (see reset_count_i in <<NAME>>_core)."

[command.reset_count]
type = "bit"
description = "Write 1 to reset the pulse count to zero. Software must write 0 back afterwards."
default_value = "0"
```

Also update the file's header comment (lines 7-10) — change
`#   command (wpulse) — one-shot commands (self-clearing on read)` to
`#   command (w)      — one-shot commands (core derives a one-cycle pulse internally)`.

- [ ] **Step 2: Update `src/vhdl/NAME_core.vhd`**

Replace the `architecture rtl of <<NAME>>_core is` block (from the `signal count_r` declaration through `end architecture rtl;`) with:

```vhdl
architecture rtl of <<NAME>>_core is

    -- Registered pulse counter. Saturates rather than wrapping.
    signal count_r : unsigned(C_COUNT_W-1 downto 0) := (others => '0');

    -- Registered previous value of reset_count_i, used to derive a
    -- one-cycle internal pulse from what is now a held-level input (the
    -- register file no longer auto-clears it after one cycle).
    signal reset_count_prev : std_logic := '0';

begin

    -- p_count: Clocked pulse counter with saturating addition.
    --
    -- Priority:  reset > reset_count pulse > counting
    -- Saturation prevents wrap-around at full-scale.
    --
    -- .. wavedrom::
    --
    --    { "signal": [
    --      { "name": "clk",          "wave": "P........." },
    --      { "name": "rst_n",        "wave": "0.1......." },
    --      { "name": "enable_i",     "wave": "0..1......" },
    --      { "name": "pulse_i",      "wave": "0...1.1..." },
    --      { "name": "reset_count_i","wave": "0......10." },
    --      { "name": "count_r",      "wave": "=..=.==.=.", "data": ["0","0","1","2","0"] },
    --      { "name": "enabled_o",    "wave": "0..1......" }
    --    ]}
    p_count : process(clk) is
        variable next_count        : unsigned(C_COUNT_W downto 0);
        variable reset_count_pulse : std_logic;
    begin
        if rising_edge(clk) then
            -- reset_count_prev still holds last cycle's value here (signal
            -- updates via <= are not visible until the next delta), so this
            -- detects a genuine 0->1 transition on reset_count_i.
            reset_count_pulse := reset_count_i and not reset_count_prev;
            reset_count_prev  <= reset_count_i;

            if rst_n = '0' then
                count_r   <= (others => '0');
                enabled_o <= '0';
            elsif reset_count_pulse = '1' then
                count_r   <= (others => '0');
                enabled_o <= enable_i;
            elsif enable_i = '1' then
                -- Saturating add: promote to C_COUNT_W+1 bits, cap at all-ones.
                next_count := ('0' & count_r) + to_unsigned(increment_i, C_COUNT_W + 1);
                if next_count(C_COUNT_W) = '1' then
                    count_r <= (others => '1');
                else
                    count_r <= next_count(C_COUNT_W-1 downto 0);
                end if;
                enabled_o <= '1';
            else
                enabled_o <= '0';
            end if;
        end if;
    end process p_count;

    pulse_count_o <= std_logic_vector(count_r);

end architecture rtl;
```

Also update the port comment above (`reset_count_i : in std_logic;`) from
`-- One-cycle reset pulse. Clears count_r to zero on the next clock.` to
`-- Held-level reset request. Core detects the rising edge internally and
-- clears count_r for exactly one cycle.`

- [ ] **Step 3: Update `src/sv/NAME_core.sv`**

Replace the body (from `logic [COUNT_W:0] count_ext;` through the `always_ff` block) with:

```systemverilog
    logic [COUNT_W:0] count_ext;  // one extra bit for saturation detection
    logic [COUNT_W-1:0] count_r;

    // Registered previous value of reset_count_i, used to derive a
    // one-cycle internal pulse from what is now a held-level input (the
    // register file no longer auto-clears it after one cycle).
    logic reset_count_prev;
    logic reset_count_pulse;

    assign reset_count_pulse = reset_count_i & ~reset_count_prev;

    // p_count: Clocked pulse counter with saturating addition.
    //
    // Priority: reset > reset_count pulse > counting
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            count_r          <= '0;
            enabled_o        <= 1'b0;
            reset_count_prev <= 1'b0;
        end else begin
            reset_count_prev <= reset_count_i;
            if (reset_count_pulse) begin
                count_r   <= '0;
                enabled_o <= enable_i;
            end else if (enable_i) begin
                // Promote to COUNT_W+1 bits for saturation check.
                count_ext = {1'b0, count_r} + COUNT_W'(increment_i);
                count_r   <= count_ext[COUNT_W] ? '1 : count_ext[COUNT_W-1:0];
                enabled_o <= 1'b1;
            end else begin
                enabled_o <= 1'b0;
            end
        end
    end
```

Also update the `reset_count_i` port comment from
`// One-cycle reset pulse. Clears count on the next rising edge.` to
`// Held-level reset request. Core detects the rising edge internally and
// clears the count for exactly one cycle.`

- [ ] **Step 4: Verify against the existing testbenches**

These testbenches already exist and are unmodified by this task — they exercise `_core` directly and must still pass, since `_core`'s port-level contract hasn't changed:

```bash
make sim FRAMEWORK=vunit TOPLEVEL_HDL=vhdl
make sim-native TOPLEVEL_HDL=vhdl
make sim-native TOPLEVEL_HDL=sv
```

Expected: all pass (VUnit: 4/4; native: `PASS: all native ... tests completed`, exit 0). Run these against an initialised copy (`make init NAME=<x> TOPLEVEL_HDL=vhdl` / `=sv` in a scratch copy) if not already initialised — `_core.vhd`/`.sv` need real identifiers to compile.

- [ ] **Step 5: Commit**

```bash
git add regs/NAME_regs.toml src/vhdl/NAME_core.vhd src/sv/NAME_core.sv
git commit -m "Rework command.reset_count to plain w mode with core-side edge detection

wpulse mode isn't supported by hdl_registers' SystemVerilog generator.
Switch to plain w (held level) for both languages and move the one-shot
pulse behavior into _core via a rising-edge detector, so the observable
port-boundary timing is unchanged and both languages use one register mode."
```

---

## Task 2: Port-list parsing in `gen_regs.py`

**Files:**
- Modify: `scripts/gen_regs.py`
- Create: `scripts/tests/__init__.py`
- Create: `scripts/tests/conftest.py`
- Create: `scripts/tests/test_gen_regs.py`

**Interfaces:**
- Produces: `Port` dataclass (`name: str`, `direction: str`, `type_str: str`); `parse_vhdl_ports(core_file: Path) -> dict[str, Port]`; `parse_sv_ports(core_file: Path) -> dict[str, Port]`. Both raise `ValueError` with a descriptive message if the file can't be parsed. Direction is `"in"`/`"out"`/`"inout"` for VHDL, `"input"`/`"output"`/`"inout"` for SV (kept as each language's native vocabulary; normalised where compared, in Task 3).

These regexes were tested against the real, current `src/vhdl/NAME_core.vhd` and `src/sv/NAME_core.sv` before writing this plan and correctly extracted all 7 ports of each (including `integer range 1 to 255` and `logic [COUNT_W-1:0]` typed ports).

- [ ] **Step 1: Create the test package files**

```bash
mkdir -p scripts/tests
touch scripts/tests/__init__.py
```

`scripts/tests/conftest.py`:

```python
"""Shared fixtures for scripts/tests/."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def vhdl_core_file(tmp_path: Path) -> Path:
    content = """\
library ieee;
use ieee.std_logic_1164.all;

entity demo_core is
    port (
        clk           : in  std_logic;
        rst_n         : in  std_logic;
        enable_i      : in  std_logic;
        increment_i   : in  integer range 1 to 255;
        reset_count_i : in  std_logic;
        enabled_o     : out std_logic;
        pulse_count_o : out std_logic_vector(15 downto 0)
    );
end entity demo_core;

architecture rtl of demo_core is
begin
end architecture rtl;
"""
    path = tmp_path / "demo_core.vhd"
    path.write_text(content)
    return path


@pytest.fixture
def sv_core_file(tmp_path: Path) -> Path:
    content = """\
module demo_core
#(
    parameter int unsigned COUNT_W = demo_pkg::C_COUNT_W
) (
    input  logic              clk,
    input  logic              rst_n,
    input  logic              enable_i,
    input  int unsigned       increment_i,
    input  logic              reset_count_i,
    output logic              enabled_o,
    output logic [COUNT_W-1:0] pulse_count_o
);
endmodule : demo_core
"""
    path = tmp_path / "demo_core.sv"
    path.write_text(content)
    return path
```

- [ ] **Step 2: Write the failing tests**

`scripts/tests/test_gen_regs.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
.venv/bin/python3 -m pytest scripts/tests/test_gen_regs.py -v
```

Expected: `ModuleNotFoundError` or `AttributeError` — `gen_regs.Port`/`parse_vhdl_ports`/`parse_sv_ports` don't exist yet.

- [ ] **Step 4: Add the parsing code to `scripts/gen_regs.py`**

Add near the top of the file, after the existing imports (keep the existing `from pathlib import Path` and generator imports as-is):

```python
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Port:
    """A single entity/module port, as parsed from RTL source text."""

    name: str
    direction: str  # VHDL: "in"/"out"/"inout"   SV: "input"/"output"/"inout"
    type_str: str


def parse_vhdl_ports(core_file: Path) -> dict[str, Port]:
    """Parse the entity port clause of a VHDL core file."""
    text = core_file.read_text()
    text = re.sub(r"--.*", "", text)
    match = re.search(
        r"\bport\s*\((.*?)\)\s*;\s*end\s+entity", text, re.IGNORECASE | re.DOTALL
    )
    if not match:
        raise ValueError(f"No entity port clause found in {core_file}")

    ports: dict[str, Port] = {}
    for entry in re.split(r";", match.group(1)):
        entry = entry.strip()
        if not entry:
            continue
        port_match = re.match(r"(\w+)\s*:\s*(in|out|inout)\s+(.+)", entry, re.IGNORECASE)
        if not port_match:
            raise ValueError(f"Could not parse port declaration: {entry!r} in {core_file}")
        name, direction, type_str = port_match.groups()
        ports[name] = Port(name=name, direction=direction.lower(), type_str=type_str.strip())
    return ports


def parse_sv_ports(core_file: Path) -> dict[str, Port]:
    """Parse the module port list of a SystemVerilog core file."""
    text = core_file.read_text()
    text = re.sub(r"//.*", "", text)
    match = re.search(r"\bmodule\s+\S+.*?\)\s*;", text, re.DOTALL)
    if not match:
        raise ValueError(f"No module port clause found in {core_file}")
    header = match.group(0)

    # The port list is the LAST top-level (...) group before the final ';'
    # (the module may also have a preceding #( ... ) parameter block).
    close_idx = header.rfind(")")
    depth = 0
    open_idx = None
    for i in range(close_idx, -1, -1):
        if header[i] == ")":
            depth += 1
        elif header[i] == "(":
            depth -= 1
            if depth == 0:
                open_idx = i
                break
    if open_idx is None:
        raise ValueError(f"Unbalanced parentheses in module header of {core_file}")
    body = header[open_idx + 1 : close_idx]

    ports: dict[str, Port] = {}
    for entry in re.split(r",(?![^\[]*\])", body):
        entry = entry.strip()
        if not entry:
            continue
        port_match = re.match(r"(input|output|inout)\s+(.+?)\s+(\w+)$", entry)
        if not port_match:
            raise ValueError(f"Could not parse port declaration: {entry!r} in {core_file}")
        direction, type_str, name = port_match.groups()
        ports[name] = Port(name=name, direction=direction, type_str=type_str.strip())
    return ports
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/python3 -m pytest scripts/tests/test_gen_regs.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/gen_regs.py scripts/tests/
git commit -m "Add VHDL/SV core port-list parsing to gen_regs.py"
```

---

## Task 3: Field-to-port mapping & type bridging

**Files:**
- Modify: `scripts/gen_regs.py`
- Modify: `scripts/tests/test_gen_regs.py`
- Modify: `scripts/tests/conftest.py`

**Interfaces:**
- Consumes: `Port` and `parse_vhdl_ports`/`parse_sv_ports` from Task 2.
- Produces: `FieldMapping` dataclass (`register_name: str`, `field_name: str`, `field_type: type`, `width: int`, `direction: str` — `"down"`/`"up"`, `port_name: str`, `needs_cast: bool`); `build_field_mappings(register_list) -> list[FieldMapping]`; `resolve_port_mappings(mappings: list[FieldMapping], core_ports: dict[str, Port]) -> None` (raises `ValueError` listing every problem found, not just the first); `build_passthrough_mappings(core_ports: dict[str, Port], field_mappings: list[FieldMapping], top_ports: dict[str, Port]) -> dict[str, str]` (raises `ValueError` for any core port with neither a field mapping nor a same-named top port).

`hdl_registers` API used here (verified against `hdl_registers==8.1.0` against this project's actual `regs/NAME_regs.toml`, post-Task-1 rename): `RegisterList.register_objects` — list of `Register`; `Register.name: str`, `Register.mode.shorthand: str` (one of `"r"`, `"w"`, `"r_w"` for anything this project uses), `Register.fields` — list of field objects; field `.name: str`, `.width: int`; field type via `type(field)`, one of `hdl_registers.field.bit.Bit`, `hdl_registers.field.bit_vector.BitVector`, `hdl_registers.field.integer.Integer`.

- [ ] **Step 1: Add fixtures for a register list**

Add to `scripts/tests/conftest.py`:

```python
@pytest.fixture
def demo_toml_file(tmp_path: Path) -> Path:
    content = """\
[conf]
mode = "r_w"
[conf.enable]
type = "bit"
default_value = "0"
[conf.increment]
type = "integer"
min_value = 1
max_value = 255
default_value = 1

[command]
mode = "w"
[command.reset_count]
type = "bit"
default_value = "0"

[status]
mode = "r"
[status.enabled]
type = "bit"
[status.pulse_count]
type = "bit_vector"
width = 16
"""
    path = tmp_path / "demo_regs.toml"
    path.write_text(content)
    return path


@pytest.fixture
def demo_register_list(demo_toml_file):
    from hdl_registers.parser.toml import from_toml

    return from_toml(name="demo", toml_file=demo_toml_file)
```

- [ ] **Step 2: Write the failing tests**

Add to `scripts/tests/test_gen_regs.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
.venv/bin/python3 -m pytest scripts/tests/test_gen_regs.py -v -k "field_mappings or resolve_port or passthrough"
```

Expected: `AttributeError` — none of `build_field_mappings`/`resolve_port_mappings`/`build_passthrough_mappings`/`FieldMapping` exist yet.

- [ ] **Step 4: Add the mapping code to `scripts/gen_regs.py`**

Add after the `parse_sv_ports` function:

```python
from hdl_registers.field.bit_vector import BitVector


@dataclass
class FieldMapping:
    """A single register field, resolved to the core port it drives/receives."""

    register_name: str
    field_name: str
    field_type: type
    width: int
    direction: str  # "down" (host writes, core input) or "up" (host reads, core output)
    port_name: str
    needs_cast: bool  # VHDL only: True for BitVector fields (record type is `unsigned`)


def build_field_mappings(register_list) -> list[FieldMapping]:
    """Walk the register list and compute each field's expected core port name,
    direction, and whether a VHDL type cast is needed to reach that port."""
    mappings: list[FieldMapping] = []
    for register in register_list.register_objects:
        mode = register.mode.shorthand
        if mode in ("w", "r_w"):
            direction, suffix = "down", "_i"
        elif mode == "r":
            direction, suffix = "up", "_o"
        else:
            raise ValueError(
                f"Register '{register.name}' uses mode '{mode}', which the "
                "SystemVerilog register-file generator does not support "
                "(only r, w, r_w). Use a supported mode — see Task 1 of "
                "docs/superpowers/plans/2026-08-17-register-autowiring.md "
                "for the pattern used to replicate wpulse-style behavior "
                "with a plain 'w' field plus a core-side edge detector."
            )
        for field in register.fields:
            mappings.append(
                FieldMapping(
                    register_name=register.name,
                    field_name=field.name,
                    field_type=type(field),
                    width=field.width,
                    direction=direction,
                    port_name=f"{field.name}{suffix}",
                    needs_cast=isinstance(field, BitVector),
                )
            )
    return mappings


def resolve_port_mappings(mappings: list[FieldMapping], core_ports: dict[str, Port]) -> None:
    """Verify every field maps to an existing core port with the matching direction.
    Raises ValueError listing every problem found, not just the first."""
    errors = []
    for mapping in mappings:
        port = core_ports.get(mapping.port_name)
        if port is None:
            errors.append(
                f"register field '{mapping.register_name}.{mapping.field_name}' "
                f"expects a core port named '{mapping.port_name}', but no such "
                "port exists"
            )
            continue
        expected_direction = "in" if mapping.direction == "down" else "out"
        actual_direction = "in" if port.direction in ("in", "input") else "out"
        if actual_direction != expected_direction:
            errors.append(
                f"core port '{mapping.port_name}' has direction "
                f"'{port.direction}', but register field "
                f"'{mapping.register_name}.{mapping.field_name}' needs "
                f"direction '{expected_direction}'"
            )
    if errors:
        raise ValueError(
            "Register field <-> core port mismatch:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


def build_passthrough_mappings(
    core_ports: dict[str, Port],
    field_mappings: list[FieldMapping],
    top_ports: dict[str, Port],
) -> dict[str, str]:
    """For core ports not covered by any register field (e.g. clk, rst_n),
    connect them to an identically-named port on <<NAME>>_top."""
    covered = {m.port_name for m in field_mappings}
    passthrough: dict[str, str] = {}
    errors = []
    for name in core_ports:
        if name in covered:
            continue
        if name not in top_ports:
            errors.append(
                f"core port '{name}' is not a register-derived port and has "
                "no matching port on <<NAME>>_top to pass through"
            )
            continue
        passthrough[name] = name
    if errors:
        raise ValueError(
            "Unmapped core port(s):\n" + "\n".join(f"  - {e}" for e in errors)
        )
    return passthrough
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/python3 -m pytest scripts/tests/test_gen_regs.py -v
```

Expected: all tests PASS (6 from Task 2 + 7 new = 13).

- [ ] **Step 6: Commit**

```bash
git add scripts/gen_regs.py scripts/tests/
git commit -m "Add register field to core port mapping and validation to gen_regs.py"
```

---

## Task 4: Marker-region rewrite and wiring-block rendering

**Files:**
- Modify: `scripts/gen_regs.py`
- Modify: `scripts/tests/test_gen_regs.py`

**Interfaces:**
- Consumes: `FieldMapping` from Task 3.
- Produces: `rewrite_marker_region(file_path: Path, begin_marker: str, end_marker: str, new_content: str) -> None` (raises `ValueError` if the marker pair isn't found); `render_vhdl_signals_block(field_mappings: list[FieldMapping]) -> str`; `render_vhdl_wiring_block(name: str, field_mappings: list[FieldMapping], passthrough: dict[str, str]) -> str`; `render_sv_wiring_block(name: str, field_mappings: list[FieldMapping], passthrough: dict[str, str]) -> str`.

Marker text (exact, including comment prefix) is fixed by this task:
VHDL: `-- BEGIN AUTOGEN REGISTER SIGNALS` / `-- END AUTOGEN REGISTER SIGNALS` (declarative region — bridging signals only) and `-- BEGIN AUTOGEN REGISTERS` / `-- END AUTOGEN REGISTERS` (statement region — bridging assignments + `u_core` instantiation). SV: `// BEGIN AUTOGEN REGISTERS` / `// END AUTOGEN REGISTERS` only (no bridging signals needed — SV struct fields are already `logic`/`logic[N:0]`, directly compatible with `_core`'s ports).

The VHDL split into two regions exists because GHDL rejects inline output-port type conversion (`o => std_logic_vector(u)` and `o => unsigned(u)` both fail — verified empirically with a minimal GHDL test case before writing this plan); a `BitVector` "up" field needs an intermediate `std_logic_vector` signal declared before `begin` and a concurrent `<=` assignment after it.

- [ ] **Step 1: Write the failing tests**

Add to `scripts/tests/test_gen_regs.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python3 -m pytest scripts/tests/test_gen_regs.py -v -k "marker_region or render_"
```

Expected: `AttributeError` — none of these functions exist yet.

- [ ] **Step 3: Add the rendering and rewrite code to `scripts/gen_regs.py`**

```python
def rewrite_marker_region(
    file_path: Path, begin_marker: str, end_marker: str, new_content: str
) -> None:
    """Replace the text strictly between a BEGIN/END marker comment pair.
    The markers themselves are preserved and left in place."""
    text = file_path.read_text()
    pattern = re.compile(re.escape(begin_marker) + r".*?" + re.escape(end_marker), re.DOTALL)
    if not pattern.search(text):
        raise ValueError(
            f"Could not find marker region '{begin_marker}' ... "
            f"'{end_marker}' in {file_path}. Add the marker comment pair "
            "before running `make regs`."
        )
    replacement = f"{begin_marker}\n{new_content}\n    {end_marker}"
    new_text = pattern.sub(lambda _match: replacement, text, count=1)
    file_path.write_text(new_text)


def render_vhdl_signals_block(field_mappings: list[FieldMapping]) -> str:
    """Bridging signal declarations for 'up' BitVector fields."""
    lines = [
        f"    signal {m.field_name} : std_logic_vector({m.width} - 1 downto 0);"
        for m in field_mappings
        if m.direction == "up" and m.needs_cast
    ]
    return "\n".join(lines)


def render_vhdl_wiring_block(
    name: str, field_mappings: list[FieldMapping], passthrough: dict[str, str]
) -> str:
    # 'up' (output-port) BitVector fields need an intermediate signal --
    # GHDL rejects both std_logic_vector(...) and unsigned(...) as inline
    # output-port conversions (verified empirically). 'down' (input-port)
    # BitVector fields don't have this restriction: VHDL allows an
    # arbitrary expression as an input-port actual, so std_logic_vector(...)
    # works inline there (also verified empirically) -- no bridging signal
    # needed for that direction.
    bridge_assignments = [
        f"    regs_up.{m.register_name}.{m.field_name} <= unsigned({m.field_name});"
        for m in field_mappings
        if m.direction == "up" and m.needs_cast
    ]

    port_lines = [f"            {formal} => {actual}" for formal, actual in passthrough.items()]
    for m in field_mappings:
        record = "regs_down" if m.direction == "down" else "regs_up"
        field_ref = f"{record}.{m.register_name}.{m.field_name}"
        if m.direction == "up" and m.needs_cast:
            actual = m.field_name  # connects to the bridging signal instead
        elif m.direction == "down" and m.needs_cast:
            actual = f"std_logic_vector({field_ref})"  # inline cast, input port
        else:
            actual = field_ref
        port_lines.append(f"            {m.port_name} => {actual}")

    instance = [
        f"    u_core : entity work.{name}_core",
        "        port map (",
        ",\n".join(port_lines),
        "        );",
    ]

    return "\n".join(bridge_assignments + ([""] if bridge_assignments else []) + instance)


def render_sv_wiring_block(
    name: str, field_mappings: list[FieldMapping], passthrough: dict[str, str]
) -> str:
    port_lines = [f"        .{formal}({actual})" for formal, actual in passthrough.items()]
    for m in field_mappings:
        if m.direction == "down":
            actual = f"hwif_out.{m.register_name}.{m.field_name}.value"
        else:
            actual = f"hwif_in.{m.register_name}.{m.field_name}.next"
        port_lines.append(f"        .{m.port_name}({actual})")

    return "\n".join(
        [
            f"    {name}_core u_core (",
            ",\n".join(port_lines),
            "    );",
        ]
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python3 -m pytest scripts/tests/test_gen_regs.py -v
```

Expected: all tests PASS (13 from Tasks 2-3 + 8 new = 21).

- [ ] **Step 5: Commit**

```bash
git add scripts/gen_regs.py scripts/tests/
git commit -m "Add marker-region rewrite and VHDL/SV wiring-block rendering to gen_regs.py"
```

---

## Task 5: SystemVerilog register-file generation

**Files:**
- Modify: `scripts/gen_regs.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `generate_sv(register_list, output_folder: Path) -> None` — mirrors the existing VHDL generation calls, writes `<name>_register_file_axi_lite.sv` and `<name>_register_file_axi_lite_pkg.sv` into `output_folder`.

`SystemVerilogAxiLiteGenerator(...).create(flatten_axi_lite=True)` was run against this project's real (post-Task-1) register map before writing this plan — confirmed it produces discrete `s_axil_*` signals (not a bundled `interface`) and a module named `<name>_register_file_axi_lite`, matching the VHDL entity's naming convention.

- [ ] **Step 1: Add the new dependency**

Add to `requirements.txt`, near the existing `hdl-registers` line:

```
# SystemVerilog register-file generation (hdl_registers' SV generator delegates to this)
peakrdl-regblock>=1.0
```

- [ ] **Step 2: Add the SV generation function to `scripts/gen_regs.py`**

Add near the existing VHDL generator imports:

```python
from hdl_registers.generator.systemverilog.axi_lite.register_file import (
    SystemVerilogAxiLiteGenerator,
)
```

Add a new function, mirroring the shape of the existing VHDL generation code:

```python
def generate_sv(register_list, output_folder: Path) -> None:
    """Generate the SystemVerilog AXI-Lite register file and its types package.
    Uses flatten_axi_lite=True so the bus side is discrete signals (s_axil_*),
    not a bundled SV interface -- keeps the bus-side wiring convention close
    to this project's existing hand-written SV top and avoids depending on
    an external interface definition.
    """
    SystemVerilogAxiLiteGenerator(register_list=register_list, output_folder=output_folder).create(
        flatten_axi_lite=True
    )
```

- [ ] **Step 3: Verify manually against the real register map**

There's no toolchain-free way to unit test this (it shells out to PeakRDL-regblock's exporter and writes real files) — verify directly:

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python3 -c "
from pathlib import Path
from hdl_registers.parser.toml import from_toml
import sys; sys.path.insert(0, 'scripts')
from gen_regs import generate_sv

rl = from_toml(name='demo', toml_file=Path('regs/NAME_regs.toml'))
generate_sv(rl, Path('/tmp/gen_sv_check'))
"
ls /tmp/gen_sv_check
grep -c "module demo_register_file_axi_lite" /tmp/gen_sv_check/demo_register_file_axi_lite.sv
rm -rf /tmp/gen_sv_check
```

Expected: two files listed (`demo_register_file_axi_lite.sv`, `demo_register_file_axi_lite_pkg.sv`); grep finds exactly `1`. (Note: `regs/NAME_regs.toml` still has literal `<<NAME>>` in some fields at this point in the plan — `from_toml(name="demo", ...)` overrides the register-list name explicitly, which is why this works pre-`make init`; the file itself doesn't need `<<NAME>>` substituted for this check.)

- [ ] **Step 4: Commit**

```bash
git add scripts/gen_regs.py requirements.txt
git commit -m "Add SystemVerilog register-file generation via PeakRDL-regblock"
```

---

## Task 6: Wire the full driver together

**Files:**
- Modify: `scripts/gen_regs.py`

**Interfaces:**
- Consumes: everything from Tasks 2-5.
- Produces: `detect_language(repo_root: Path) -> str` (returns `"vhdl"` or `"sv"` based on which exists on disk); modified `generate_from_toml(toml_path: Path) -> None` — now generates the register file for the detected language, then calls a new `autowire_top(name: str, language: str, register_list, repo_root: Path) -> None` which performs the parse/map/render/rewrite sequence from Tasks 2-4.

This task has no new unit-testable pure logic of its own (it's wiring, not new decision-making) — verification is the `make regs` run at the end.

- [ ] **Step 1: Read the current `generate_from_toml` and `main` functions**

Confirm their current shape before editing (they were last touched in this session's earlier "fix the `_regs_regs` double-suffix bug" work — `name = toml_path.stem.removesuffix("_regs")`):

```bash
sed -n '1,90p' scripts/gen_regs.py
```

- [ ] **Step 2: Add `detect_language` and `autowire_top`, and update `generate_from_toml`**

Add `detect_language`:

```python
def detect_language(repo_root: Path) -> str:
    """Return "vhdl" or "sv" based on which core source file exists under src/.
    Mirrors how the rest of the Makefile infers language post-`make init`."""
    src_dir = repo_root / "src"
    if list(src_dir.glob("*_core.vhd")):
        return "vhdl"
    if list(src_dir.glob("*_core.sv")):
        return "sv"
    raise ValueError(
        f"No *_core.vhd or *_core.sv found under {src_dir} -- run `make init` first."
    )
```

Add `autowire_top`:

```python
def autowire_top(name: str, language: str, register_list, repo_root: Path) -> None:
    """Regenerate the marker-delimited register-wiring region(s) in <name>_top."""
    src_dir = repo_root / "src"
    ext = "vhd" if language == "vhdl" else "sv"
    core_file = src_dir / f"{name}_core.{ext}"
    top_file = src_dir / f"{name}_top.{ext}"

    parse_ports = parse_vhdl_ports if language == "vhdl" else parse_sv_ports
    core_ports = parse_ports(core_file)
    top_ports = parse_ports(top_file)

    field_mappings = build_field_mappings(register_list)
    resolve_port_mappings(field_mappings, core_ports)
    passthrough = build_passthrough_mappings(core_ports, field_mappings, top_ports)

    if language == "vhdl":
        rewrite_marker_region(
            top_file,
            "-- BEGIN AUTOGEN REGISTER SIGNALS",
            "-- END AUTOGEN REGISTER SIGNALS",
            render_vhdl_signals_block(field_mappings),
        )
        rewrite_marker_region(
            top_file,
            "-- BEGIN AUTOGEN REGISTERS",
            "-- END AUTOGEN REGISTERS",
            render_vhdl_wiring_block(name, field_mappings, passthrough),
        )
    else:
        rewrite_marker_region(
            top_file,
            "// BEGIN AUTOGEN REGISTERS",
            "// END AUTOGEN REGISTERS",
            render_sv_wiring_block(name, field_mappings, passthrough),
        )
    print(f"  Auto-wired {top_file.relative_to(repo_root)}")
```

Now update `generate_from_toml` — find the existing function (it currently always calls the three VHDL generators unconditionally) and replace its body to branch on `detect_language`:

```python
def generate_from_toml(toml_path: Path) -> None:
    """Generate all outputs for a single TOML register definition file."""
    name = toml_path.stem.removesuffix("_regs")
    print(f"  Generating registers for: {name}")

    register_list = from_toml(name=name, toml_file=toml_path)

    language = detect_language(REPO_ROOT)
    if language == "vhdl":
        VhdlRegisterPackageGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
        VhdlRecordPackageGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
        VhdlAxiLiteWrapperGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
    else:
        generate_sv(register_list, GEN_SV)

    CHeaderGenerator(register_list=register_list, output_folder=GEN_C).create()
    HtmlPageGenerator(register_list=register_list, output_folder=GEN_HTML).create()

    autowire_top(name=name, language=language, register_list=register_list, repo_root=REPO_ROOT)
```

Add the `GEN_SV` output-folder constant next to the existing `GEN_VHDL`/`GEN_C`/`GEN_HTML` constants near the top of the file:

```python
GEN_SV = REPO_ROOT / "out" / "regs" / "sv"
```

And in `main()`, add `GEN_SV` to the directories created up front (find the existing `for d in (GEN_VHDL, GEN_C, GEN_HTML): d.mkdir(...)` loop and add `GEN_SV` to that tuple).

- [ ] **Step 3: Run the full pytest suite to confirm nothing broke**

```bash
.venv/bin/python3 -m pytest scripts/tests/ -v
```

Expected: all 21 tests still PASS (this task added no new pure-logic functions, so no new tests — this is a regression check).

- [ ] **Step 4: Commit**

```bash
git add scripts/gen_regs.py
git commit -m "Wire gen_regs.py's driver to detect language and auto-wire _top after generation"
```

---

## Task 7: Scaffold the marker regions in `NAME_top.vhd`/`.sv`

**Files:**
- Modify: `src/vhdl/NAME_top.vhd`
- Modify: `src/sv/NAME_top.sv`
- Modify: `pytest.ini`

**Interfaces:**
- Produces: both top files now contain the exact marker comment pairs `gen_regs.py` (Task 6) looks for, with content matching what the generator will produce on the next `make regs` run (so this task's diff introduces no behavior change by itself — it's purely restructuring existing hand-written text into the marker format, for VHDL; for SV it's the first real register integration, replacing the `// TODO` stub).

- [ ] **Step 1: Update `pytest.ini`**

Add `scripts/tests` to `testpaths` and `scripts` to `pythonpath`:

```ini
[pytest]
# Test discovery roots
testpaths =
    submodules/HDLAutoDoc/src/scripts/hdl_autodoc/tests
    tb/cocotb
    scripts/tests

# Add source paths so imports resolve without conftest.py hacks
pythonpath =
    submodules/HDLAutoDoc/src/scripts/hdl_autodoc
    tb/cocotb
    scripts
```

- [ ] **Step 2: Restructure `src/vhdl/NAME_top.vhd` into the marker format**

Replace the `architecture rtl of <<NAME>>_top is` block with:

```vhdl
architecture rtl of <<NAME>>_top is

    -- Register record signals connecting the generated register file to the core.
    -- regs_down: register values written by the host (conf, command registers).
    -- regs_up:   status values driven by the core (status register).
    signal regs_down : <<NAME>>_regs_down_t := <<NAME>>_regs_down_init;
    signal regs_up   : <<NAME>>_regs_up_t   := <<NAME>>_regs_up_init;

    -- Bridging signals for register fields whose VHDL record type (unsigned)
    -- doesn't directly match a plain std_logic_vector core port -- content
    -- generated by `make regs`, do not hand-edit.
    -- BEGIN AUTOGEN REGISTER SIGNALS
    signal pulse_count : std_logic_vector(16 - 1 downto 0);
    -- END AUTOGEN REGISTER SIGNALS

begin

    -- u_regs: Generated AXI4-Lite register file.
    --
    -- Entity and packages are produced by `make regs` via hdl_registers.
    -- Source: out/regs/vhdl/<<NAME>>_register_file_axi_lite.vhd
    u_regs : entity work.<<NAME>>_register_file_axi_lite
        port map (
            clk          => clk,
            reset        => not rst_n,      -- generated entity uses active-high reset
            axi_lite_m2s => s_axi_m2s,
            axi_lite_s2m => s_axi_s2m,
            regs_up      => regs_up,
            regs_down    => regs_down
        );

    -- u_core: Counter core logic, and its register wiring.
    --
    -- Content between the markers is generated by `make regs` -- do not
    -- hand-edit; edit regs/<<NAME>>_regs.toml instead. Everything else in
    -- this file (ports, u_regs above) is yours to edit freely.
    -- BEGIN AUTOGEN REGISTERS
    regs_up.status.pulse_count <= unsigned(pulse_count);

    u_core : entity work.<<NAME>>_core
        port map (
            clk => clk,
            rst_n => rst_n,
            enable_i => regs_down.conf.enable,
            increment_i => regs_down.conf.increment,
            reset_count_i => regs_down.command.reset_count,
            enabled_o => regs_up.status.enabled,
            pulse_count_o => pulse_count
        );
    -- END AUTOGEN REGISTERS

end architecture rtl;
```

(The exact width `16` and field names here match today's register map — this is the content `make regs` will regenerate on the next run anyway, so the starting values only need to be *a* valid instance of the marker format, not hand-perfected.)

- [ ] **Step 3: Restructure `src/sv/NAME_top.sv` into the marker format**

Replace the module body from `// ── Decoded register signals ──` through the end (before `endmodule`) with a real register-file instantiation. This is new integration — the current file is a stub with tied-off AXI outputs:

```systemverilog
    // ── Register file signals ────────────────────────────────────────────────
    // hwif_out: register values written by the host (conf, command registers).
    // hwif_in:  status values driven by the core (status register).
    <<NAME>>_register_file_axi_lite_pkg::<<NAME>>__out_t hwif_out;
    <<NAME>>_register_file_axi_lite_pkg::<<NAME>>__in_t  hwif_in;

    // ── u_regs: Generated AXI4-Lite register file ───────────────────────────
    //
    // Module and package are produced by `make regs` via hdl_registers +
    // PeakRDL-regblock. Source: out/regs/sv/<<NAME>>_register_file_axi_lite.sv
    //
    // Bus-side connection: this project's s_axi_* ports don't match the
    // generated module's flattened s_axil_* names 1:1 (it also has
    // AWPROT/ARPROT, which this port list doesn't expose) -- wired by hand
    // below, not by the generator.
    <<NAME>>_register_file_axi_lite u_regs (
        .clk           (clk),
        .rst           (~rst_n),          // generated module uses active-high reset
        .s_axil_awready(s_axi_awready),
        .s_axil_awvalid(s_axi_awvalid),
        .s_axil_awaddr (s_axi_awaddr),
        .s_axil_awprot (3'b000),
        .s_axil_wready (s_axi_wready),
        .s_axil_wvalid (s_axi_wvalid),
        .s_axil_wdata  (s_axi_wdata),
        .s_axil_wstrb  (s_axi_wstrb),
        .s_axil_bready (s_axi_bready),
        .s_axil_bvalid (s_axi_bvalid),
        .s_axil_bresp  (s_axi_bresp),
        .s_axil_arready(s_axi_arready),
        .s_axil_arvalid(s_axi_arvalid),
        .s_axil_araddr (s_axi_araddr),
        .s_axil_arprot (3'b000),
        .s_axil_rready (s_axi_rready),
        .s_axil_rvalid (s_axi_rvalid),
        .s_axil_rdata  (s_axi_rdata),
        .s_axil_rresp  (s_axi_rresp),
        .hwif_in       (hwif_in),
        .hwif_out      (hwif_out)
    );

    // ── u_core: Counter core logic, and its register wiring ─────────────────
    //
    // Content between the markers is generated by `make regs` -- do not
    // hand-edit; edit regs/<<NAME>>_regs.toml instead. Everything else in
    // this file (ports, u_regs above) is yours to edit freely.
    // BEGIN AUTOGEN REGISTERS
    <<NAME>>_core u_core (
        .clk(clk),
        .rst_n(rst_n),
        .enable_i(hwif_out.conf.enable.value),
        .increment_i(hwif_out.conf.increment.value),
        .reset_count_i(hwif_out.command.reset_count.value),
        .enabled_o(hwif_in.status.enabled.next),
        .pulse_count_o(hwif_in.status.pulse_count.next)
    );
    // END AUTOGEN REGISTERS
```

Delete the now-obsolete `assign enable_r = ...` / `assign s_axi_* = ...` tie-off block and the `enable_r`/`increment_r`/`reset_counter_r`/`enabled_s`/`pulse_count_s` signal declarations above it — they're replaced by the direct `hwif_out`/`hwif_in` connections. Also remove the module-header comment block's now-inaccurate "Option A / Option B" TODO text (lines 1-10), replacing it with a short accurate description matching the VHDL top's header comment style.

- [ ] **Step 4: Sanity-check the marker format with a real `make regs` run**

In an initialised scratch copy (both languages), confirm the generator actually finds and rewrites the markers without error:

```bash
# (in a scratch copy, after make init NAME=demoproj TOPLEVEL_HDL=vhdl && make venv && pip install -r requirements.txt)
make regs
git diff src/demoproj_top.vhd   # expect: only the marked regions changed, formatting normalised
```

```bash
# (in a separate scratch copy, after make init NAME=demoproj TOPLEVEL_HDL=sv && make venv && pip install -r requirements.txt)
make regs
git diff src/demoproj_top.sv   # expect: only the AUTOGEN REGISTERS region changed
```

Expected: `make regs` completes without a `ValueError` from `resolve_port_mappings`/`build_passthrough_mappings`/`rewrite_marker_region`. If it raises, the error message names the exact field/port at fault — fix the mismatch in whichever file is wrong (most likely a typo in the marker text or a leftover port-name inconsistency) and re-run.

- [ ] **Step 5: Commit**

```bash
git add src/vhdl/NAME_top.vhd src/sv/NAME_top.sv pytest.ini
git commit -m "Scaffold AUTOGEN marker regions in NAME_top.vhd/.sv; give SV top real register integration"
```

---

## Task 8: Full end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full pytest suite**

```bash
.venv/bin/python3 -m pytest scripts/tests/ -v
```

Expected: all 21 tests PASS.

- [ ] **Step 2: Run the smoke test for both languages**

```bash
scripts/smoke_test.sh
```

Expected: `init`, `venv`, `deps`, `regs`, `lsp`, `lint-vhdl`/`lint-sv`, `sim-native`, `sim-cocotb-*`, `sim-vunit` (VHDL only), `synth`, `html`, `coverage`, `clean-generated` all PASS for both `vhdl` and `sv` rows in the summary table. (`sim-cocotb-*` and `html` may show pre-existing local-machine failures unrelated to this feature — see `CLAUDE.md`'s "Known macOS gap" notes for `libintl.8.dylib`/`libxcb.dylib` — those are environment issues, not regressions from this work. Everything else must be green.)

- [ ] **Step 3: Manually inspect one generated `_top` file for correctness**

```bash
KEEP=1 scripts/smoke_test.sh vhdl
# find the kept temp dir path printed at the end, then:
cat "$KEPT_DIR/vhdl/src/"*_top.vhd
```

Confirm: the `u_core` port map inside the markers connects all five register-derived ports plus `clk`/`rst_n`, matches the naming convention exactly, and the file outside the markers (the `u_regs` instantiation, entity port list) is untouched from what Task 7 wrote.

- [ ] **Step 4: Confirm `command.reset_count`'s new behavior end-to-end**

The `test_reset_count` case in `tb/vunit/vhdl/NAME_tb.vhd` and the equivalent section in the native/cocotb testbenches already exercise this — their pass/fail in Step 2's smoke test *is* this confirmation. No separate step needed; this note exists so a reviewer knows where to look if Step 2 fails specifically on a reset-related check.

- [ ] **Step 5: Final commit (if Steps 1-3 required any fixes)**

```bash
git add -A
git commit -m "Fix issues found during end-to-end register auto-wiring verification"
```

If no fixes were needed, skip this step — Task 7's commit is the last one.
