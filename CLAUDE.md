# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open-source HDL project template supporting both VHDL and SystemVerilog. All workflows are driven through `make`. The template uses `<<NAME>>` as a placeholder that gets replaced by `make init NAME=<project>`.

## Toolchain

All HDL tools (GHDL, Yosys, Verilator, Icarus, nextpnr) are expected to come from **OSS CAD Suite**, installed at `~/tools/oss-cad-suite` by default. Override with `make <target> OSS_CAD_SUITE=/path/to/oss-cad-suite`.

**NVC** (VHDL simulator) is a separate dependency, used only by `make sim-native TOPLEVEL_HDL=vhdl` — it's not bundled in OSS CAD Suite. Install via `brew install nvc` or see https://www.nickg.me.uk/nvc/. Override with `make sim-native NVC=/path/to/nvc`.

**Known macOS gap**: `make html`/`make pdf`/`make coverage` can crash on import with `OSError: cannot load library 'libxcb.dylib'`. This is `sphinxcontrib.wavedrom` unconditionally importing `cairosvg` → `cairocffi` → `xcffib` at module-import time — `xcffib` needs `libxcb.dylib` resolvable via `cffi`'s `dlopen()`, which behaves differently from `ctypes.util.find_library()` and isn't satisfied by `brew install cairo` alone (`DYLD_LIBRARY_PATH=/opt/homebrew/lib` fixes `find_library()` but not the `make`-spawned Sphinx subprocess, likely SIP stripping `DYLD_*`). This triggers regardless of whether the project actually uses any `.. wavedrom::` directive or `SCHEMATICS=1`. Third-party packaging issue (`xcffib`/`cairocffi` on macOS), not fixable by editing this repo. Untested whether Linux CI hits the same gap.

**Pre-existing SV doc-coverage gap**: `make html`/`make coverage` for a SystemVerilog project (`TOPLEVEL_HDL=sv`) fail at the `hierarchy` step with `IndexError: list index out of range` in `parse_hierarchy.py`'s `build_hierarchy()`, before ever reaching the macOS gap above. Root cause: `scripts/gen_filelist.sh` intentionally excludes SV sources from the doc filelist ("SV files are alternate simulation targets, not doc targets" — see the script's own trailing comment), so `filelist.f` has zero source files for an SV project and `parse_hierarchy.py` crashes on an empty module list instead of failing gracefully. This predates the testbenches-target-`_top` migration (confirmed via `git log -- scripts/gen_filelist.sh`, last touched by pre-migration commits) and is unrelated to it — HDL AutoDoc's Sphinx pipeline simply doesn't support SV projects yet. `make synth`/`make impl` and all SV simulation flows (including `sim-cpp`) are unaffected, since they don't go through `parse_hierarchy.py`.

**SV register-file synthesizability**: `hdl_registers`' SystemVerilog generator delegates to PeakRDL-regblock, which unconditionally emits **unpacked** SV structs for its `hwif_in`/`hwif_out` types and `automatic` locals inside `always_comb` blocks — neither supported by free/OSS Yosys's native `read_verilog -sv` frontend (`"Only PACKED supported at this time"` / `"unexpected TOK_AUTOMATIC"`), which would otherwise break `make synth TOPLEVEL_HDL=sv`/`make impl TOPLEVEL_HDL=sv` for any project using the register auto-wiring feature. `generate_sv()` in `scripts/gen_regs.py` (`_make_sv_synthesizable`) post-processes both generated files to work around this — packing every struct level (verified safe: no code anywhere bit-slices a struct as a flat vector) and stripping `automatic` (verified safe: these blocks never recurse or run concurrently) — verified via a full `synth` run producing a clean netlist, with no change in behavior for Verilator-based flows (`lint-sv`, `sim-cocotb-verilator`, `sim-native`). **Residual gap**: `make sim FRAMEWORK=cocotb SIM=icarus TOPLEVEL_HDL=sv` was found to *already* fail on PeakRDL-regblock's unmodified output for the same two reasons (Icarus independently rejects both constructs) — a gap `scripts/smoke_test.sh` doesn't catch since its SV cocotb row only exercises `SIM=verilator`. The post-processing fix downgrades this from a hard compile failure to compiling with `"sorry: constant selects in always_* processes are not currently supported (all bits will be included)"` warnings — plausibly benign, since nothing here depends on partial-bit-select semantics inside those blocks, but not independently verified for simulation fidelity the way the Yosys/Verilator paths were. Untested with Icarus-based cocotb SV runs.

## Initial Setup (one-time)

```bash
git submodule update --init --recursive         # Fetch the HDLAutoDoc submodule (needed for make html/pdf/test-autodoc)
make init NAME=<project_name>                    # VHDL project (default)
make init NAME=<project_name> TOPLEVEL_HDL=sv   # SystemVerilog project
make venv                        # Create .venv/ and install Python dependencies
make deps                        # Fetch HDL dependencies via Bender (bender update)
make regs                        # Generate VHDL/C/HTML from regs/<name>_regs.toml
```

Cloning fresh? Use `git clone --recurse-submodules <url>` to skip the separate submodule step above.

## Common Commands

```bash
# Simulation
make sim                                              # VUnit + GHDL (VHDL, default)
make sim FRAMEWORK=cocotb SIM=ghdl TOPLEVEL_HDL=vhdl # cocotb + GHDL (VHDL)
make sim FRAMEWORK=cocotb SIM=verilator TOPLEVEL_HDL=sv  # cocotb + Verilator (SV)
make sim FRAMEWORK=cocotb SIM=icarus   TOPLEVEL_HDL=sv   # cocotb + Icarus (SV)
make sim-native TOPLEVEL_HDL=vhdl                         # Native VHDL via NVC, no framework
make sim-native TOPLEVEL_HDL=sv                           # Native SV via Verilator --binary, no framework

# Single VUnit test
VUNIT_SIMULATOR=ghdl .venv/bin/python tb/vunit/run.py -v "tb_lib.NAME_tb.test_count_up"

# Synthesis
make synth                  # VHDL via ghdl-yosys-plugin → Xilinx 7-series
make synth TOPLEVEL_HDL=sv  # SV via native Yosys
make synth-gui              # Open Yosys schematic viewer after synthesis

# Implementation (place-and-route via nextpnr)
make impl                   # Synth + PnR → bitstream  [IMPL_FAMILY=ice40|ecp5|machxo2]
make impl-gui               # Open nextpnr interactive GUI
make icestudio              # Run impl then open IceStudio for programming
# Key impl variables: IMPL_FAMILY (ice40), IMPL_DEVICE (hx8k), IMPL_PACKAGE (ct256)
# IMPL_TOPLEVEL (NAME_core), IMPL_CONSTRAINT (synth/constraints/<toplevel>.pcf)

# Documentation
make html                   # Build Sphinx docs (requires make regs first)
make html SCHEMATICS=1      # Include RTL schematics (requires yosys + ghdl-yosys-plugin)
make pdf                    # Build LaTeX PDF documentation
make doc                    # Build both HTML and PDF

# Simulation (additional)
make sim-vunit-gui          # VUnit + GHDL with waveform viewer

# Linting
make lint                   # All linters
make lint-vhdl              # GHDL analysis + vsg style guide
make lint-sv                # Verilator --lint-only -Wall

# Register generation
make regs                   # Generate from all regs/*.toml

# Tests
make test-autodoc           # hdl_autodoc Python unit tests (pytest)

# Dependency management
make deps                   # bender update (resolved via `bender path <name>`, not vendored)
make install                # Upgrade Python dependencies in active venv

# Diagnostics
make vars                   # Print all current Makefile variable values

# Clean
make clean                  # Remove out/docs/, sim artefacts
make clean-generated        # Also remove out/regs/, out/synth/, out/impl/, filelist.f
make clean-all              # Full reset including .venv/
```

## Architecture

### 3-Module HDL Hierarchy

Every project using this template follows this structure:

```
<<NAME>>_top     — top-level wrapper: AXI4-Lite ports + instantiates core and regs
  <<NAME>>_core  — pure RTL logic; no register bus; takes decoded register signals
  <<NAME>>_regs  — GENERATED by make regs; never hand-written
```

`<<NAME>>_top.vhd` wires `regs_down` (host → core) and `regs_up` (core → host status) using typed records from the generated `<<NAME>>_register_record_pkg.vhd`.

### Source Layout

```
src/vhdl/        VHDL RTL (NAME_pkg.vhd, NAME_core.vhd, NAME_top.vhd)
src/sv/          SystemVerilog RTL (same structure, identical port names)
regs/            TOML register definitions (source of truth)
out/             GENERATED outputs (gitignored)
  out/regs/vhdl/ VHDL register packages + AXI-Lite wrapper
  out/regs/sv/   SV register file + address-constants package (SV projects only)
  out/regs/c/    C header files
  out/regs/html/ HTML register documentation
tb/vunit/        VUnit runner (run.py) + VHDL testbenches
tb/cocotb/       cocotb Makefile + Python test modules
  tb/cocotb/vhdl/  GHDL-only flattening wrapper (see Simulator / Framework Routing above)
tb/native/       Framework-less testbenches (tb/native/vhdl, tb/native/sv) run directly by NVC / Verilator
tb/cpp/          Framework-less C++ testbench + hand-rolled AXI-Lite driver, run directly by Verilator --cc --exe --build
synth/           Yosys synthesis scripts (.ys) + XDC constraints
scripts/
  hdl_autodoc/   HDL AutoDoc extraction pipeline (unchanged from HDLAutoDoc)
  gen_regs.py    Register generation driver (uses hdl_registers)
  gen_filelist.sh Bender → filelist.f for hdl_autodoc
  init_project.sh Template initialisation (replaces <<NAME>>)
docs/            Sphinx documentation source (RST shells + conf.py)
```

### Dependency Management

**Bender** (`Bender.yml`) is the primary source of truth for all HDL file lists. `Bender.lock` is committed for reproducible builds. The Makefile calls `bender script flist -t <target>` to get ordered file lists:
- `rtl_vhdl` — VHDL RTL sources
- `rtl_sv` — SV RTL sources
- `gen_vhdl` — generated VHDL register files
- `tb_vhdl` — testbench VHDL (simulation only)

**FuseSoC** (`template.core`) is a secondary manifest kept in sync with `Bender.yml` for ecosystem compatibility.

`hdl_modules` (declared under `dependencies:`) has no `Bender.yml` of its own — Bender still checks it out via `bender update` and resolves it with `bender path hdl_modules`, which the Makefile uses to locate `axi_lite_pkg.vhd`/`register_file_pkg.vhd` for GHDL library compilation (`HDL_MODULES`/`VHDL_AXI_LITE`/`VHDL_REG_FILE` in the Makefile). There is no `deps/` vendoring step — `make deps` is just `bender update`; the checkout lives in Bender's own `.bender/` cache (gitignored).

### Simulator / Framework Routing

| `FRAMEWORK` | `SIM`      | `TOPLEVEL_HDL` | Mechanism             |
|-------------|------------|----------------|-----------------------|
| `vunit`     | ghdl       | vhdl           | VUnit → GHDL via VHPI |
| `cocotb`    | ghdl       | vhdl           | cocotb → GHDL via VPI |
| `cocotb`    | verilator  | sv             | cocotb → Verilator VPI|
| `cocotb`    | icarus     | sv             | cocotb → iverilog VPI |

The `tb/cocotb/Makefile` enforces valid combinations with an error guard.

The `cocotb`/`ghdl`/`vhdl` row targets a thin wrapper entity,
`tb/cocotb/vhdl/<<NAME>>_cocotb_top.vhd`, not `<<NAME>>_top` directly:
GHDL's VPI backend cannot expose VHDL record-typed ports (used by
`<<NAME>>_top`'s AXI-Lite `s_axi_m2s`/`s_axi_s2m` ports) to cocotb at
all, so the wrapper flattens them into flat signals (matching the SV
side's native naming) around an unmodified `<<NAME>>_top` instance.
`<<NAME>>_top.vhd` itself is untouched; the SV path needs no such
wrapper since its ports are already flat.

Every testbench above targets `<<NAME>>_top` (not `_core`), driving it over its real AXI-Lite register interface: VUnit uses `hdl_registers`' generated read/write package plus `hdl-modules`' `axi_lite_master` BFM; cocotb (both languages) uses `cocotbext-axi`'s `AxiLiteMaster`.

`make sim-native TOPLEVEL_HDL=vhdl|sv` is a separate, framework-less path — it compiles and runs `tb/native/vhdl/NAME_tb.vhd` directly with NVC (using OSVVM's `Axi4LiteManager` — install once via `nvc --install osvvm`), or `tb/native/sv/NAME_tb.sv` directly with `verilator --binary --timing` (using a small hand-rolled AXI-Lite driver, `tb/native/sv/axi_lite_driver_pkg.sv` — no off-the-shelf, non-UVM, Verilator-compatible SV BFM exists). Both also target `<<NAME>>_top`.

`make sim-cpp TOPLEVEL_HDL=sv` compiles and runs `tb/cpp/<<NAME>>_tb.cpp` via `verilator --cc --exe --build`, using a small hand-rolled AXI-Lite driver (`tb/cpp/axi_lite_driver.hpp`) — the conventional way to write a Verilator C++ harness for a bus this simple. SV-only; Verilator doesn't read VHDL.

### Register Generation

Register definitions live in `regs/<name>_regs.toml` using the `hdl_registers` TOML format. Running `make regs` calls `scripts/gen_regs.py` which generates:
- `out/regs/vhdl/<name>_regs_pkg.vhd` — address/field constants
- `out/regs/vhdl/<name>_register_record_pkg.vhd` — typed VHDL records
- `out/regs/vhdl/<name>_register_file_axi_lite.vhd` — AXI-Lite register entity (this is `<<NAME>>_regs`)
- `out/regs/vhdl/<name>_register_read_write_pkg.vhd` — VUnit-only simulation read/write procedures, used by `tb/vunit/vhdl/<name>_tb.vhd` to drive registers over `net`/`bus_handle` message passing instead of raw signal manipulation
- `out/regs/c/<name>_regs.h` — C header for embedded drivers
- `out/regs/html/<name>_regs.html` — register documentation

The generated AXI-Lite entity requires the `hdl-modules` library (fetched via `make deps`).

For SystemVerilog projects, `make regs` instead generates `out/regs/sv/<name>_register_file_axi_lite.sv` and `out/regs/sv/<name>_register_file_axi_lite_pkg.sv` via PeakRDL-regblock (through `hdl_registers`' SystemVerilog generator, `flatten_axi_lite=True`), plus `out/regs/sv/<name>_regs_addr_pkg.sv` — a small lowercase-named localparam package (one per register's byte address) consumed by `tb/native/sv/<name>_tb.sv`, since `<<NAME>>` template substitution can't produce the C header's uppercase macro names pre-init.

`make regs` also auto-wires each register field to a matching `<name>_core` port, rewriting only the marker-delimited region(s) inside `<name>_top` (VHDL: `-- BEGIN/END AUTOGEN REGISTER SIGNALS` plus `-- BEGIN/END AUTOGEN REGISTERS`; SV: `// BEGIN/END AUTOGEN REGISTERS`). Field leaf names must be unique across the whole register map (each resolves to a distinct `<name>_core` port) — see the "SV register-file synthesizability" note above for the residual Icarus gap this introduces.

### Documentation Pipeline

The HDL AutoDoc scripts themselves live in the `submodules/HDLAutoDoc` git submodule (not vendored into `scripts/`) — `AUTODOC_SCRIPTDIR` in the Makefile points there directly, so updates come from `git submodule update --remote`. `docs/conf.py`, `docs/_static/`, and `docs/_templates/` are project-owned copies (not referenced from the submodule), since they carry local customisations — see the note in `docs/conf.py` before syncing theme/template changes from upstream.

The `make html` target runs the full HDL AutoDoc + Sphinx pipeline:
1. `make filelist` — generates `filelist.f` from Bender
2. `parse_hierarchy.py` — discovers module relationships
3. `generate_rst.py` — creates RST shells
4. `run_extract.py` — extracts FSMs, block diagrams, CDC, reset domains, processes
5. `include_registers.py` — links generated HTML register docs into Sphinx
6. `sphinx-build` — builds final HTML

WaveDrom timing diagrams are embedded in VHDL process comments using `.. wavedrom::` directives.

### Template Initialisation

`make init NAME=<name> TOPLEVEL_HDL=vhdl|sv` (default: `vhdl`):
1. Moves `src/<hdl>/` files to `src/`, removes both `src/vhdl/` and `src/sv/`, and normalises `src/vhdl/` / `src/sv/` path references to `src/` across all config and doc files.
2. Replaces all `<<NAME>>` in file contents with `<name>`.
3. Renames all `NAME_*.ext` files to `<name>_*.ext`.

After `make init`, `src/` is flat (no language subdirectories), `<<NAME>>` and `NAME_` patterns are gone, and both Bender targets (`rtl_vhdl`, `rtl_sv`) reference `src/` — only the chosen language's files will exist there.

## Key Files

- `Makefile` — all targets; read the `## help` comments for documentation
- `Bender.yml` — HDL source lists and external dependencies
- `regs/NAME_regs.toml` — register definitions (post-init: `<name>_regs.toml`)
- `scripts/gen_regs.py` — register generation driver
- `scripts/init_project.sh` — project initialisation
- `docs/conf.py` — Sphinx configuration (project name, extensions, theme)
- `submodules/HDLAutoDoc` — git submodule; source of the HDL AutoDoc extraction/generation scripts (`scripts/gen_regs.py` and `docs/` remain project-owned)
- `vsg.yml` — VHDL Style Guide linter rules
- `.github/workflows/ci.yml` — CI matrix (lint, sim×4, synth, test-autodoc); includes a `regs` job that regenerates and diffs register files to catch uncommitted drift, and a `smoke-test` job (vhdl/sv matrix) that runs `scripts/smoke_test.sh` — the only job that exercises the Makefile *after* `make init`, which is the state real users actually build against
- `scripts/smoke_test.sh` — copies the working tree into an isolated temp dir per language, runs `make init`, then walks `regs`/`lsp`/`lint`/every testbench flow/`synth`/`html`/`coverage`. Runs every step regardless of earlier failures and prints a full pass/fail summary (`scripts/smoke_test.sh [vhdl|sv]`, `KEEP=1` to keep the temp dirs)
- `.github/workflows/docs.yml` — Sphinx → GitHub Pages deployment (main branch only)
- `.python-version` — pins Python 3.13 for venv and CI
