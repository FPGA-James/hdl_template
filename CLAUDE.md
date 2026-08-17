# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open-source HDL project template supporting both VHDL and SystemVerilog. All workflows are driven through `make`. The template uses `<<NAME>>` as a placeholder that gets replaced by `make init NAME=<project>`.

## Toolchain

All HDL tools (GHDL, Yosys, Verilator, Icarus, nextpnr) are expected to come from **OSS CAD Suite**, installed at `~/tools/oss-cad-suite` by default. Override with `make <target> OSS_CAD_SUITE=/path/to/oss-cad-suite`.

**NVC** (VHDL simulator) is a separate dependency, used only by `make sim-native TOPLEVEL_HDL=vhdl` — it's not bundled in OSS CAD Suite. Install via `brew install nvc` or see https://www.nickg.me.uk/nvc/. Override with `make sim-native NVC=/path/to/nvc`.

**Known macOS gap**: `make html`/`make pdf`/`make coverage` can crash on import with `OSError: cannot load library 'libxcb.dylib'`. This is `sphinxcontrib.wavedrom` unconditionally importing `cairosvg` → `cairocffi` → `xcffib` at module-import time — `xcffib` needs `libxcb.dylib` resolvable via `cffi`'s `dlopen()`, which behaves differently from `ctypes.util.find_library()` and isn't satisfied by `brew install cairo` alone (`DYLD_LIBRARY_PATH=/opt/homebrew/lib` fixes `find_library()` but not the `make`-spawned Sphinx subprocess, likely SIP stripping `DYLD_*`). This triggers regardless of whether the project actually uses any `.. wavedrom::` directive or `SCHEMATICS=1`. Third-party packaging issue (`xcffib`/`cairocffi` on macOS), not fixable by editing this repo. Untested whether Linux CI hits the same gap.

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
  out/regs/c/    C header files
  out/regs/html/ HTML register documentation
tb/vunit/        VUnit runner (run.py) + VHDL testbenches
tb/cocotb/       cocotb Makefile + Python test modules
tb/native/       Framework-less testbenches (tb/native/vhdl, tb/native/sv) run directly by NVC / Verilator
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
| `cocotb`    | ghdl       | vhdl           | cocotb → GHDL via VHPI|
| `cocotb`    | verilator  | sv             | cocotb → Verilator VPI|
| `cocotb`    | icarus     | sv             | cocotb → iverilog VPI |

The `tb/cocotb/Makefile` enforces valid combinations with an error guard.

`make sim-native TOPLEVEL_HDL=vhdl|sv` is a separate, framework-less path — it compiles and runs `tb/native/vhdl/NAME_tb.vhd` directly with NVC, or `tb/native/sv/NAME_tb.sv` directly with `verilator --binary --timing`, with no VUnit/cocotb dependency. Both testbenches target `<<NAME>>_core` directly (not `_top`), matching the VUnit and cocotb testbenches, so the AXI-Lite register block and `hdl-modules` are not involved.

### Register Generation

Register definitions live in `regs/<name>_regs.toml` using the `hdl_registers` TOML format. Running `make regs` calls `scripts/gen_regs.py` which generates:
- `out/regs/vhdl/<name>_regs_pkg.vhd` — address/field constants
- `out/regs/vhdl/<name>_register_record_pkg.vhd` — typed VHDL records
- `out/regs/vhdl/<name>_register_file_axi_lite.vhd` — AXI-Lite register entity (this is `<<NAME>>_regs`)
- `out/regs/c/<name>_regs.h` — C header for embedded drivers
- `out/regs/html/<name>_regs.html` — register documentation

The generated AXI-Lite entity requires the `hdl-modules` library (fetched via `make deps`).

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
