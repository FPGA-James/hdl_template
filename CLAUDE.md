# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open-source HDL project template supporting both VHDL and SystemVerilog. All workflows are driven through `make`. The template uses `<<NAME>>` as a placeholder that gets replaced by `make init NAME=<project>`.

## Toolchain

All HDL tools (GHDL, Yosys, Verilator, Icarus, nextpnr) are expected to come from **OSS CAD Suite**, installed at `~/tools/oss-cad-suite` by default. Override with `make <target> OSS_CAD_SUITE=/path/to/oss-cad-suite`.

**NVC** (VHDL simulator) is a separate dependency, used only by `make sim-native TOPLEVEL_HDL=vhdl` — it's not bundled in OSS CAD Suite. Install via `brew install nvc` or see https://www.nickg.me.uk/nvc/. Override with `make sim-native NVC=/path/to/nvc`.

**macOS libxcb note**: `make html`/`make pdf`/`make coverage` (and `doc-check-env`, and `make test-autodoc`, whose navigation tests build a Sphinx project in-process) require `libxcb.dylib` to be findable by `cffi`'s `dlopen()` — this is needed by `sphinxcontrib.wavedrom` → `cairosvg` → `cairocffi` → `xcffib` at module-import time. The Makefile sets `DYLD_LIBRARY_PATH=/opt/homebrew/lib:/usr/local/lib` inline on each sphinx invocation (bypassing SIP stripping by setting it in the child's environment after the shell's own dyld initialisation). This requires `libxcb` to be installed (`brew install libxcb`); if it isn't, you'll see `OSError: cannot load library 'libxcb.dylib'`. Untested whether Linux CI hits the same gap (unlikely — `libxcb` is typically in the standard linker path on Linux).

**SV documentation is plainer than VHDL's, by design**: `scripts/gen_filelist.sh` includes SV sources (via Bender's `rtl_sv`/`gen_sv` targets, verified to actually exist on disk — see the script's `bender_flist()` comment for why a naive check isn't enough) so `make html`/`make coverage` work for `TOPLEVEL_HDL=sv` projects too. HDL AutoDoc's `parse_hierarchy.py`/`generate_schematic.py` genuinely support SV (hierarchy discovery, native-Yosys schematics), but `generate_rst.py`'s entity page falls back to a plain `literalinclude` source listing for SV modules instead of the structured port/generic table `.. vhdl:autoentity::` produces — that directive comes from the `sphinx-vhdl` extension and is VHDL-only upstream, a permanent difference in documentation depth, not a bug. The VHDL branch of `gen_filelist.sh` is only taken when `.vhd` files actually exist on disk (always true pre-init, since Bender.yml's file lists aren't pruned by `make init` — only `src/` itself is), falling through to the SV branch otherwise; this avoids the duplicate-module-name collision that occurs when *both* `src/vhdl/` and `src/sv/` exist simultaneously. Pre-init the script itself does not parse (its fallback loops hold unquoted `<<NAME>>`); docs are a post-init feature.

**SV register-file synthesizability**: `hdl_registers`' SystemVerilog generator delegates to PeakRDL-regblock, which unconditionally emits **unpacked** SV structs for its `hwif_in`/`hwif_out` types and `automatic` locals inside `always_comb` blocks — neither supported by free/OSS Yosys's native `read_verilog -sv` frontend (`"Only PACKED supported at this time"` / `"unexpected TOK_AUTOMATIC"`), which would otherwise break `make synth TOPLEVEL_HDL=sv`/`make impl TOPLEVEL_HDL=sv` for any project using the register auto-wiring feature. `generate_sv()` in `scripts/gen_regs.py` (`_make_sv_synthesizable`) post-processes both generated files to work around this — packing every struct level (verified safe: no code anywhere bit-slices a struct as a flat vector) and stripping `automatic` (verified safe: these blocks never recurse or run concurrently) — verified via a full `synth` run producing a clean netlist, with no change in behavior for Verilator-based flows (`lint-sv`, `sim-cocotb-verilator`, `sim-native`).

**Icarus is not supported for SystemVerilog**: Icarus Verilog (13.0-devel) cannot parse a module with an `axil_if.slave` modport port (`syntax error` at `<<NAME>>_top`'s port list — verified; it cannot parse interface/modport ports anywhere in the hierarchy), and it also rejects the generated register file's constructs (the post-processing above helps Yosys, not Icarus). `tb/cocotb/Makefile` therefore accepts only `SIM=verilator` for `TOPLEVEL_HDL=sv` and says why. A project that needs Icarus must give its top flat ports and verify the register file separately.

## Makefile Layout

The top-level `Makefile` is a thin entry point (user variables + includes); the logic is split by flow, with one file per tool backend:

```
Makefile                user variables (FRAMEWORK, SIM, TOPLEVEL_HDL, SCHEMATICS, ...), includes, all
scripts/mk/core.mk      PATH/env, Bender file lists, macros, tool registry (SYNTH_TOOLS, IMPL_TOOLS, SIM_NATIVE_TOOLS)
scripts/mk/setup.mk     venv, deps, init, lsp, regs
scripts/mk/sim.mk       sim dispatcher (FRAMEWORK) + cocotb/vunit; sim-native -> sim-native-$(NATIVE_SIM)
scripts/mk/synth.mk     synth -> synth-$(SYNTH_TOOL)
scripts/mk/impl.mk      impl / impl-gui -> impl-$(IMPL_TOOL); icestudio help entry
scripts/mk/docs.mk      HDL AutoDoc (includes the submodule's autodoc.mk) + html/pdf/doc/coverage/reports
scripts/mk/lint.mk      lint -> lint-$(HDL_KIND), test-autodoc
scripts/mk/clean.mk, scripts/mk/help.mk
scripts/mk/tools/*/*.mk   yosys, nextpnr, nvc, verilator, ghdl (lint-vhdl), icestudio
```

**Adding a tool backend (e.g. Questa, Vivado):** drop a file in `scripts/mk/tools/<tool>/<tool>.mk` that appends itself to the registry for the flows it provides (`SYNTH_TOOLS += vivado`, `IMPL_TOOLS += vivado`, `SIM_NATIVE_TOOLS += questa`) and defines the matching `<flow>-<tool>` targets (`synth-vivado`, `impl-vivado` / `impl-gui-vivado`, `sim-native-questa`); select it with `SYNTH_TOOL=vivado` / `IMPL_TOOL=vivado` / `NATIVE_SIM=questa`. Nothing else needs editing — the dispatchers use `$(wildcard scripts/mk/tools/*/*.mk)` and an unregistered tool gets an error listing the registered ones (`unknown-tool` macro in `scripts/mk/core.mk`). Tool-specific variables (family/part/constraint) belong in the tool's own file; vendor flows are best written as Tcl/DO scripts under `scripts/<tool>/` that the `.mk` file launches. cocotb and VUnit pick their simulator from `SIM` / `VUNIT_SIMULATOR` (see `tb/cocotb/Makefile`, `tb/vunit/run.py`) — those two files need a Questa branch too. Bender can emit tool-specific file lists directly (`bender script vsim`, `bender script vivado`).

Conventions that keep the include-based layout working: help entries (`## description`) for dispatched/aliased targets live in the flow file as recipe-less "stubs" (the recipe is in the tool file), and any alias target with no real recipe gets an explicit `@:` recipe so make does not try the `<flow>-%` fallback rule on it. `HDL_KIND` is the normalised language key (`sv` or `vhdl`) used for per-language variables (`YOSYS_READ_$(HDL_KIND)`). `TOPLEVEL_HDL` (default `vhdl`) is the language switch: `FRAMEWORK` (`vunit` / `cocotb` for SV) and `SIM` (`ghdl` / `verilator` for SV) default from it, and `make init ... TOPLEVEL_HDL=sv` rewrites its default in the project's `Makefile` to `sv`, so a bare `make sim|lint|synth|impl|html` takes the project's language path. `lint-sv` and the sim targets depend on `regs`.

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
make sim FRAMEWORK=cocotb SIM=ghdl TOPLEVEL_HDL=vhdl PYUVM=1      # pyuvm bench instead of test_NAME.py
make sim FRAMEWORK=cocotb SIM=verilator TOPLEVEL_HDL=sv PYUVM=1
make sim-native TOPLEVEL_HDL=vhdl                         # Native VHDL via NVC, no framework
make sim-native TOPLEVEL_HDL=sv                           # Native SV via Verilator --binary, no framework
make sim-cpp TOPLEVEL_HDL=sv                              # C++ bench via Verilator --cc --exe --build

# Single VUnit test
VUNIT_SIMULATOR=ghdl .venv/bin/python tb/vunit/run.py -v "tb_lib.<<NAME>>_tb.test_count_up"

# Synthesis
make synth                  # VHDL via ghdl-yosys-plugin → Xilinx 7-series
make synth TOPLEVEL_HDL=sv  # SV via native Yosys
make synth-gui              # Open Yosys schematic viewer after synthesis

# Implementation (place-and-route via nextpnr)
make impl                   # Synth + PnR → bitstream, then check timing  [default: ECP5 25F-8, 200 MHz]
make impl-gui               # Open nextpnr interactive GUI
make icestudio              # Run impl then open IceStudio for programming
# Key impl variables: IMPL_FAMILY (ecp5|ice40|machxo2), IMPL_DEVICE (25k), IMPL_PACKAGE (CABGA256), IMPL_SPEED (8),
# IMPL_FREQ_MHZ (200), IMPL_TOPLEVEL (SV: NAME_top, VHDL: NAME_core), IMPL_CONSTRAINT (optional; synth/constraints/<top>.lpf|.pcf),
# IMPL_PNR_OPT (nextpnr timing effort)

# Documentation
make html TOPLEVEL_HDL=sv   # Build Sphinx docs (run make regs first)
make html SCHEMATICS=1      # Force RTL schematics on (default: on for SV, off for VHDL)
make pdf                    # Build LaTeX PDF documentation
make doc                    # Build both HTML and PDF

# Simulation (additional)
make sim-vunit-gui          # VUnit + GHDL with waveform viewer

# Linting
make lint                   # Linters for the active language
make lint-vhdl              # GHDL analysis + vsg style guide
make lint-sv                # Verilator --lint-only -Wall

# Register generation
make regs                   # Generate from all regs/*.toml

# Tests
make test-autodoc           # hdl_autodoc Python unit tests (pytest)
.venv/bin/python3 -m pytest scripts/tests   # gen_regs.py unit tests

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
<<NAME>>_top     — top-level wrapper: AXI4-Lite port + instantiates core and regs
  <<NAME>>_core  — pure RTL logic; no register bus; takes decoded register signals
  <<NAME>>_regs  — GENERATED by make regs; never hand-written
```

SystemVerilog: `<<NAME>>_top.sv` takes its bus as an `axil_if.slave s_axil` interface port (`src/sv/axil_if.sv`) and slices the address down to the generated register file's width with `<<NAME>>_regs_addr_pkg::<<NAME>>_addr_width`. VHDL: `<<NAME>>_top.vhd` takes hdl-modules' `axi_lite_m2s_t`/`axi_lite_s2m_t` records and wires `regs_down` (host → core) and `regs_up` (core → host status) using typed records from the generated `<<NAME>>_register_record_pkg.vhd`.

### Source Layout

```
src/vhdl/        VHDL RTL (NAME_pkg.vhd, NAME_core.vhd, NAME_top.vhd)
src/sv/          SystemVerilog RTL (same structure, plus axil_if.sv)
regs/            TOML register definitions (source of truth)
out/             GENERATED outputs (gitignored)
  out/regs/vhdl/ VHDL register packages + AXI-Lite wrapper
  out/regs/sv/   SV register file + address-constants package (SV projects only)
  out/regs/c/    C header files
  out/regs/html/ HTML register documentation
tb/vunit/        VUnit runner (run.py) + VHDL testbenches
tb/cocotb/       cocotb Makefile + Python test modules
  tb/cocotb/vhdl/        GHDL-only flattening wrapper (see Simulator / Framework Routing below)
  tb/cocotb/NAME_top_cocotb_top.sv   SV flattening wrapper (axil_if -> flat s_axi_* signals)
  tb/cocotb/pyuvm_tb/    pyuvm testbench (register agent, counter reference model); not named pyuvm: that would shadow the pip package
tb/native/       Framework-less testbenches (tb/native/vhdl, tb/native/sv) run directly by NVC / Verilator
tb/cpp/          Framework-less C++ testbench + hand-rolled AXI-Lite driver, run directly by Verilator --cc --exe --build
synth/           Yosys synthesis scripts (.ys) + XDC constraints; synth/constraints/NAME_top.lpf for the ECP5 flow
scripts/
  mk/            Makefile fragments (see Makefile Layout above)
  gen_regs.py    Register generation driver (uses hdl_registers)
  gen_filelist.sh Bender → filelist.f for hdl_autodoc
  check_nextpnr_timing.sh  Reads nextpnr's routed Max frequency and fails if the target is missed
  init_project.sh Template initialisation (replaces <<NAME>>)
docs/            Sphinx documentation source (conf.py wrapper; pages are generated)
```

### Dependency Management

**Bender** (`Bender.yml`) is the primary source of truth for all HDL file lists. `Bender.lock` is committed for reproducible builds. The Makefile calls `bender script flist -t <target>` to get ordered file lists:
- `rtl_vhdl` — VHDL RTL sources
- `rtl_sv` — SV RTL sources (`axil_if.sv` before its consumer)
- `gen_vhdl`, `gen_sv` — generated register files
- `tb_vhdl` — testbench VHDL (simulation only)
- `impl_sv` — optional, commented out: a few-pin wrapper for `make impl` when a top has more port bits than the package has pins (SV only; set `IMPL_TOPLEVEL` to its module)

**FuseSoC** (`template.core`) is a secondary manifest kept in sync with `Bender.yml` for ecosystem compatibility.

`hdl_modules` (declared under `dependencies:`) has no `Bender.yml` of its own — Bender still checks it out via `bender update` and resolves it with `bender path hdl_modules`, which the Makefile uses to locate `axi_lite_pkg.vhd`/`register_file_pkg.vhd` for GHDL library compilation. There is no `deps/` vendoring step — `make deps` is just `bender update`; the checkout lives in Bender's own `.bender/` cache (gitignored).

### Simulator / Framework Routing

| `FRAMEWORK` | `SIM`      | `TOPLEVEL_HDL` | Mechanism             |
|-------------|------------|----------------|-----------------------|
| `vunit`     | ghdl       | vhdl           | VUnit → GHDL via VHPI |
| `cocotb`    | ghdl       | vhdl           | cocotb → GHDL via VPI |
| `cocotb`    | verilator  | sv             | cocotb → Verilator VPI|

The `tb/cocotb/Makefile` enforces valid combinations with an error guard (Icarus: see the Toolchain notes).

Neither cocotb path targets `<<NAME>>_top` directly. The `ghdl`/`vhdl` row targets `tb/cocotb/vhdl/<<NAME>>_cocotb_top.vhd`: GHDL's VPI backend cannot expose VHDL record-typed ports (`s_axi_m2s`/`s_axi_s2m`) to cocotb at all, so the wrapper flattens them into flat `s_axi_*` signals around an unmodified `<<NAME>>_top`. The `verilator`/`sv` row targets `tb/cocotb/NAME_top_cocotb_top.sv`, which does the same for the `axil_if` port (no simulator accepts an interface port on the top level). Both expose identical signal names, so `test_NAME.py` and the pyuvm bench run unchanged on either language. `test_NAME.py` pins the register read latency (`READ_TO_READ_OVERHEAD_CYCLES`: 4 for VHDL, 5 for SV — the SV generator registers the decode stage); it is what fails if that stage changes.

Every testbench above targets `<<NAME>>_top` (not `_core`), driving it over its real AXI-Lite register interface: VUnit uses `hdl_registers`' generated read/write package plus `hdl-modules`' `axi_lite_master` BFM; cocotb (both languages) uses `cocotbext-axi`'s `AxiLiteMaster`. `PYUVM=1` swaps `test_NAME.py` for `tb/cocotb/pyuvm_tb/test_NAME_top.py` (a register agent plus `CounterModel`; exact counts are checked only while the counter is disabled because a read is a multi-cycle transaction).

`make sim-native TOPLEVEL_HDL=vhdl|sv` is a separate, framework-less path — it compiles and runs `tb/native/vhdl/NAME_tb.vhd` directly with NVC (using OSVVM's `Axi4LiteManager` — install once via `nvc --install osvvm`), or `tb/native/sv/NAME_tb.sv` directly with `verilator --binary --timing` (using a small hand-rolled AXI-Lite driver, `tb/native/sv/axi_lite_driver_pkg.sv` — no off-the-shelf, non-UVM, Verilator-compatible SV BFM exists; the bench bridges its flat signals to an `axil_if`). Both also target `<<NAME>>_top`.

`make sim-cpp TOPLEVEL_HDL=sv` compiles and runs `tb/cpp/<<NAME>>_tb.cpp` via `verilator --cc --exe --build` against `tb/cpp/NAME_top_cpp_flat.sv` (another flattening wrapper), using a small hand-rolled AXI-Lite driver (`tb/cpp/axi_lite_driver.hpp`). SV-only; Verilator doesn't read VHDL.

### Register Generation

Register definitions live in `regs/<name>_regs.toml` using the `hdl_registers` TOML format. Running `make regs` calls `scripts/gen_regs.py` which generates:
- `out/regs/vhdl/<name>_regs_pkg.vhd` — address/field constants
- `out/regs/vhdl/<name>_register_record_pkg.vhd` — typed VHDL records
- `out/regs/vhdl/<name>_register_file_axi_lite.vhd` — AXI-Lite register entity (this is `<<NAME>>_regs`)
- `out/regs/vhdl/<name>_register_read_write_pkg.vhd` — VUnit-only simulation read/write procedures, used by `tb/vunit/vhdl/<name>_tb.vhd` to drive registers over `net`/`bus_handle` message passing instead of raw signal manipulation
- `out/regs/c/<name>_regs.h` — C header for embedded drivers
- `out/regs/html/<name>_regs.html` — register documentation

The generated AXI-Lite entity requires the `hdl-modules` library (fetched via `make deps`).

For SystemVerilog projects, `make regs` instead generates `out/regs/sv/<name>_register_file_axi_lite.sv` and `out/regs/sv/<name>_register_file_axi_lite_pkg.sv` via PeakRDL-regblock (through `hdl_registers`' SystemVerilog generator, `flatten_axi_lite=True`), plus `out/regs/sv/<name>_regs_addr_pkg.sv` — a small lowercase-named localparam package: one per register's byte address, and `<name>_addr_width`, the bit width of the register file's address ports (copied from the generated package's uppercase `MIN_ADDR_WIDTH`, which `<<NAME>>` template substitution cannot produce). `scripts/gen_regs.py` (`_register_sv_decode`) also registers PeakRDL-regblock's decode stage (strobes, request, address, write data) before the field logic, which shortens the request → decode → load-enable critical path; reads and writes each gain one cycle and stay ordered, the register map and ports are unchanged.

`make regs` also auto-wires each register field to a matching `<name>_core` port, rewriting only the marker-delimited region(s) inside `<name>_top` (VHDL: `-- BEGIN/END AUTOGEN REGISTER SIGNALS` plus `-- BEGIN/END AUTOGEN REGISTERS`; SV: `// BEGIN/END AUTOGEN REGISTERS`). Field leaf names must be unique across the whole register map (each resolves to a distinct `<name>_core` port). Interface-typed core ports (e.g. a stream) are connected by name to an identically named top port. The SV top slices `s_axil` addresses to `<name>_addr_width` bits, so the `axil_if` instances (testbench wrappers) need `ADDR_W` at least that wide: the default 8 covers 64 registers, a larger map needs a larger `ADDR_W` where `axil_if` is instantiated.

### Documentation Pipeline

The HDL AutoDoc pipeline lives in the `submodules/HDLAutoDoc` git submodule (pinned at **v3.13.0**) and is consumed the way upstream intends: the Makefile `include`s `submodules/HDLAutoDoc/src/autodoc.mk` (all its targets are `doc-*`: `doc-html`, `doc-pdf`, `doc-coverage`, `doc-clean-generated`, …; `make doc-help` lists them). Our `html`/`pdf`/`doc`/`coverage`/`reports` targets are thin aliases that add project glue by *adding prerequisites* to upstream's targets: `filelist` (Bender → `filelist.f`) plus the venv/submodule checks before `doc-hierarchy`. `autodoc.mk` assigns its variables with `=`, so the project overrides (`AUTODOC_SOURCEDIR=docs`, `AUTODOC_BUILDDIR=out/docs`, `AUTODOC_SPHINXBUILD` with the macOS `DYLD_LIBRARY_PATH` prefix, `AUTODOC_CONFDIR=docs`) sit *after* the include. If the submodule isn't checked out the Makefile still parses (sim/synth/lint work); the doc targets print the usual "run `git submodule update --init --recursive`" message. To update the tool: `git -C submodules/HDLAutoDoc fetch --tags && git -C submodules/HDLAutoDoc checkout <tag>`, then `make html`.

Sphinx reads the shared `conf.py`, `_static/` and `_templates/` from the tool via `-c`. `docs/conf.py` is a short wrapper that `exec`s the tool's conf (path passed as `AUTODOC_TOOL_CONFDIR`) and adds the `sphinxcontrib.rsvgconverter` extension (SVG → PDF); it also puts the tool's conf dir on `sys.path` first, because the tool's conf imports `mermaid_support` from beside itself. `docs/_static/` holds only generated register pages. The register-map docs read from `$(AUTODOC_REGISTERS_DIR)` (`out/registers`): the `regs` target copies `regs/<name>_regs.toml` there.

**Schematics (`SCHEMATICS`):** `make html` renders an RTL schematic (yosys → netlistsvg) for every module, shown under a collapsed "RTL Detail" section. Default **on for SV, off for VHDL**: HDL AutoDoc v3.13 records package/interface files (modules-less) as `support_files` for SystemVerilog only, so a VHDL module that uses a package fails its schematic ("no declaration for …"). The SVG/PDF outputs and `docs/.extract_cache.json` are gitignored — after editing a package/interface (or on a stale cache) run `make html FORCE=1`. yosys's native SV front end limits still apply (no `return` in functions, no `import` inside a module body, basic interface/modport only).

Known upstream limits (the only warnings a clean build prints): the generated register file's source page `literalinclude`s `src/<name>_register_file_axi_lite.<ext>`, which lives in `out/regs/`, so Sphinx reports "Include file not found" (VHDL also "Entity … was not found in parsed VHDL"); and `could not extract module name from …pkg.vhd` notices for VHDL packages.

Behaviours of the SV description renderer worth knowing: the `//` comment block directly above `module <name>` is copied into that module's `entity.rst` as RST, so (a) a diagram or list in a module-header comment must be introduced by a paragraph ending in `::` (e.g. `Register interface::`), otherwise nested indentation is an RST error; (b) unbalanced backticks in that block (e.g. SystemVerilog macro ticks) are RST warnings; (c) a non-comment line (such as a `` `include``) between the comment block and `module` cuts the block. The hierarchy parser (`parse_hierarchy.py`) matches `#(...)` up to the first `)`, so an instance whose parameter override contains parentheses (`#(.X(X))`) is not seen at all — pass parameters by position (`#(X)`). A port's description is only the **single comment line directly above it** (or an inline comment).

The `make html` target runs the full HDL AutoDoc + Sphinx pipeline:
1. `make filelist` — generates `filelist.f` from Bender
2. `parse_hierarchy.py` — discovers module relationships
3. `generate_rst.py` — creates RST shells
4. `run_extract.py` — extracts FSMs, block diagrams, CDC, reset domains, processes
5. `generate_coverage.py` — the Documentation Coverage page (also alone via `make coverage`)
6. `sphinx-build` — builds final HTML

Generated Testbenches/Build/Coverage pages (`docs/testbenches/`, `docs/synthesis/`, `docs/coverage.rst`) are gitignored; `TESTBENCHES=0` / `BUILD=0` drop the first two. WaveDrom timing diagrams and Mermaid diagrams (`.. mermaid::`, needs `sphinxcontrib-mermaid`) are embedded in comments.

### Implementation (`make impl`)

`make impl` runs Yosys (`synth_<family>`) then nextpnr and the family's packer, then **gates on timing**: nextpnr runs with `--timing-allow-fail` so the bitstream and reports are always produced, and `scripts/check_nextpnr_timing.sh` reads the routed `Max frequency` per clock and fails the build if any clock misses `IMPL_FREQ_MHZ` (default 200, passed to nextpnr as `--freq`). Defaults: ECP5 LFE5U-25F, CABGA256, speed grade 8.

- **Top and pins:** the SV default is `<<NAME>>_top`, the VHDL default `<<NAME>>_core` (the VHDL top's AXI-Lite records flatten to more IO bits than the package has pins). Pins are left unplaced: the constraint file is optional (`synth/constraints/<top>.lpf`/`.pcf`, passed only if it exists) and nextpnr runs with `--lpf-allow-unconstrained`, so this measures area and Fmax and is not a board design. A top that does not fit needs a few-pin wrapper (Bender target `impl_sv`).
- **Measured on the example counter** (default seed): SV top about 235–254 MHz (depends on the target, since placement is timing-driven), VHDL core about 310 MHz, iCE40 HX8K (`IMPL_FAMILY=ice40 IMPL_DEVICE=hx8k IMPL_PACKAGE=ct256`) about 139 MHz — pass `IMPL_FREQ_MHZ=100` there. Placement varies with the nextpnr seed and tool version.
- **Family define:** the flow reads the RTL with `-DTARGET_<FAMILY>` (`TARGET_ECP5` by default; `YOSYS_DEFINES` in `scripts/mk/tools/yosys/yosys.mk`), so RTL can instantiate a family primitive where inference falls short. `make synth` (Xilinx 7-series), Verilator and the docs schematics do not set it.
- **Reports** go to `out/reports/` (`yosys/yosys.log`, `stat.txt`, `nextpnr.log`), so `make html` shows utilization and timing on the Build page; the full layout is under "Reports" below.
- **Yosys + interfaces:** an interface instance connected to a submodule's interface port must be passed plain (`.s_axil(s_axil)`); selecting the modport on the connection leaves the wires undriven in Yosys and the logic is optimised away (`has no driver` warnings are the symptom). A function cannot use `return` (assign to the function name).

### Reports (`out/reports/`)

Every flow keeps what its tools print, plus the report files they can write, under `out/reports/<tool>/`, for HDL Log Lens (VS Code extension) (it reads `**/out/reports/**/*.log` and `**/*.rpt`, picks the parser from the file or folder name, and reads nextpnr's `*_timing.json` + `*_routed.json` for its Timing table). Logs are written by the `run-logged` macro in `scripts/mk/core.mk` (`tee`, so the terminal output and the exit status are unchanged); each tool's folder is a `<TOOL>_RDIR` variable in its `scripts/mk/tools/<tool>/` file. Keep new tools in a folder named after the tool.

| Folder | Written by | Files |
|---|---|---|
| `yosys/` | `make synth`, `make impl` | `yosys.log`, `stat.txt`, `stat.json`, `check.txt`; synth also `netlist.json`. `make html` reads `yosys.log`, `stat.txt`, `nextpnr.log` at these exact names. `synth` and `impl` share the folder, so the last one run wins. |
| `yosys/nextpnr.log`, `impl/` | `make impl` | `<top>_<family>_timing.json` (timing + utilization + critical paths), `_routed.json`, `_routed.sdf`, `_placed.svg`, `_routed.svg`; iCE40 also `_icetime.rpt` / `_icetime.json` |
| `verilator/` | `lint-sv`, `sim-native`, `sim-cpp` | `lint.log`, `native_*` / `cpp_*`: `_build.log`, `_sim.log`, `_stats.txt`, `_coverage.dat`, `_coverage.info`, `_coverage/` (annotated sources), `_coverage.log` |
| `nvc/` | `sim-native` (VHDL) | `sim.log` (with `--stats`), `<top>_tb.covdb`, `coverage/` (HTML), `coverage.xml` (Cobertura) |
| `ghdl/`, `vsg/` | `lint-vhdl` | `ghdl/lint.log`; `vsg/vsg.log`, `vsg.json`, `vsg.xml` (JUnit), `code_quality.json` |
| `vunit/` | `sim` (VUnit) | `vunit.log` (run with `--no-color`), `xunit.xml` |
| `cocotb/` | `sim FRAMEWORK=cocotb` | `cocotb.log`, `results.xml` (via `COCOTB_RESULTS_FILE`) |

Deliberately not produced: Yosys `ltp` (on a mapped netlist it prints false "Detected loop" warnings into `yosys.log`), nextpnr `--router2-heatmap` (writes no files).

### Template Initialisation

`make init NAME=<name> TOPLEVEL_HDL=vhdl|sv` (default: `vhdl`):
1. Moves `src/<hdl>/` files to `src/`, removes both `src/vhdl/` and `src/sv/`, and normalises `src/vhdl/` / `src/sv/` path references to `src/` across all config and doc files.
2. Replaces all `<<NAME>>` in file contents with `<name>`.
3. Renames all files whose name *begins* with `NAME_` (extensions: vhd sv v py toml ys xdc lpf rst cpp h hpp) to `<name>_*.ext`. Directories are never renamed, so directory names must be neutral. Names that merely *contain* `NAME` keep it: `tb/cocotb/test_NAME.py`, `tb/cocotb/pyuvm_tb/test_NAME_*.py` and `synth/constraints/NAME.xdc` (the cocotb Makefile refers to `test_NAME`, so the files are stable across projects).
4. For `TOPLEVEL_HDL=sv`, rewrites the Makefile's `TOPLEVEL_HDL` default to `sv` (see Makefile Layout).

After `make init`, `src/` is flat (no language subdirectories), no `<<NAME>>` placeholder remains and no file name begins with `NAME_`, and both Bender targets (`rtl_vhdl`, `rtl_sv`) reference `src/` — only the chosen language's files will exist there. Re-running with a different name is a no-op once the placeholders are gone.

## Key Files

- `Makefile` — user variables and includes; targets live in `scripts/mk/`, read the `## help` comments for documentation
- `Bender.yml` — HDL source lists and external dependencies
- `regs/NAME_regs.toml` — register definitions (post-init: `<name>_regs.toml`)
- `scripts/gen_regs.py` — register generation driver (tests: `scripts/tests/`). `FIXED_VALUE_REGISTERS` (name → constant, e.g. `module_id`/`version`) and `NO_CORE_WIRING_REGISTERS` (e.g. a scratch register) are empty by default: edit them to make a register name special, otherwise every register field is wired to a same-named `<name>_core` port
- `scripts/init_project.sh` — project initialisation
- `docs/conf.py` — thin Sphinx wrapper around the tool's shared `conf.py`
- `submodules/HDLAutoDoc` — git submodule; source of the HDL AutoDoc scripts and `autodoc.mk` (`scripts/gen_regs.py` and `docs/conf.py` remain project-owned)
- `vsg.yml` — VHDL Style Guide linter rules (`rule:` is the key vsg reads; `make lint-vhdl` invokes vsg through its `main()`, since `python -m vsg` is a silent no-op)
- `.github/workflows/ci.yml` — CI (`regs`, `test-autodoc`, `smoke-test`; the raw-checkout lint/sim/synth jobs are commented out, see README); includes a `regs` job that regenerates and diffs register files to catch uncommitted drift, and a `smoke-test` job (vhdl/sv matrix) that runs `scripts/smoke_test.sh` — the only job that exercises the Makefile *after* `make init`, which is the state real users actually build against
- `scripts/smoke_test.sh` — copies the working tree into an isolated temp dir per language, runs `make init` (name `my_ip2`), checks for leftover placeholders, then walks `regs`/`lsp`/`lint`/every testbench flow (including pyuvm)/`synth`/`impl`/`html`/`coverage`/`test-autodoc`/the generator tests. Runs every step regardless of earlier failures and prints a full pass/fail summary (`scripts/smoke_test.sh [vhdl|sv]`, `KEEP=1` to keep the temp dirs)
- `.github/workflows/docs.yml` — Sphinx → GitHub Pages deployment (main branch only)
- `.python-version` — pins Python 3.13 for venv and CI
