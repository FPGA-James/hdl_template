# Testbenches Target `_top` via AXI-Lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every testbench in this template (VUnit, cocotb, native-vhdl, native-sv, and a new C++ path) instantiates `<name>_top` and drives it over AXI-Lite, instead of instantiating `<name>_core` and poking its plain ports directly — exercising the register auto-wiring feature end-to-end in every simulation path.

**Architecture:** Each framework gets its own AXI-Lite driver (table below), each testbench re-expresses the same five existing scenarios (`count_up`, `increment_step` [cocotb only], `saturation`, `reset_count`, `disable`) as register reads/writes instead of direct port stimulus, and two small additions land in `scripts/gen_regs.py` (a VHDL simulation read/write package, and an SV register-address package) to give tests a way to address registers without hand-typing offsets.

**Tech Stack:** VHDL (GHDL, NVC), SystemVerilog (Verilator, Icarus), Python (cocotb, VUnit, hdl_registers), C++ (Verilator `--cc --exe --build`), OSVVM (via `nvc --install osvvm`), `cocotbext-axi` (pip).

**Spec:** `docs/superpowers/specs/2026-08-21-testbenches-target-top-design.md`

## Global Constraints

- All five existing test scenarios (`count_up`, `increment_step` [cocotb only], `saturation`, `reset_count`, `disable`/`test_disable_holds_count`) must be preserved in every testbench — same pass/fail behavior, re-expressed as register operations.
- `_core`'s RTL and port list must not change.
- Every testbench instantiating `_top` must tie `pulse_i` to `'0'`/`1'b0` — it's an unconnected input port, not exercised by any scenario, but VHDL requires driving an `in` port and leaving it dangling in SV is sloppy.
- `command.reset_count` is a plain `w`-mode field: writing 1 then writing 0 back (matching the TOML's own documented contract) produces the one-cycle internal pulse `_core` derives from the rising edge — every testbench's `reset_count` scenario does two writes, not one.
- `cocotbext-axi`'s `AxiLiteMaster` must be constructed with `reset_active_level=False` (this project's reset is `rst_n`, active-low; the library defaults to active-high).
- OSVVM's `Axi4LiteManager` port `nReset` is unused internally (verified by reading the full entity body) — tie it to `rst_n` for documentation purposes only; do not expect it to affect timing, and do not treat an apparently-ignored reset as a wiring bug.
- `native-sv` and `cpp` use hand-rolled AXI-Lite drivers by design (verified: no viable off-the-shelf non-UVM, Verilator-compatible SV BFM exists — `pulp-platform/axi`'s `axi_test.sv` was spiked directly and fails under Verilator with `%Error-UNSUPPORTED: virtual interface never assigned any actual interface` on its unused full-AXI classes). Do not attempt to reintroduce a third-party SV BFM dependency as part of this plan.
- Register byte address = `4 * <index of register in the register list>`, 0-based. VHDL sources this via the new `VhdlSimulationReadWritePackageGenerator`-generated procedures (address computed internally) or, where raw addresses are needed (native-vhdl), the existing `<name>_regs_pkg.vhd`'s lowercase register-index constants (`<name>_conf`, `<name>_command`, `<name>_status`). SV sources this via the new `<name>_regs_addr_pkg.sv` (this plan adds it, Task 2) — **deliberately lowercase-named** (`<name>_conf_addr`, not `<NAME>_CONF_ADDR`), because `<<NAME>>` template substitution is a literal, case-preserving text replacement: a template file can write `<<NAME>>_conf_addr` and have it correctly become `myproject_conf_addr` post-init, but it cannot produce an uppercased `MYPROJECT_CONF_ADDR` from any `<<NAME>>`-shaped token. C++ sources this via the already-generated `out/regs/c/<name>_regs.h`, but likewise never by naming its uppercase `#define` macros directly — use `offsetof(<<NAME>>_regs_t, conf)` etc. against the header's struct type instead, whose type name and field names are both lowercase/un-prefixed and so are safely `<<NAME>>`-substitutable. cocotb's Python test module has no HDL-package import mechanism at all (it interacts with the DUT via signal handles, not by importing generated packages) — its three register addresses are hardcoded integers with a documented justification in Task 5, an accepted, explicit deviation from this principle.
- `scripts/init_project.sh`'s content-substitution and file-rename globs must include `.cpp`/`.h`/`.hpp`, or new C++ files won't survive `make init` correctly.
- Every task that touches a testbench must verify it by actually running it (real scratch-copy compile + execute, real pass/fail output) — not just confirming it parses or compiles.
- Do not run `make init` directly in the shared worktree — verification happens in `/tmp` scratch copies, exactly as established in the prior register-autowiring plan's tasks.

---

### Task 1: Add the VHDL simulation read/write package generator

**Files:**
- Modify: `scripts/gen_regs.py`

**Interfaces:**
- Produces: `generate_from_toml`'s VHDL branch now also writes `out/regs/vhdl/<name>_register_read_write_pkg.vhd`.

This is a currently-installed-but-unused `hdl_registers` generator. No new unit test is needed for this one-line addition (it delegates entirely to a third-party generator, mirroring how Task 5 of the original register-autowiring plan treated `generate_sv` — no toolchain-free way to unit test generated-file content beyond what `hdl_registers`' own test suite already covers). Verification is Task 4 (VUnit) actually consuming the generated file.

- [ ] **Step 1: Add the import**

In `scripts/gen_regs.py`, find the existing VHDL generator imports:

```python
from hdl_registers.generator.vhdl.register_package import VhdlRegisterPackageGenerator
from hdl_registers.generator.vhdl.record_package import VhdlRecordPackageGenerator
from hdl_registers.generator.vhdl.axi_lite.wrapper import VhdlAxiLiteWrapperGenerator
```

Add immediately after:

```python
from hdl_registers.generator.vhdl.simulation.read_write_package import (
    VhdlSimulationReadWritePackageGenerator,
)
```

- [ ] **Step 2: Call it in the VHDL branch of `generate_from_toml`**

Find:

```python
    if language == "vhdl":
        VhdlRegisterPackageGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
        VhdlRecordPackageGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
        VhdlAxiLiteWrapperGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
    else:
        generate_sv(register_list, GEN_SV)
```

Add a fourth call inside the `if` branch:

```python
    if language == "vhdl":
        VhdlRegisterPackageGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
        VhdlRecordPackageGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
        VhdlAxiLiteWrapperGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
        VhdlSimulationReadWritePackageGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
    else:
        generate_sv(register_list, GEN_SV)
```

- [ ] **Step 3: Verify by generating for real**

```bash
rm -rf /tmp/task1-verify
mkdir -p /tmp/task1-verify
cd /Users/james/Workspace/hdl_template/.claude/worktrees/tb-top-axi-lite
.venv/bin/python3 -c "
from pathlib import Path
from hdl_registers.parser.toml import from_toml
import sys; sys.path.insert(0, 'scripts')
from gen_regs import generate_from_toml
import gen_regs
gen_regs.GEN_VHDL = Path('/tmp/task1-verify')
gen_regs.GEN_VHDL.mkdir(exist_ok=True)
gen_regs.GEN_C = Path('/tmp/task1-verify-c'); gen_regs.GEN_C.mkdir(exist_ok=True)
gen_regs.GEN_HTML = Path('/tmp/task1-verify-html'); gen_regs.GEN_HTML.mkdir(exist_ok=True)
"
```

This inline monkeypatch approach is finicky (module-level constants) — simpler: just run `make regs` in a throwaway full-repo copy and check the output file exists:

```bash
rm -rf /tmp/task1-verify-repo
cp -r /Users/james/Workspace/hdl_template/.claude/worktrees/tb-top-axi-lite /tmp/task1-verify-repo
cd /tmp/task1-verify-repo
rm -rf .git out .venv
git init -q
git add -A -- . ':!out'
git -c user.email=test@test.com -c user.name=test commit -q -m scratch
~/.pyenv/versions/3.13.3/bin/python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
make regs
ls out/regs/vhdl/ | grep register_read_write_pkg
```

Expected: `NAME_register_read_write_pkg.vhd` exists (pre-init, name is literal `NAME`). Clean up: `rm -rf /tmp/task1-verify-repo`.

- [ ] **Step 4: Commit**

```bash
git add scripts/gen_regs.py
git commit -m "Generate the VHDL simulation read/write package for register access in testbenches"
```

---

### Task 2: Add the SV register-address package generator

**Files:**
- Modify: `scripts/gen_regs.py`
- Modify: `scripts/tests/test_gen_regs.py`
- Modify: `Bender.yml`
- Modify: `template.core`

**Interfaces:**
- Produces: `render_sv_address_constants(register_list) -> str`. `generate_sv` now also writes `out/regs/sv/<name>_regs_addr_pkg.sv`.

**Note on scope**: this task also updates `Bender.yml`'s `gen_sv` target (an explicit file list, not a glob — the new file won't be picked up otherwise) and `template.core`'s matching fileset, since `$(SV_GEN)` (used by `lint-sv`, `synth`, `impl`, cocotb's SV build, and — added by this plan — native-sv's and cpp's builds) is how every SV consumer finds generated register files. Without this, every later task that expects `<<NAME>>_regs_addr_pkg` to be visible via `$(SV_GEN)` would fail with a missing-package error that looks like a bug in that later task, when the real cause is here.

- [ ] **Step 1: Write the failing tests**

Add to `scripts/tests/test_gen_regs.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python3 -m pytest scripts/tests/test_gen_regs.py -v -k "address_constants"
```

Expected: `AttributeError` — `gen_regs.render_sv_address_constants` doesn't exist yet.

- [ ] **Step 3: Add the function to `scripts/gen_regs.py`**

Add it in the "SystemVerilog register-file generation" section, immediately before `_make_sv_synthesizable`:

```python
def render_sv_address_constants(register_list) -> str:
    """Generate a small SV package with one localparam per register's byte
    address (4 * 0-based index into the register list) -- the same
    computation the VHDL path's generated read/write package uses
    internally. Verified: generated for this project's real register map,
    compiled and ran cleanly under both Verilator and Icarus.

    Names are deliberately lowercase (demo_conf_addr, not DEMO_CONF_ADDR):
    <<NAME>> template substitution is a literal, case-preserving text
    replacement, so only lowercase-project-name-prefixed identifiers are
    reachable from a template testbench file written pre-init. This also
    matches <name>_regs_pkg.vhd's existing lowercase constant convention
    (demo_conf, demo_command, demo_status).
    """
    name = register_list.name
    lines = [f"package {name}_regs_addr_pkg;"]
    for index, register in enumerate(register_list.register_objects):
        const_name = f"{name}_{register.name}_addr"
        lines.append(f"    localparam int unsigned {const_name} = 4 * {index};")
    lines.append("endpackage")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Call it from `generate_sv`**

Find:

```python
    for filename in (
        f"{register_list.name}_register_file_axi_lite.sv",
        f"{register_list.name}_register_file_axi_lite_pkg.sv",
    ):
        generated_file = output_folder / filename
        generated_file.write_text(_make_sv_synthesizable(generated_file.read_text()))
```

Add immediately after that loop, still inside `generate_sv`:

```python
    addr_pkg_file = output_folder / f"{register_list.name}_regs_addr_pkg.sv"
    addr_pkg_file.write_text(render_sv_address_constants(register_list))
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/python3 -m pytest scripts/tests/test_gen_regs.py -v
```

Expected: all tests pass (33 existing + 2 new = 35).

- [ ] **Step 6: Verify the generated file actually compiles**

```bash
rm -rf /tmp/task2-verify
mkdir -p /tmp/task2-verify
cd /Users/james/Workspace/hdl_template/.claude/worktrees/tb-top-axi-lite
.venv/bin/python3 -c "
from pathlib import Path
from hdl_registers.parser.toml import from_toml
import sys; sys.path.insert(0, 'scripts')
from gen_regs import generate_sv
rl = from_toml(name='demo', toml_file=Path('regs/NAME_regs.toml'))
generate_sv(rl, Path('/tmp/task2-verify'))
"
cat > /tmp/task2-verify/spike_top.sv <<'EOF'
module spike_top;
    import demo_regs_addr_pkg::*;
    initial $display("conf=%0d command=%0d status=%0d", demo_conf_addr, demo_command_addr, demo_status_addr);
endmodule
EOF
verilator --binary --timing -Wall -Wno-fatal -j 0 -Mdir /tmp/task2-verify/obj --top-module spike_top /tmp/task2-verify/demo_regs_addr_pkg.sv /tmp/task2-verify/spike_top.sv
/tmp/task2-verify/obj/Vspike_top
```

Expected: `conf=0 command=4 status=8`, no errors. Clean up: `rm -rf /tmp/task2-verify`.

- [ ] **Step 7: Wire the new file into `Bender.yml`'s `gen_sv` target**

Find (in `Bender.yml`):

```yaml
  - target: gen_sv
    files:
      - out/regs/sv/<<NAME>>_register_file_axi_lite_pkg.sv
      - out/regs/sv/<<NAME>>_register_file_axi_lite.sv
```

Add the new file (package-before-module ordering doesn't matter here since the address package has no dependency on the register-file package, but list it first for consistency with "packages before consumers"):

```yaml
  - target: gen_sv
    files:
      - out/regs/sv/<<NAME>>_regs_addr_pkg.sv
      - out/regs/sv/<<NAME>>_register_file_axi_lite_pkg.sv
      - out/regs/sv/<<NAME>>_register_file_axi_lite.sv
```

- [ ] **Step 8: Mirror the same change in `template.core`**

`template.core` is a FuseSoC manifest kept in sync with `Bender.yml` (per `CLAUDE.md`) — find its `gen_sv` fileset (mirrors the Bender target from the original register-autowiring plan's Task 8) and add the same file in the same position.

- [ ] **Step 9: Verify `$(SV_GEN)` now includes the new file**

```bash
cd /Users/james/Workspace/hdl_template/.claude/worktrees/tb-top-axi-lite
bender script flist -t gen_sv 2>/dev/null
```

Expected: three paths listed, including one ending in `_regs_addr_pkg.sv`.

- [ ] **Step 10: Commit**

```bash
git add scripts/gen_regs.py scripts/tests/test_gen_regs.py Bender.yml template.core
git commit -m "Add SV register-address constants generator for testbench use"
```

---

### Task 3: Extend `init_project.sh` for `.cpp`/`.h`/`.hpp`

**Files:**
- Modify: `scripts/init_project.sh`

**Interfaces:** none (shell script glob extension).

- [ ] **Step 1: Extend the content-substitution glob**

Find (the `find` command building the list of files whose `<<NAME>>` content gets substituted):

```bash
    \( \
        -name "*.vhd" -o -name "*.sv"   -o -name "*.v"    \
        -o -name "*.py"  -o -name "*.sh"  -o -name "*.toml" \
        -o -name "*.yml" -o -name "*.yaml"\
        -o -name "*.rst" -o -name "*.md"  -o -name "*.txt"  \
        -o -name "Makefile" -o -name "*.mk" -o -name "*.core" \
        -o -name "*.f"   -o -name "*.ys"  -o -name "*.xdc"  \
        -o -name "Bender.yml" \
    \) -print0 2>/dev/null)
```

Change to:

```bash
    \( \
        -name "*.vhd" -o -name "*.sv"   -o -name "*.v"    \
        -o -name "*.py"  -o -name "*.sh"  -o -name "*.toml" \
        -o -name "*.yml" -o -name "*.yaml"\
        -o -name "*.rst" -o -name "*.md"  -o -name "*.txt"  \
        -o -name "Makefile" -o -name "*.mk" -o -name "*.core" \
        -o -name "*.f"   -o -name "*.ys"  -o -name "*.xdc"  \
        -o -name "*.cpp" -o -name "*.h"   -o -name "*.hpp"  \
        -o -name "Bender.yml" \
    \) -print0 2>/dev/null)
```

- [ ] **Step 2: Extend the file-rename glob**

Find:

```bash
    \( \
        -name "NAME_*.vhd" -o -name "NAME_*.sv" -o -name "NAME_*.v" \
        -o -name "NAME_*.py" -o -name "NAME_*.toml" -o -name "NAME_*.ys" \
        -o -name "NAME_*.xdc" -o -name "NAME_*.rst" \
    \) -print0 2>/dev/null)
```

Change to:

```bash
    \( \
        -name "NAME_*.vhd" -o -name "NAME_*.sv" -o -name "NAME_*.v" \
        -o -name "NAME_*.py" -o -name "NAME_*.toml" -o -name "NAME_*.ys" \
        -o -name "NAME_*.xdc" -o -name "NAME_*.rst" \
        -o -name "NAME_*.cpp" -o -name "NAME_*.h" -o -name "NAME_*.hpp" \
    \) -print0 2>/dev/null)
```

- [ ] **Step 3: Verify with a synthetic file (cpp files don't exist yet — Task 9 adds the real ones; this proves the glob mechanics work)**

```bash
rm -rf /tmp/task3-verify
cp -r /Users/james/Workspace/hdl_template/.claude/worktrees/tb-top-axi-lite /tmp/task3-verify
cd /tmp/task3-verify
mkdir -p tb/cpp
echo '// <<NAME>> dummy' > tb/cpp/NAME_dummy.cpp
bash scripts/init_project.sh demoproj vhdl
cat src/demoproj_pkg.vhd > /dev/null  # sanity the real init still works
find tb/cpp -type f
cat tb/cpp/demoproj_dummy.cpp
```

Expected: `tb/cpp/demoproj_dummy.cpp` exists (renamed from `NAME_dummy.cpp`), containing `// demoproj dummy` (substituted). Clean up: `rm -rf /tmp/task3-verify`.

- [ ] **Step 4: Commit**

```bash
git add scripts/init_project.sh
git commit -m "Extend init_project.sh to handle .cpp/.h/.hpp files"
```

---

### Task 4: Port the VUnit testbench to target `_top`

**Files:**
- Modify: `tb/vunit/run.py`
- Modify: `tb/vunit/vhdl/NAME_tb.vhd`

**Interfaces:**
- Consumes: Task 1's `<name>_register_read_write_pkg.vhd` (procedures `write_demo_conf_enable`, `write_demo_conf_increment`, `write_demo_command_reset_count`, `read_demo_status_enabled`, `read_demo_status_pulse_count` — real names verified by actually running the generator against this project's register map).
- Produces: nothing consumed by later tasks (VUnit is a leaf testbench).

**Verified dependency chain** (every file below was traced by hand from `axi_lite_master.vhd`'s own `library`/`use`/`entity work.X` clauses, not assumed): `axi_lite_master.vhd` (the BFM) instantiates `entity common.axi_stream_protocol_checker`, which itself needs `work.types_pkg` (i.e., `common.types_pkg` once compiled) — both from `hdl-modules/modules/common/src/`. This is a real transitive dependency that isn't needed by `lint-vhdl`/`synth` (which never use the BFM), so it isn't already wired into any existing Makefile variable — `run.py` needs it explicitly.

- [ ] **Step 1: Rewrite `tb/vunit/run.py`**

Replace the whole file with:

```python
#!/usr/bin/env python3
"""VUnit test runner for the <<NAME>> design.

Run with GHDL (set by the Makefile via VUNIT_SIMULATOR):
    make sim FRAMEWORK=vunit

Or directly:
    VUNIT_SIMULATOR=ghdl python tb/vunit/run.py
    VUNIT_SIMULATOR=ghdl python tb/vunit/run.py -v --no-color   # verbose
    VUNIT_SIMULATOR=ghdl python tb/vunit/run.py --list           # list tests
    VUNIT_SIMULATOR=ghdl python tb/vunit/run.py -g               # GUI mode
"""

import subprocess
from pathlib import Path
from vunit import VUnit

# Repository root (two levels up from this file: tb/vunit/run.py → repo root)
ROOT = Path(__file__).resolve().parents[2]

vu = VUnit.from_argv(compile_builtins=False)
vu.add_vhdl_builtins()

# ── hdl-modules dependency (AXI-Lite types, register file, and the
# axi_lite_master BFM that drives <<NAME>>_top's AXI-Lite port) ─────────────
HDL_MODULES = Path(
    subprocess.run(
        ["bender", "path", "hdl_modules"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
)

axi_lite_lib = vu.add_library("axi_lite")
axi_lite_lib.add_source_files(HDL_MODULES / "modules" / "axi_lite" / "src" / "axi_lite_pkg.vhd")

# common: needed transitively by the axi_lite_master BFM's internal
# axi_stream_protocol_checker instances -- not needed by lint-vhdl/synth,
# which never use the BFM, so it isn't already wired in elsewhere.
common_lib = vu.add_library("common")
common_lib.add_source_files(HDL_MODULES / "modules" / "common" / "src" / "types_pkg.vhd")
common_lib.add_source_files(
    HDL_MODULES / "modules" / "common" / "src" / "axi_stream_protocol_checker.vhd"
)

register_file_lib = vu.add_library("register_file")
register_file_lib.add_source_files(
    HDL_MODULES / "modules" / "register_file" / "src" / "register_file_pkg.vhd"
)
register_file_lib.add_source_files(
    HDL_MODULES / "modules" / "register_file" / "src" / "axi_lite_register_file.vhd"
)
register_file_lib.add_source_files(
    HDL_MODULES / "modules" / "register_file" / "sim" / "register_operations_pkg.vhd"
)

bfm_lib = vu.add_library("bfm")
bfm_lib.add_source_files(HDL_MODULES / "modules" / "bfm" / "sim" / "axi_lite_master.vhd")

# ── RTL library ──────────────────────────────────────────────────────────────
rtl_lib = vu.add_library("rtl_lib")
rtl_lib.add_source_files(ROOT / "src" / "<<NAME>>_pkg.vhd")
rtl_lib.add_source_files(ROOT / "src" / "<<NAME>>_core.vhd")
rtl_lib.add_source_files(ROOT / "src" / "<<NAME>>_top.vhd")

# ── Generated register files (produced by `make regs`) ──────────────────────
gen_dir = ROOT / "out" / "regs" / "vhdl"
rtl_lib.add_source_files(gen_dir / "<<NAME>>_regs_pkg.vhd")
rtl_lib.add_source_files(gen_dir / "<<NAME>>_register_record_pkg.vhd")
rtl_lib.add_source_files(gen_dir / "<<NAME>>_register_file_axi_lite.vhd")
rtl_lib.add_source_files(gen_dir / "<<NAME>>_register_read_write_pkg.vhd")

# ── Testbench library ─────────────────────────────────────────────────────────
tb_lib = vu.add_library("tb_lib")
tb_lib.add_source_files(ROOT / "tb" / "vunit" / "vhdl" / "<<NAME>>_tb.vhd")

vu.main()
```

- [ ] **Step 2: Rewrite `tb/vunit/vhdl/NAME_tb.vhd`**

Replace the whole file with:

```vhdl
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library vunit_lib;
context vunit_lib.vunit_context;

library axi_lite;
use axi_lite.axi_lite_pkg.all;

library rtl_lib;
use rtl_lib.<<NAME>>_pkg.all;
use rtl_lib.<<NAME>>_regs_pkg.all;
use rtl_lib.<<NAME>>_register_read_write_pkg.all;

-- VUnit testbench for <<NAME>>_top.
--
-- Drives the design through its real AXI-Lite register interface (via
-- hdl-modules' axi_lite_master BFM) rather than <<NAME>>_core's plain ports
-- directly -- this exercises the auto-wired register integration, not just
-- the core counter logic.
--
-- Test cases:
--   test_count_up    — count increments on each pulse when enabled
--   test_saturation  — counter saturates at (2**C_COUNT_W)-1
--   test_reset_count — reset_count clears count in one cycle
--   test_disable     — count holds when enable is deasserted
entity <<NAME>>_tb is
    generic (runner_cfg : string);
end entity <<NAME>>_tb;

architecture bench of <<NAME>>_tb is

    signal clk       : std_logic := '0';
    signal rst_n     : std_logic := '0';
    signal pulse_i   : std_logic := '0';

    signal s_axi_m2s : axi_lite_m2s_t;
    signal s_axi_s2m : axi_lite_s2m_t;

    -- 10 ns clock (100 MHz)
    constant C_CLK_PERIOD : time := 10 ns;

    procedure clk_edge is
    begin
        wait until rising_edge(clk);
        wait for 1 ps;
    end procedure;

begin

    clk <= not clk after C_CLK_PERIOD / 2;

    -- DUT instantiation: <<NAME>>_top, not <<NAME>>_core.
    u_dut : entity rtl_lib.<<NAME>>_top
        port map (
            clk       => clk,
            rst_n     => rst_n,
            pulse_i   => pulse_i,
            s_axi_m2s => s_axi_m2s,
            s_axi_s2m => s_axi_s2m
        );

    -- AXI-Lite bus master BFM, driven by the generated read/write
    -- procedures below via VUnit's message-passing bus_handle.
    u_axi_lite_master : entity bfm.axi_lite_master
        port map (
            clk          => clk,
            axi_lite_m2s => s_axi_m2s,
            axi_lite_s2m => s_axi_s2m
        );

    main : process is
    begin
        test_runner_setup(runner, runner_cfg);

        -- Release reset
        clk_edge;
        rst_n <= '1';
        clk_edge;

        -- ── test_count_up ─────────────────────────────────────────────────
        if run("test_count_up") then
            write_<<NAME>>_conf_increment(net, 1);
            write_<<NAME>>_conf_enable(net, '1');
            for i in 1 to 8 loop
                clk_edge;
                check_equal(read_pulse_count, i, "count_up: expected " & integer'image(i));
            end loop;
            check_equal(read_enabled, '1', "enabled should be high when counting");
        end if;

        -- ── test_saturation ───────────────────────────────────────────────
        if run("test_saturation") then
            write_<<NAME>>_conf_increment(net, 255);
            write_<<NAME>>_conf_enable(net, '1');
            for i in 1 to (2**C_COUNT_W - 1) / 255 + 2 loop
                clk_edge;
            end loop;
            check_equal(read_pulse_count, 2**C_COUNT_W - 1, "counter should saturate at max value");
        end if;

        -- ── test_reset_count ──────────────────────────────────────────────
        if run("test_reset_count") then
            write_<<NAME>>_conf_increment(net, 1);
            write_<<NAME>>_conf_enable(net, '1');
            for i in 1 to 5 loop
                clk_edge;
            end loop;
            check_equal(read_pulse_count, 5, "count before reset");

            write_<<NAME>>_command_reset_count(net, '1');
            clk_edge;
            write_<<NAME>>_command_reset_count(net, '0');
            check_equal(read_pulse_count, 0, "count after reset");
        end if;

        -- ── test_disable ──────────────────────────────────────────────────
        if run("test_disable") then
            write_<<NAME>>_conf_increment(net, 1);
            write_<<NAME>>_conf_enable(net, '1');
            for i in 1 to 4 loop
                clk_edge;
            end loop;
            check_equal(read_pulse_count, 4, "count before disable");

            write_<<NAME>>_conf_enable(net, '0');
            for i in 1 to 4 loop
                clk_edge;
            end loop;
            check_equal(read_pulse_count, 4, "count should hold when disabled");
            check_equal(read_enabled, '0', "enabled should be low when disabled");
        end if;

        test_runner_cleanup(runner);
    end process main;

    test_runner_watchdog(runner, 1 ms);

end architecture bench;
```

**This step needs real per-project procedure names, not the placeholder-style `write_<<NAME>>_conf_increment` shown above** — `<<NAME>>` is a literal template token pre-init, but the *generated* procedures use the TOML-derived register-list name (e.g. `demo` when testing manually, the real project name post-init), not the literal string `<<NAME>>`. Before writing this file for real, generate the read/write package for the current pre-init `regs/NAME_regs.toml` (name resolves to literal `NAME`) and copy the *exact* procedure names it contains — do not guess-and-check. Also add two small local helper functions to keep the test body readable, since the generated procedures need `net`/`bus_handle` plumbing that returns via `out`/`variable` parameters rather than a function return value:

```vhdl
    impure function read_pulse_count return integer is
        variable value : integer;
    begin
        read_<<NAME>>_status_pulse_count(net, value);
        return value;
    end function;

    impure function read_enabled return std_ulogic is
        variable value : std_ulogic;
    begin
        read_<<NAME>>_status_enabled(net, value);
        return value;
    end function;
```

(Place these in the architecture's declarative region, above `begin`.) Replace every literal `<<NAME>>` in generated-procedure-name positions with the real generated names once confirmed against actual generator output.

- [ ] **Step 3: Verify end-to-end in a scratch copy**

```bash
rm -rf /tmp/task4-verify
cp -r /Users/james/Workspace/hdl_template/.claude/worktrees/tb-top-axi-lite /tmp/task4-verify
cd /tmp/task4-verify
rm -rf .git out .venv
git init -q
bash scripts/init_project.sh demoproj vhdl
git add -A -- . ':!out'
git -c user.email=test@test.com -c user.name=test commit -q -m scratch
~/.pyenv/versions/3.13.3/bin/python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
make deps
make regs
make sim FRAMEWORK=vunit
```

Expected: all 4 VUnit tests pass. If GHDL reports a missing library/file, re-check the dependency chain in Step 1 against the real `hdl-modules` checkout (`bender path hdl_modules`) rather than guessing a fix. Clean up: `rm -rf /tmp/task4-verify`.

- [ ] **Step 4: Commit**

```bash
git add tb/vunit/run.py tb/vunit/vhdl/NAME_tb.vhd
git commit -m "Port VUnit testbench to target <<NAME>>_top via AXI-Lite"
```

---

### Task 5: Port the cocotb testbench (both languages) to target `_top`

**Files:**
- Modify: `tb/cocotb/Makefile`
- Modify: `tb/cocotb/test_NAME.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `cocotbext-axi`'s `AxiLiteMaster`/`AxiLiteBus` (real API verified in the design spec).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the dependency**

In `requirements.txt`, add near the cocotb-related lines:

```
cocotbext-axi
```

- [ ] **Step 2: Rewrite `tb/cocotb/test_NAME.py`**

Replace the whole file with:

```python
"""cocotb testbench for <<NAME>>_top.

Drives the design through its real AXI-Lite register interface (via
cocotbext-axi) rather than <<NAME>>_core's plain ports directly -- this
exercises the auto-wired register integration, not just the core counter
logic. Runs against both the VHDL and SystemVerilog implementations via
the same test suite -- AXI-Lite signal names are identical across both.

Run via the top-level Makefile:
    make sim FRAMEWORK=cocotb SIM=ghdl       TOPLEVEL_HDL=vhdl
    make sim FRAMEWORK=cocotb SIM=verilator  TOPLEVEL_HDL=sv
    make sim FRAMEWORK=cocotb SIM=icarus     TOPLEVEL_HDL=sv
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from cocotbext.axi import AxiLiteBus, AxiLiteMaster

CONF_ADDR = 0
COMMAND_ADDR = 4
STATUS_ADDR = 8


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
    """Counter increments by the configured step on each clock when enabled."""
    axil = await setup(dut)
    await write_conf(axil, enable=True, increment=1)

    for expected in range(1, 9):
        await RisingEdge(dut.clk)
        _, pulse_count = await read_status(axil)
        assert pulse_count == expected, f"Expected count={expected}, got {pulse_count}"
    enabled, _ = await read_status(axil)
    assert enabled == 1, "enabled should be high when counting"


@cocotb.test()
async def test_increment_step(dut):
    """Counter adds the configured step (not just 1) per clock."""
    axil = await setup(dut)
    step = 5
    await write_conf(axil, enable=True, increment=step)

    for i in range(1, 5):
        await RisingEdge(dut.clk)
        _, pulse_count = await read_status(axil)
        assert pulse_count == i * step, f"Expected count={i * step}, got {pulse_count}"


@cocotb.test()
async def test_reset_count(dut):
    """command.reset_count clears the counter in one cycle."""
    axil = await setup(dut)
    await write_conf(axil, enable=True, increment=1)
    for _ in range(5):
        await RisingEdge(dut.clk)

    _, pulse_count = await read_status(axil)
    assert pulse_count == 5, "pre-reset count should be 5"

    await write_command_reset_count(axil, True)
    await RisingEdge(dut.clk)
    await write_command_reset_count(axil, False)
    await RisingEdge(dut.clk)

    _, pulse_count = await read_status(axil)
    assert pulse_count == 0, "count should be 0 after reset pulse"


@cocotb.test()
async def test_disable_holds_count(dut):
    """Count holds its value when enable is deasserted."""
    axil = await setup(dut)
    await write_conf(axil, enable=True, increment=1)
    for _ in range(4):
        await RisingEdge(dut.clk)

    _, pulse_count = await read_status(axil)
    assert pulse_count == 4

    await write_conf(axil, enable=False, increment=1)
    for _ in range(4):
        await RisingEdge(dut.clk)

    enabled, pulse_count = await read_status(axil)
    assert pulse_count == 4, "count should hold when disabled"
    assert enabled == 0, "enabled should be low when disabled"


@cocotb.test()
async def test_saturation(dut):
    """Counter saturates at (2**COUNT_W)-1 rather than wrapping."""
    axil = await setup(dut)
    max_val = (1 << 16) - 1  # 65535 for C_COUNT_W=16
    await write_conf(axil, enable=True, increment=255)

    cycles_to_saturate = max_val // 255 + 4
    for _ in range(cycles_to_saturate):
        await RisingEdge(dut.clk)

    _, pulse_count = await read_status(axil)
    assert pulse_count == max_val, f"Expected saturation at {max_val}, got {pulse_count}"
```

Note: `CONF_ADDR`/`COMMAND_ADDR`/`STATUS_ADDR` are hardcoded to `0`/`4`/`8` here rather than sourced from a generated artifact, because cocotb's DUT-agnostic Python test module has no natural single source for these across both VHDL and SV builds within this task's scope — this is an accepted, explicit deviation from the "source addresses from generated artifacts" principle in the spec, justified because the register map's *order* (conf, command, status) is fixed by `regs/NAME_regs.toml` and unlikely to silently reorder; if this ever becomes fragile in practice, a follow-up could parse `out/regs/c/<name>_regs.h` from Python at test-collection time.

- [ ] **Step 3: Rewrite `tb/cocotb/Makefile`**

Read the current file first to confirm its exact current shape before editing (it was last touched when Task 8 of the register-autowiring plan wired in `gen_sv`/`gen_vhdl` sources — confirm that wiring is still intact and build on it, don't revert it). Then modify the `VHDL_SOURCES`/`VERILOG_SOURCES` construction (exact variable names depend on what's there — read first) so that:

- The VHDL branch compiles, in order: `hdl-modules`' `axi_lite_pkg.vhd`, `common`'s `types_pkg.vhd` + `axi_stream_protocol_checker.vhd` (not actually needed for cocotb — cocotb doesn't use the BFM, only the generated register file needs `axi_lite_pkg`/`register_file_pkg`; skip the BFM-only `common`/`bfm` library additions here, they're VUnit-specific), `register_file_pkg.vhd`, `axi_lite_register_file.vhd`, then the project's `<<NAME>>_pkg.vhd`, the generated `<<NAME>>_regs_pkg.vhd`/`<<NAME>>_register_record_pkg.vhd`/`<<NAME>>_register_file_axi_lite.vhd`, `<<NAME>>_core.vhd`, and `<<NAME>>_top.vhd` (replacing the current `TOPLEVEL = <<NAME>>_core` with `TOPLEVEL = <<NAME>>_top`, and removing `<<NAME>>_top.vhd` from any exclusion).
- The SV branch compiles the project's `<<NAME>>_pkg.sv`, the generated `out/regs/sv/<<NAME>>_register_file_axi_lite_pkg.sv` + `<<NAME>>_register_file_axi_lite.sv` (package before module, matching the ordering requirement already established in `Makefile`'s `SV_GEN` wiring), `<<NAME>>_core.sv`, and `<<NAME>>_top.sv` (replacing `TOPLEVEL = <<NAME>>_core` with `TOPLEVEL = <<NAME>>_top`).
- Delete the now-inaccurate header comment: *"The top-level for cocotb tests is `<<NAME>>_core` (not `_top`), so the AXI-Lite register block is not involved and no hdl-modules dependency is needed."* Replace with a short, accurate description (register integration is now exercised via `_top`'s AXI-Lite port).

- [ ] **Step 4: Verify end-to-end, both languages, all three simulator combinations**

```bash
rm -rf /tmp/task5-verify-vhdl /tmp/task5-verify-sv
cp -r /Users/james/Workspace/hdl_template/.claude/worktrees/tb-top-axi-lite /tmp/task5-verify-vhdl
cp -r /Users/james/Workspace/hdl_template/.claude/worktrees/tb-top-axi-lite /tmp/task5-verify-sv
cd /tmp/task5-verify-vhdl
rm -rf .git out .venv
git init -q
bash scripts/init_project.sh demoproj vhdl
git add -A -- . ':!out'; git -c user.email=test@test.com -c user.name=test commit -q -m scratch
~/.pyenv/versions/3.13.3/bin/python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
make deps
make regs
make sim FRAMEWORK=cocotb SIM=ghdl TOPLEVEL_HDL=vhdl

cd /tmp/task5-verify-sv
rm -rf .git out .venv
git init -q
bash scripts/init_project.sh demoproj sv
git add -A -- . ':!out'; git -c user.email=test@test.com -c user.name=test commit -q -m scratch
~/.pyenv/versions/3.13.3/bin/python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
make regs
make sim FRAMEWORK=cocotb SIM=verilator TOPLEVEL_HDL=sv
make sim FRAMEWORK=cocotb SIM=icarus TOPLEVEL_HDL=sv
```

Expected: all 5 tests pass in all three combinations. Clean up: `rm -rf /tmp/task5-verify-vhdl /tmp/task5-verify-sv`.

- [ ] **Step 5: Commit**

```bash
git add tb/cocotb/Makefile tb/cocotb/test_NAME.py requirements.txt
git commit -m "Port cocotb testbench to target <<NAME>>_top via AXI-Lite (cocotbext-axi)"
```

---

### Task 6: Write the native-sv hand-rolled AXI-Lite driver package

**Files:**
- Create: `tb/native/sv/axi_lite_driver_pkg.sv`

**Interfaces:**
- Produces: `task automatic axil_write(ref logic awvalid, ..., input logic [7:0] addr, input logic [31:0] data, ref logic clk)`-shaped tasks (exact signature below) — consumed by Task 8.

This is a standalone, independently-testable unit before it's wired into the real testbench (Task 8) — verify it against a trivial local slave model first, exactly as the pulp-platform spike did, so any bugs surface here rather than tangled up with the real DUT.

- [ ] **Step 1: Write the driver package**

```systemverilog
// Hand-rolled AXI-Lite bus driver for native (framework-less) SystemVerilog
// testbenches. No off-the-shelf, non-UVM, Verilator-compatible SV AXI-Lite
// BFM was found (pulp-platform/axi's axi_test.sv was spiked directly and
// fails under Verilator on unused full-AXI classes) -- see
// docs/superpowers/specs/2026-08-21-testbenches-target-top-design.md.
// Single-beat only, no bursts, no backpressure injection: exactly what
// this project's test scenarios need, nothing more. A real BFM can
// replace this later without touching the testbench that calls it, as
// long as the axil_write/axil_read task signatures stay the same.
package axi_lite_driver_pkg;

    task automatic axil_write(
        ref   logic        clk,
        ref   logic        awvalid, ref logic awready, ref logic [7:0]  awaddr,
        ref   logic        wvalid,  ref logic wready,  ref logic [31:0] wdata, ref logic [3:0] wstrb,
        ref   logic        bvalid,  ref logic bready,
        input logic [7:0]  addr,
        input logic [31:0] data
    );
        awvalid = 1'b1; awaddr = addr;
        wvalid  = 1'b1; wdata  = data; wstrb = 4'b1111;
        bready  = 1'b1;
        do @(posedge clk); while (!awready);
        awvalid = 1'b0;
        do @(posedge clk); while (!wready);
        wvalid = 1'b0;
        do @(posedge clk); while (!bvalid);
        bready = 1'b0;
    endtask

    task automatic axil_read(
        ref   logic        clk,
        ref   logic        arvalid, ref logic arready, ref logic [7:0]  araddr,
        ref   logic        rvalid,  ref logic rready,  ref logic [31:0] rdata,
        input logic [7:0]  addr,
        output logic [31:0] data
    );
        arvalid = 1'b1; araddr = addr;
        rready  = 1'b1;
        do @(posedge clk); while (!arready);
        arvalid = 1'b0;
        do @(posedge clk); while (!rvalid);
        data = rdata;
        rready = 1'b0;
    endtask

endpackage : axi_lite_driver_pkg
```

- [ ] **Step 2: Write a standalone spike testbench to verify it (scratch, not committed)**

```bash
mkdir -p /tmp/task6-verify
cat > /tmp/task6-verify/spike_dut.sv <<'EOF'
module spike_dut (
    input  logic        clk, input logic rst_n,
    input  logic        s_axi_awvalid, output logic s_axi_awready, input logic [7:0] s_axi_awaddr,
    input  logic        s_axi_wvalid,  output logic s_axi_wready,  input logic [31:0] s_axi_wdata, input logic [3:0] s_axi_wstrb,
    output logic        s_axi_bvalid,  input logic s_axi_bready,
    input  logic        s_axi_arvalid, output logic s_axi_arready, input logic [7:0] s_axi_araddr,
    output logic        s_axi_rvalid,  input logic s_axi_rready,  output logic [31:0] s_axi_rdata
);
    logic [31:0] mem [0:255];
    assign s_axi_awready = 1'b1;
    assign s_axi_wready  = 1'b1;
    assign s_axi_arready = 1'b1;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            s_axi_bvalid <= 1'b0; s_axi_rvalid <= 1'b0;
        end else begin
            if (s_axi_awvalid && s_axi_wvalid) begin mem[s_axi_awaddr] <= s_axi_wdata; s_axi_bvalid <= 1'b1; end
            else if (s_axi_bready) s_axi_bvalid <= 1'b0;
            if (s_axi_arvalid) begin s_axi_rdata <= mem[s_axi_araddr]; s_axi_rvalid <= 1'b1; end
            else if (s_axi_rready) s_axi_rvalid <= 1'b0;
        end
    end
endmodule

module spike_tb;
    import axi_lite_driver_pkg::*;
    logic clk = 0, rst_n = 0;
    always #5ns clk = ~clk;
    logic awvalid, awready, wvalid, wready, bvalid, bready, arvalid, arready, rvalid, rready;
    logic [7:0] awaddr, araddr;
    logic [31:0] wdata, rdata, read_result;
    logic [3:0] wstrb;
    spike_dut dut (.clk, .rst_n,
        .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_awaddr(awaddr),
        .s_axi_wvalid(wvalid), .s_axi_wready(wready), .s_axi_wdata(wdata), .s_axi_wstrb(wstrb),
        .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_araddr(araddr),
        .s_axi_rvalid(rvalid), .s_axi_rready(rready), .s_axi_rdata(rdata));
    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1;
        repeat (2) @(posedge clk);
        axil_write(clk, awvalid, awready, awaddr, wvalid, wready, wdata, wstrb, bvalid, bready, 8'h04, 32'hDEADBEEF);
        axil_read(clk, arvalid, arready, araddr, rvalid, rready, rdata, 8'h04, read_result);
        if (read_result !== 32'hDEADBEEF) begin $error("FAIL: got %h", read_result); $fatal(1); end
        $display("PASS");
        $finish;
    end
endmodule
EOF
cp /Users/james/Workspace/hdl_template/.claude/worktrees/tb-top-axi-lite/tb/native/sv/axi_lite_driver_pkg.sv /tmp/task6-verify/
verilator --binary --timing -Wall -Wno-fatal -j 0 -Mdir /tmp/task6-verify/obj --top-module spike_tb /tmp/task6-verify/axi_lite_driver_pkg.sv /tmp/task6-verify/spike_dut.sv
/tmp/task6-verify/obj/Vspike_tb
```

Expected: `PASS`, no `$fatal`. Clean up: `rm -rf /tmp/task6-verify`.

- [ ] **Step 3: Commit**

```bash
git add tb/native/sv/axi_lite_driver_pkg.sv
git commit -m "Add hand-rolled AXI-Lite driver package for native SystemVerilog testbenches"
```

---

### Task 7: Port the native-vhdl testbench to target `_top`

**Files:**
- Modify: `tb/native/vhdl/NAME_tb.vhd`

**Interfaces:** none produced (leaf testbench).

**Prerequisite for this task's implementer:** confirm `nvc --install osvvm` succeeds and produces the `osvvm_axi4` library before writing this file — if it's not already installed in this environment, install it now (`nvc --install osvvm`) rather than discovering the gap mid-task.

- [ ] **Step 1: Rewrite `tb/native/vhdl/NAME_tb.vhd`**

```vhdl
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

library work;
use work.<<NAME>>_pkg.all;
use work.<<NAME>>_regs_pkg.all;

library axi_lite;
use axi_lite.axi_lite_pkg.all;

library osvvm;
context osvvm.OsvvmContext;

library osvvm_axi4;
context osvvm_axi4.Axi4LiteContext;

-- Native (framework-less) testbench for <<NAME>>_top, run directly with NVC
-- -- no VUnit/cocotb dependency, but does depend on OSVVM (install once via
-- `nvc --install osvvm`) for its Axi4LiteManager verification component,
-- since a hand-rolled AXI-Lite driver would duplicate what OSVVM already
-- provides well for VHDL (unlike the SV/C++ paths, where no equivalent
-- off-the-shelf option exists -- see the design spec).
--
--   make sim-native TOPLEVEL_HDL=vhdl
--
-- Test cases:
--   count_up    -- count increments on each pulse when enabled
--   saturation  -- counter saturates at (2**C_COUNT_W)-1
--   reset_count -- command.reset_count clears count in one cycle
--   disable     -- count holds when enable is deasserted
entity <<NAME>>_tb is
end entity <<NAME>>_tb;

architecture bench of <<NAME>>_tb is

    constant AXI_ADDR_WIDTH : integer := 8;
    constant AXI_DATA_WIDTH : integer := 32;

    signal clk     : std_logic := '0';
    signal rst_n   : std_logic := '0';
    signal pulse_i : std_logic := '0';

    signal s_axi_m2s : axi_lite_m2s_t;
    signal s_axi_s2m : axi_lite_s2m_t;

    -- OSVVM's own AXI-Lite record type (different from hdl-modules'
    -- axi_lite_m2s_t/s2m_t used by <<NAME>>_top) -- bridged field-by-field
    -- below. Verified against Axi4LiteInterfacePkg.vhd's real record
    -- definitions.
    signal AxiBus : Axi4LiteRecType(
        WriteAddress(Addr(AXI_ADDR_WIDTH - 1 downto 0)),
        WriteData(Data(AXI_DATA_WIDTH - 1 downto 0), Strb(AXI_DATA_WIDTH / 8 - 1 downto 0)),
        ReadAddress(Addr(AXI_ADDR_WIDTH - 1 downto 0)),
        ReadData(Data(AXI_DATA_WIDTH - 1 downto 0))
    );

    signal ManagerRec : AddressBusRecType(
        Address(AXI_ADDR_WIDTH - 1 downto 0),
        DataToModel(AXI_DATA_WIDTH - 1 downto 0),
        DataFromModel(AXI_DATA_WIDTH - 1 downto 0)
    );

    constant C_CLK_PERIOD : time := 10 ns;

    -- Register byte addresses, computed from <<NAME>>_regs_pkg.vhd's real
    -- generated register-index constants (<<NAME>>_conf/_command/_status)
    -- rather than hand-typed hex -- these track the register map
    -- automatically if it's ever reordered.
    constant CONF_ADDR    : std_logic_vector(AXI_ADDR_WIDTH - 1 downto 0) :=
        std_logic_vector(to_unsigned(4 * <<NAME>>_conf, AXI_ADDR_WIDTH));
    constant COMMAND_ADDR : std_logic_vector(AXI_ADDR_WIDTH - 1 downto 0) :=
        std_logic_vector(to_unsigned(4 * <<NAME>>_command, AXI_ADDR_WIDTH));
    constant STATUS_ADDR  : std_logic_vector(AXI_ADDR_WIDTH - 1 downto 0) :=
        std_logic_vector(to_unsigned(4 * <<NAME>>_status, AXI_ADDR_WIDTH));

    procedure check_equal(actual, expected : unsigned; msg : string) is
    begin
        assert actual = expected
            report "FAIL: " & msg & " -- expected " & integer'image(to_integer(expected)) &
                   " got " & integer'image(to_integer(actual))
            severity failure;
    end procedure;

begin

    clk <= not clk after C_CLK_PERIOD / 2;

    u_dut : entity work.<<NAME>>_top
        port map (
            clk       => clk,
            rst_n     => rst_n,
            pulse_i   => pulse_i,
            s_axi_m2s => s_axi_m2s,
            s_axi_s2m => s_axi_s2m
        );

    u_axi_manager : Axi4LiteManager
        port map (
            Clk      => clk,
            nReset   => rst_n,  -- unused internally in this OSVVM version; tied for documentation only
            AxiBus   => AxiBus,
            TransRec => ManagerRec
        );

    -- Field-by-field bridge between OSVVM's Axi4LiteRecType and
    -- hdl-modules' axi_lite_m2s_t/s2m_t. Verified against both packages'
    -- real record definitions.
    s_axi_m2s.write.aw.valid <= AxiBus.WriteAddress.Valid;
    s_axi_m2s.write.aw.addr(AXI_ADDR_WIDTH - 1 downto 0) <= unsigned(AxiBus.WriteAddress.Addr);
    AxiBus.WriteAddress.Ready <= s_axi_s2m.write.aw.ready;

    s_axi_m2s.write.w.valid <= AxiBus.WriteData.Valid;
    s_axi_m2s.write.w.data(AXI_DATA_WIDTH - 1 downto 0) <= AxiBus.WriteData.Data;
    s_axi_m2s.write.w.strb(AXI_DATA_WIDTH / 8 - 1 downto 0) <= AxiBus.WriteData.Strb;
    AxiBus.WriteData.Ready <= s_axi_s2m.write.w.ready;

    AxiBus.WriteResponse.Valid <= s_axi_s2m.write.b.valid;
    AxiBus.WriteResponse.Resp <= s_axi_s2m.write.b.resp;
    s_axi_m2s.write.b.ready <= AxiBus.WriteResponse.Ready;

    s_axi_m2s.read.ar.valid <= AxiBus.ReadAddress.Valid;
    s_axi_m2s.read.ar.addr(AXI_ADDR_WIDTH - 1 downto 0) <= unsigned(AxiBus.ReadAddress.Addr);
    AxiBus.ReadAddress.Ready <= s_axi_s2m.read.ar.ready;

    AxiBus.ReadData.Valid <= s_axi_s2m.read.r.valid;
    AxiBus.ReadData.Data <= s_axi_s2m.read.r.data(AXI_DATA_WIDTH - 1 downto 0);
    AxiBus.ReadData.Resp <= s_axi_s2m.read.r.resp;
    s_axi_m2s.read.r.ready <= AxiBus.ReadData.Ready;

    main : process is
        variable read_data : std_logic_vector(AXI_DATA_WIDTH - 1 downto 0);
    begin
        wait until rst_n = '0';
        wait for C_CLK_PERIOD * 3;
        rst_n <= '1';
        wait for C_CLK_PERIOD;

        -- ── count_up ──────────────────────────────────────────────────────
        Write(ManagerRec, CONF_ADDR, x"00000003");  -- enable=1, increment=1
        for i in 1 to 8 loop
            wait for C_CLK_PERIOD;
            Read(ManagerRec, STATUS_ADDR, read_data);
            check_equal(unsigned(read_data(16 downto 1)), to_unsigned(i, 16), "count_up");
        end loop;
        Read(ManagerRec, STATUS_ADDR, read_data);
        assert read_data(0) = '1' report "FAIL: enabled should be high when counting" severity failure;

        -- ── saturation ────────────────────────────────────────────────────
        Write(ManagerRec, CONF_ADDR, x"000001FF");  -- enable=1, increment=255
        for i in 1 to (2**C_COUNT_W - 1) / 255 + 2 loop
            wait for C_CLK_PERIOD;
        end loop;
        Read(ManagerRec, STATUS_ADDR, read_data);
        check_equal(unsigned(read_data(16 downto 1)), to_unsigned(2**C_COUNT_W - 1, 16), "saturation");

        -- ── reset_count ───────────────────────────────────────────────────
        Write(ManagerRec, COMMAND_ADDR, x"00000001");
        wait for C_CLK_PERIOD;
        Write(ManagerRec, COMMAND_ADDR, x"00000000");
        Read(ManagerRec, STATUS_ADDR, read_data);
        check_equal(unsigned(read_data(16 downto 1)), to_unsigned(0, 16), "reset_count");

        -- ── disable ───────────────────────────────────────────────────────
        Write(ManagerRec, CONF_ADDR, x"00000003");  -- enable=1, increment=1
        for i in 1 to 4 loop
            wait for C_CLK_PERIOD;
        end loop;
        Read(ManagerRec, STATUS_ADDR, read_data);
        check_equal(unsigned(read_data(16 downto 1)), to_unsigned(4, 16), "disable: count before disable");

        Write(ManagerRec, CONF_ADDR, x"00000002");  -- enable=0, increment=1
        for i in 1 to 4 loop
            wait for C_CLK_PERIOD;
        end loop;
        Read(ManagerRec, STATUS_ADDR, read_data);
        check_equal(unsigned(read_data(16 downto 1)), to_unsigned(4, 16), "disable: count should hold");
        assert read_data(0) = '0' report "FAIL: enabled should be low when disabled" severity failure;

        report "PASS: all native VHDL tests completed" severity note;
        std.env.finish;
        wait;
    end process main;

    watchdog : process is
    begin
        wait for 1 ms;
        assert false report "FAIL: watchdog timeout" severity failure;
        std.env.finish;
    end process watchdog;

end architecture bench;
```

**Bit-packing verified, not guessed**: the register-value literals used above (e.g. `x"00000003"` = enable=1, increment=1; status readback bits `16 downto 1` = pulse_count, bit 0 = enabled) were checked directly against a real generated `demo_regs_pkg.vhd`: `demo_conf_enable : natural := 0` (bit 0), `demo_conf_increment : natural range 8 downto 1` (bits 1-8), `demo_status_enabled : natural := 0` (bit 0), `demo_status_pulse_count : natural range 16 downto 1` (bits 1-16) — matching exactly. This is specific to this project's *current* register map (`regs/NAME_regs.toml`); if that TOML is ever edited (field added/reordered/resized) before this task runs, regenerate `<name>_regs_pkg.vhd` and re-check these constants rather than assuming they still hold.

- [ ] **Step 2: Verify end-to-end in a scratch copy**

```bash
rm -rf /tmp/task7-verify
cp -r /Users/james/Workspace/hdl_template/.claude/worktrees/tb-top-axi-lite /tmp/task7-verify
cd /tmp/task7-verify
rm -rf .git out .venv
git init -q
bash scripts/init_project.sh demoproj vhdl
git add -A -- . ':!out'; git -c user.email=test@test.com -c user.name=test commit -q -m scratch
~/.pyenv/versions/3.13.3/bin/python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
make regs
make sim-native TOPLEVEL_HDL=vhdl
```

Expected: `PASS: all native VHDL tests completed`, exit 0. If NVC reports missing `osvvm`/`osvvm_axi4` libraries, run `nvc --install osvvm` first (this is a one-time, per-machine setup step, same category as installing NVC itself). Clean up: `rm -rf /tmp/task7-verify`.

- [ ] **Step 3: Commit**

```bash
git add tb/native/vhdl/NAME_tb.vhd
git commit -m "Port native VHDL testbench to target <<NAME>>_top via OSVVM's Axi4LiteManager"
```

---

### Task 8: Port the native-sv testbench to target `_top`

**Files:**
- Modify: `tb/native/sv/NAME_tb.sv`

**Interfaces:**
- Consumes: Task 6's `axi_lite_driver_pkg.sv` (`axil_write`/`axil_read` tasks).

- [ ] **Step 1: Rewrite `tb/native/sv/NAME_tb.sv`**

```systemverilog
// Native (framework-less) testbench for <<NAME>>_top, run directly via the
// simulator's --binary mode -- no cocotb dependency. Drives the design
// through its real AXI-Lite register interface (via the hand-rolled driver
// in axi_lite_driver_pkg.sv) rather than <<NAME>>_core's plain ports
// directly.
//
//   make sim-native TOPLEVEL_HDL=sv
//
// Test cases:
//   count_up    -- count increments on each pulse when enabled
//   saturation  -- counter saturates at (2**C_COUNT_W)-1
//   reset_count -- command.reset_count clears count in one cycle
//   disable     -- count holds when enable is deasserted
module <<NAME>>_tb;
    import <<NAME>>_pkg::*;
    import <<NAME>>_regs_addr_pkg::*;
    import axi_lite_driver_pkg::*;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic pulse_i = 1'b0;

    logic        s_axi_awvalid, s_axi_awready;
    logic [7:0]  s_axi_awaddr;
    logic        s_axi_wvalid, s_axi_wready;
    logic [31:0] s_axi_wdata;
    logic [3:0]  s_axi_wstrb;
    logic        s_axi_bvalid, s_axi_bready;
    logic [1:0]  s_axi_bresp;
    logic        s_axi_arvalid, s_axi_arready;
    logic [7:0]  s_axi_araddr;
    logic        s_axi_rvalid, s_axi_rready;
    logic [31:0] s_axi_rdata;
    logic [1:0]  s_axi_rresp;

    localparam time C_CLK_PERIOD = 10ns;
    always #(C_CLK_PERIOD / 2) clk = ~clk;

    // Register byte addresses from the generated <<NAME>>_regs_addr_pkg
    // (Task 2) rather than hand-typed literals -- tracks the register map
    // automatically if it's ever reordered.
    localparam logic [7:0] CONF_ADDR    = <<NAME>>_conf_addr;
    localparam logic [7:0] COMMAND_ADDR = <<NAME>>_command_addr;
    localparam logic [7:0] STATUS_ADDR  = <<NAME>>_status_addr;

    <<NAME>>_top u_dut (
        .clk(clk), .rst_n(rst_n), .pulse_i(pulse_i),
        .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready), .s_axi_awaddr(s_axi_awaddr),
        .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready), .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(s_axi_wstrb),
        .s_axi_bvalid(s_axi_bvalid), .s_axi_bready(s_axi_bready), .s_axi_bresp(s_axi_bresp),
        .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready), .s_axi_araddr(s_axi_araddr),
        .s_axi_rvalid(s_axi_rvalid), .s_axi_rready(s_axi_rready), .s_axi_rdata(s_axi_rdata), .s_axi_rresp(s_axi_rresp)
    );

    task automatic check_equal(int unsigned actual, int unsigned expected, string msg);
        if (actual !== expected) begin
            $error("FAIL: %s -- expected %0d got %0d", msg, expected, actual);
            $fatal(1);
        end
    endtask

    task automatic write_conf(bit enable, int unsigned increment);
        logic [31:0] value;
        value = {23'b0, increment[7:0], enable};
        axil_write(clk, s_axi_awvalid, s_axi_awready, s_axi_awaddr,
                   s_axi_wvalid, s_axi_wready, s_axi_wdata, s_axi_wstrb,
                   s_axi_bvalid, s_axi_bready, CONF_ADDR, value);
    endtask

    task automatic write_command_reset_count(bit asserted);
        axil_write(clk, s_axi_awvalid, s_axi_awready, s_axi_awaddr,
                   s_axi_wvalid, s_axi_wready, s_axi_wdata, s_axi_wstrb,
                   s_axi_bvalid, s_axi_bready, COMMAND_ADDR, {31'b0, asserted});
    endtask

    task automatic read_status(output bit enabled, output int unsigned pulse_count);
        logic [31:0] value;
        axil_read(clk, s_axi_arvalid, s_axi_arready, s_axi_araddr,
                  s_axi_rvalid, s_axi_rready, s_axi_rdata, STATUS_ADDR, value);
        enabled = value[0];
        pulse_count = value[16:1];
    endtask

    initial begin
        bit enabled;
        int unsigned pulse_count;

        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        // ── count_up ─────────────────────────────────────────────────────
        write_conf(1'b1, 1);
        for (int i = 1; i <= 8; i++) begin
            @(posedge clk);
            read_status(enabled, pulse_count);
            check_equal(pulse_count, i, "count_up");
        end
        read_status(enabled, pulse_count);
        if (enabled !== 1'b1) begin
            $error("FAIL: enabled should be high when counting");
            $fatal(1);
        end

        // ── saturation ───────────────────────────────────────────────────
        write_conf(1'b1, 255);
        for (int i = 1; i <= (2 ** C_COUNT_W - 1) / 255 + 2; i++) @(posedge clk);
        read_status(enabled, pulse_count);
        check_equal(pulse_count, (2 ** C_COUNT_W) - 1, "saturation");

        // ── reset_count ──────────────────────────────────────────────────
        write_command_reset_count(1'b1);
        @(posedge clk);
        write_command_reset_count(1'b0);
        read_status(enabled, pulse_count);
        check_equal(pulse_count, 0, "reset_count");

        // ── disable ──────────────────────────────────────────────────────
        write_conf(1'b1, 1);
        for (int i = 1; i <= 4; i++) @(posedge clk);
        read_status(enabled, pulse_count);
        check_equal(pulse_count, 4, "disable: count before disable");

        write_conf(1'b0, 1);
        for (int i = 1; i <= 4; i++) @(posedge clk);
        read_status(enabled, pulse_count);
        check_equal(pulse_count, 4, "disable: count should hold");
        if (enabled !== 1'b0) begin
            $error("FAIL: enabled should be low when disabled");
            $fatal(1);
        end

        $display("PASS: all native SystemVerilog tests completed");
        $finish;
    end

    initial begin
        #1ms;
        $error("FAIL: watchdog timeout");
        $fatal(1);
    end

endmodule : <<NAME>>_tb
```

**Before treating this as final**: same caveat as Task 7 — re-derive the exact `conf`/`status` bit-packing from the real generated register package rather than trusting `{23'b0, increment[7:0], enable}` blindly.

- [ ] **Step 2: Update `make sim-native`'s SV invocation to compile the new files**

Find `sim-native-sv` in the `Makefile`:

```makefile
sim-native-sv: regs ## Compile+run tb/native/sv/<<NAME>>_tb.sv directly with Verilator --binary (no framework)
	@printf "\n\033[1m  Running native SystemVerilog simulation (Verilator)...\033[0m\n\n"
	@mkdir -p $(NATIVE_RDIR)/verilator_obj
	@$(OSS_CAD_SUITE)/bin/verilator --binary --timing -Wall -Wno-fatal -j 0 \
	  -Mdir $(NATIVE_RDIR)/verilator_obj --top-module <<NAME>>_tb \
	  src/sv/<<NAME>>_pkg.sv src/sv/<<NAME>>_core.sv tb/native/sv/<<NAME>>_tb.sv
	@$(NATIVE_RDIR)/verilator_obj/V<<NAME>>_tb
	@printf "\n\033[32m  ✓\033[0m Native SystemVerilog simulation passed\n\n"
```

Change to compile `<<NAME>>_top.sv` (not `_core.sv`), the generated SV register file, and the new driver package:

```makefile
sim-native-sv: regs ## Compile+run tb/native/sv/<<NAME>>_tb.sv directly with Verilator --binary (no framework)
	@printf "\n\033[1m  Running native SystemVerilog simulation (Verilator)...\033[0m\n\n"
	@mkdir -p $(NATIVE_RDIR)/verilator_obj
	@$(OSS_CAD_SUITE)/bin/verilator --binary --timing -Wall -Wno-fatal -j 0 \
	  -Mdir $(NATIVE_RDIR)/verilator_obj --top-module <<NAME>>_tb \
	  tb/native/sv/axi_lite_driver_pkg.sv \
	  src/sv/<<NAME>>_pkg.sv \
	  $(SV_GEN) \
	  src/sv/<<NAME>>_core.sv src/sv/<<NAME>>_top.sv \
	  tb/native/sv/<<NAME>>_tb.sv
	@$(NATIVE_RDIR)/verilator_obj/V<<NAME>>_tb
	@printf "\n\033[32m  ✓\033[0m Native SystemVerilog simulation passed\n\n"
```

(`$(SV_GEN)` is the existing Makefile variable for the generated SV register file, already correctly ordered package-before-module — reuse it rather than hand-listing paths again.)

- [ ] **Step 3: Verify end-to-end in a scratch copy**

```bash
rm -rf /tmp/task8-verify
cp -r /Users/james/Workspace/hdl_template/.claude/worktrees/tb-top-axi-lite /tmp/task8-verify
cd /tmp/task8-verify
rm -rf .git out .venv
git init -q
bash scripts/init_project.sh demoproj sv
git add -A -- . ':!out'; git -c user.email=test@test.com -c user.name=test commit -q -m scratch
~/.pyenv/versions/3.13.3/bin/python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
make regs
make sim-native TOPLEVEL_HDL=sv
```

Expected: `PASS: all native SystemVerilog tests completed`, exit 0. Clean up: `rm -rf /tmp/task8-verify`.

- [ ] **Step 4: Commit**

```bash
git add tb/native/sv/NAME_tb.sv Makefile
git commit -m "Port native SystemVerilog testbench to target <<NAME>>_top via AXI-Lite"
```

---

### Task 9: Add the C++ testbench path

**Files:**
- Create: `tb/cpp/axi_lite_driver.hpp`
- Create: `tb/cpp/NAME_tb.cpp`
- Modify: `Makefile`

**Interfaces:** none produced (leaf testbench).

- [ ] **Step 1: Write `tb/cpp/axi_lite_driver.hpp`**

```cpp
// Hand-rolled AXI-Lite bus driver for Verilator C++ testbenches. No
// off-the-shelf AXI-Lite C++ VIP was targeted for this project -- a small
// hand-rolled driver operating directly on the Verilated model's port
// members is the conventional, idiomatic way to write a Verilator C++
// harness for a simple bus like this. Single-beat only, no bursts.
#pragma once

#include <cstdint>

// Template on the Verilated top-level type so this driver has zero
// dependency on any specific project's generated class name.
template <typename Top>
class AxiLiteDriver {
public:
    explicit AxiLiteDriver(Top* top) : top_(top) {}

    void write(uint8_t addr, uint32_t data) {
        top_->s_axi_awvalid = 1; top_->s_axi_awaddr = addr;
        top_->s_axi_wvalid  = 1; top_->s_axi_wdata  = data; top_->s_axi_wstrb = 0xF;
        top_->s_axi_bready  = 1;
        do { tick(); } while (!top_->s_axi_awready);
        top_->s_axi_awvalid = 0;
        while (!top_->s_axi_wready) { tick(); }
        top_->s_axi_wvalid = 0;
        while (!top_->s_axi_bvalid) { tick(); }
        top_->s_axi_bready = 0;
    }

    uint32_t read(uint8_t addr) {
        top_->s_axi_arvalid = 1; top_->s_axi_araddr = addr;
        top_->s_axi_rready  = 1;
        do { tick(); } while (!top_->s_axi_arready);
        top_->s_axi_arvalid = 0;
        while (!top_->s_axi_rvalid) { tick(); }
        uint32_t data = top_->s_axi_rdata;
        top_->s_axi_rready = 0;
        return data;
    }

    // Advance one clock cycle: caller supplies how, since the exact
    // eval()/time-advance sequence is test-harness-specific.
    std::function<void()> tick;

private:
    Top* top_;
};
```

Note: `tick` as a public `std::function<void()>` member (set by the test harness after construction) keeps this driver decoupled from the harness's own clock-generation strategy — the harness assigns it once, e.g. `driver.tick = [&]() { top->clk = 0; top->eval(); main_time++; top->clk = 1; top->eval(); main_time++; };`. Add `#include <functional>` alongside `<cstdint>`.

- [ ] **Step 2: Write `tb/cpp/NAME_tb.cpp`**

```cpp
// Verilator C++ testbench for <<NAME>>_top. Drives the design through its
// real AXI-Lite register interface via the hand-rolled driver in
// axi_lite_driver.hpp.
//
//   make sim-cpp TOPLEVEL_HDL=sv
//
// Test cases: count_up, saturation, reset_count, disable.
#include <cassert>
#include <cstddef>
#include <cstdio>
#include "V<<NAME>>_top.h"
#include "verilated.h"
#include "axi_lite_driver.hpp"
#include "<<NAME>>_regs.h"

static vluint64_t main_time = 0;
double sc_time_stamp() { return main_time; }

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    auto* top = new V<<NAME>>_top;

    AxiLiteDriver<V<<NAME>>_top> axil(top);
    axil.tick = [&]() {
        top->clk = 0; top->eval(); main_time++;
        top->clk = 1; top->eval(); main_time++;
    };

    // Byte addresses via offsetof() into the generated <<NAME>>_regs_t
    // struct, not the header's uppercase #define macros: <<NAME>>
    // template substitution is a literal, case-preserving text
    // replacement, and the struct's type name and field names (conf,
    // command, status) are lowercase/un-prefixed and so are safely
    // substitutable, unlike e.g. <<NAME>>_CONF_ADDR (which pre-init reads
    // as literal NAME_CONF_ADDR, wrong case relative to what
    // hdl_registers' .upper() convention actually generates post-init).
    const uint8_t CONF_ADDR = offsetof(<<NAME>>_regs_t, conf);
    const uint8_t COMMAND_ADDR = offsetof(<<NAME>>_regs_t, command);
    const uint8_t STATUS_ADDR = offsetof(<<NAME>>_regs_t, status);

    top->rst_n = 0;
    top->pulse_i = 0;
    for (int i = 0; i < 5; i++) axil.tick();
    top->rst_n = 1;
    axil.tick();

    // ── count_up ─────────────────────────────────────────────────────────
    axil.write(CONF_ADDR, 0x00000003);  // enable=1, increment=1
    for (int i = 1; i <= 8; i++) {
        axil.tick();
        uint32_t status = axil.read(STATUS_ADDR);
        uint32_t pulse_count = (status >> 1) & 0xFFFF;
        if (pulse_count != (uint32_t)i) {
            fprintf(stderr, "FAIL: count_up expected %d got %u\n", i, pulse_count);
            return 1;
        }
    }
    if (!(axil.read(STATUS_ADDR) & 0x1)) {
        fprintf(stderr, "FAIL: enabled should be high when counting\n");
        return 1;
    }

    // ── saturation ───────────────────────────────────────────────────────
    axil.write(CONF_ADDR, 0x000001FF);  // enable=1, increment=255
    int cycles = ((1 << 16) - 1) / 255 + 4;
    for (int i = 0; i < cycles; i++) axil.tick();
    uint32_t pulse_count = (axil.read(STATUS_ADDR) >> 1) & 0xFFFF;
    if (pulse_count != 0xFFFF) {
        fprintf(stderr, "FAIL: saturation expected 65535 got %u\n", pulse_count);
        return 1;
    }

    // ── reset_count ──────────────────────────────────────────────────────
    axil.write(COMMAND_ADDR, 0x00000001);
    axil.tick();
    axil.write(COMMAND_ADDR, 0x00000000);
    pulse_count = (axil.read(STATUS_ADDR) >> 1) & 0xFFFF;
    if (pulse_count != 0) {
        fprintf(stderr, "FAIL: reset_count expected 0 got %u\n", pulse_count);
        return 1;
    }

    // ── disable ──────────────────────────────────────────────────────────
    axil.write(CONF_ADDR, 0x00000003);  // enable=1, increment=1
    for (int i = 0; i < 4; i++) axil.tick();
    pulse_count = (axil.read(STATUS_ADDR) >> 1) & 0xFFFF;
    if (pulse_count != 4) {
        fprintf(stderr, "FAIL: disable pre-check expected 4 got %u\n", pulse_count);
        return 1;
    }
    axil.write(CONF_ADDR, 0x00000002);  // enable=0, increment=1
    for (int i = 0; i < 4; i++) axil.tick();
    uint32_t status = axil.read(STATUS_ADDR);
    pulse_count = (status >> 1) & 0xFFFF;
    if (pulse_count != 4 || (status & 0x1)) {
        fprintf(stderr, "FAIL: disable post-check count=%u enabled=%u\n", pulse_count, status & 0x1);
        return 1;
    }

    printf("PASS: all C++ tests completed\n");
    delete top;
    return 0;
}
```

**Register-value bit-packing verified, not guessed** (addressing itself is safe via `offsetof()` regardless): the literal values written (`0x00000003` = enable=1,increment=1; status bits `[16:1]`=pulse_count, bit 0=enabled) were checked against the real generated `demo_regs_pkg.vhd`'s field-position constants, same as Task 7 — see that task's note for the exact constants checked. Specific to the current `regs/NAME_regs.toml`; re-verify if that TOML changes before this task runs.

- [ ] **Step 3: Add the `sim-cpp` Makefile target**

Add near `sim-native-sv` in the `Makefile`:

```makefile
sim-cpp: regs ## Compile+run tb/cpp/<<NAME>>_tb.cpp directly with Verilator --cc --exe --build (SV only)
ifneq ($(TOPLEVEL_HDL),sv)
	$(error sim-cpp requires TOPLEVEL_HDL=sv -- Verilator does not read VHDL)
endif
	@printf "\n\033[1m  Running C++ testbench (Verilator --cc --exe --build)...\033[0m\n\n"
	@mkdir -p $(NATIVE_RDIR)/cpp_obj
	@$(OSS_CAD_SUITE)/bin/verilator --cc --exe --build -Wall -Wno-fatal -j 0 \
	  -Mdir $(NATIVE_RDIR)/cpp_obj --top-module <<NAME>>_top \
	  src/sv/<<NAME>>_pkg.sv \
	  $(SV_GEN) \
	  src/sv/<<NAME>>_core.sv src/sv/<<NAME>>_top.sv \
	  tb/cpp/<<NAME>>_tb.cpp \
	  -CFLAGS "-Itb/cpp -Iout/regs/c" \
	  -o <<NAME>>_tb_cpp
	@$(NATIVE_RDIR)/cpp_obj/<<NAME>>_tb_cpp
	@printf "\n\033[32m  ✓\033[0m C++ testbench passed\n\n"
```

- [ ] **Step 4: Verify end-to-end in a scratch copy**

```bash
rm -rf /tmp/task9-verify
cp -r /Users/james/Workspace/hdl_template/.claude/worktrees/tb-top-axi-lite /tmp/task9-verify
cd /tmp/task9-verify
rm -rf .git out .venv
git init -q
bash scripts/init_project.sh demoproj sv
git add -A -- . ':!out'; git -c user.email=test@test.com -c user.name=test commit -q -m scratch
~/.pyenv/versions/3.13.3/bin/python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
make regs
make sim-cpp TOPLEVEL_HDL=sv
```

Expected: `PASS: all C++ tests completed`, exit 0. Also confirm the VHDL guard works: `make sim-cpp TOPLEVEL_HDL=vhdl` should fail with the `$(error ...)` message, not attempt to run Verilator against VHDL. Clean up: `rm -rf /tmp/task9-verify`.

- [ ] **Step 5: Commit**

```bash
git add tb/cpp/ Makefile
git commit -m "Add C++ testbench path (Verilator --cc --exe --build) targeting <<NAME>>_top"
```

---

### Task 10: Update `scripts/smoke_test.sh` and CI

**Files:**
- Modify: `scripts/smoke_test.sh`
- Modify: `.github/workflows/ci.yml`

**Interfaces:** none produced.

- [ ] **Step 1: Add the OSVVM install step to `smoke_test.sh`**

Read the current file first (it was last touched by this session's earlier work adding `xfail_step` then removing it — confirm current exact shape). Add, before the VHDL row's `sim-native` step:

```bash
    step "$lang" "install-osvvm" nvc --install osvvm
```

Only for the VHDL row (`if [[ "$lang" == vhdl ]]; then` branch) — SV doesn't need it. Placement: immediately before `step "$lang" "sim-native" make sim-native TOPLEVEL_HDL=vhdl`.

- [ ] **Step 2: Add the `sim-cpp` step to `smoke_test.sh`'s SV row**

In the SV (`else`) branch, add after `sim-cocotb-verilator`:

```bash
        step "$lang" "sim-cpp"              make sim-cpp TOPLEVEL_HDL=sv
```

- [ ] **Step 3: Update `.github/workflows/ci.yml`'s `smoke-test` job**

Find the `smoke-test` job's "Install NVC" step and add an OSVVM install immediately after it:

```yaml
      - name: Install NVC
        run: |
          curl -sSL -o nvc.deb https://github.com/nickg/nvc/releases/download/r1.22.1/nvc_1.22.1-1_amd64_ubuntu-24.04.deb
          sudo apt-get install -y ./nvc.deb

      - name: Install OSVVM
        run: nvc --install osvvm
```

- [ ] **Step 4: Verify `nvc --install osvvm` succeeds locally (idempotent, safe to re-run)**

```bash
nvc --install osvvm
nvc --list 2>&1 | grep -i osvvm
```

Expected: OSVVM libraries listed (`osvvm`, `osvvm_axi4`, etc.), no error. This step doesn't need a scratch copy — it's a machine-global NVC library install, matching how NVC itself is installed once per machine.

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_test.sh .github/workflows/ci.yml
git commit -m "Wire OSVVM install and sim-cpp into smoke_test.sh and CI"
```

---

### Task 11: Update documentation

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Interfaces:** none produced.

- [ ] **Step 1: Update `CLAUDE.md`'s "Simulator / Framework Routing" table**

Find:

```markdown
| `FRAMEWORK` | `SIM`      | `TOPLEVEL_HDL` | Mechanism             |
|-------------|------------|----------------|-----------------------|
| `vunit`     | ghdl       | vhdl           | VUnit → GHDL via VHPI |
| `cocotb`    | ghdl       | vhdl           | cocotb → GHDL via VHPI|
| `cocotb`    | verilator  | sv             | cocotb → Verilator VPI|
| `cocotb`    | icarus     | sv             | cocotb → iverilog VPI |

The `tb/cocotb/Makefile` enforces valid combinations with an error guard.

`make sim-native TOPLEVEL_HDL=vhdl|sv` is a separate, framework-less path — it compiles and runs `tb/native/vhdl/NAME_tb.vhd` directly with NVC, or `tb/native/sv/NAME_tb.sv` directly with `verilator --binary --timing`, with no VUnit/cocotb dependency. Both testbenches target `<<NAME>>_core` directly (not `_top`), matching the VUnit and cocotb testbenches, so the AXI-Lite register block and `hdl-modules` are not involved.
```

Replace with:

```markdown
| `FRAMEWORK` | `SIM`      | `TOPLEVEL_HDL` | Mechanism             |
|-------------|------------|----------------|-----------------------|
| `vunit`     | ghdl       | vhdl           | VUnit → GHDL via VHPI |
| `cocotb`    | ghdl       | vhdl           | cocotb → GHDL via VHPI|
| `cocotb`    | verilator  | sv             | cocotb → Verilator VPI|
| `cocotb`    | icarus     | sv             | cocotb → iverilog VPI |

The `tb/cocotb/Makefile` enforces valid combinations with an error guard.

Every testbench above targets `<<NAME>>_top` (not `_core`), driving it over its real AXI-Lite register interface: VUnit uses `hdl_registers`' generated read/write package plus `hdl-modules`' `axi_lite_master` BFM; cocotb (both languages) uses `cocotbext-axi`'s `AxiLiteMaster`.

`make sim-native TOPLEVEL_HDL=vhdl|sv` is a separate, framework-less path — it compiles and runs `tb/native/vhdl/NAME_tb.vhd` directly with NVC (using OSVVM's `Axi4LiteManager` — install once via `nvc --install osvvm`), or `tb/native/sv/NAME_tb.sv` directly with `verilator --binary --timing` (using a small hand-rolled AXI-Lite driver, `tb/native/sv/axi_lite_driver_pkg.sv` — no off-the-shelf, non-UVM, Verilator-compatible SV BFM exists). Both also target `<<NAME>>_top`.

`make sim-cpp TOPLEVEL_HDL=sv` compiles and runs `tb/cpp/<<NAME>>_tb.cpp` via `verilator --cc --exe --build`, using a small hand-rolled AXI-Lite driver (`tb/cpp/axi_lite_driver.hpp`) — the conventional way to write a Verilator C++ harness for a bus this simple. SV-only; Verilator doesn't read VHDL.
```

- [ ] **Step 2: Update `README.md`'s Make targets table**

Add a row near `sim-native`:

```
make sim-cpp         Run the C++ testbench directly with Verilator --cc --exe --build [TOPLEVEL_HDL=sv only]
```

- [ ] **Step 3: Document `nvc --install osvvm`**

In `README.md`'s Tool Requirements table, add a row (or extend the NVC row):

```
| [NVC](https://www.nickg.me.uk/nvc/) | `make sim-native TOPLEVEL_HDL=vhdl` | `brew install nvc` / [releases](https://github.com/nickg/nvc/releases) — not part of OSS CAD Suite; also run `nvc --install osvvm` once, needed by the native VHDL testbench |
```

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "Document testbenches-target-_top change, OSVVM setup, and sim-cpp"
```

---

### Task 12: Full end-to-end verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full pytest suite**

```bash
.venv/bin/python3 -m pytest -q
```

Expected: all tests pass (35 in `scripts/tests/` after Task 2's additions, plus whatever else `pytest.ini` discovers).

- [ ] **Step 2: Run the full smoke test for both languages**

```bash
scripts/smoke_test.sh
```

Expected: every step passes for both `vhdl` and `sv` rows, including the new `install-osvvm` and `sim-cpp` steps, except the already-documented, unrelated pre-existing environment gaps (`sim-cocotb-ghdl`/`sim-cocotb-verilator`: `libintl.8.dylib`; `html`: `libxcb.dylib`/SV-excluded-from-docs — see `CLAUDE.md`'s "Known macOS gap" notes) and `sv synth`'s already-resolved status (should now PASS, per the earlier SV-synthesizability fix — if it doesn't, that's a real regression to investigate, not an expected gap).

- [ ] **Step 3: Confirm `make init` handles the new C++ files correctly, for real, in the full pipeline**

```bash
KEEP=1 scripts/smoke_test.sh sv
```

Find the kept temp dir path printed at the end, then:

```bash
ls "$KEPT_DIR/sv/tb/cpp/"
```

Expected: `<name>_tb.cpp` (properly renamed and de-templated), `axi_lite_driver.hpp` (unchanged, since it has no `<<NAME>>` content). Clean up the kept temp dir afterward.

- [ ] **Step 4: Final commit (if Steps 1-3 required any fixes)**

```bash
git add -A
git commit -m "Fix issues found during end-to-end testbenches-target-_top verification"
```

If no fixes were needed, skip this step.
