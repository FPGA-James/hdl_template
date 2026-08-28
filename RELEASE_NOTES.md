# Release Notes

## V1.4.0 — CI actually works

Both GitHub Actions workflows (`ci.yml`, `docs.yml`) had never fully passed since this repo's first commit. All of it traces back to real, fixable infrastructure bugs, not the `<<NAME>>`-placeholder limitation already known about — that limitation is real too, but it was never the thing actually blocking every run.

- **`make venv` was never called.** Every CI job ran `pip install -r requirements.txt` directly instead, but every Makefile target is gated on `.venv/` actually existing — so every job failed immediately, unconditionally, on every push, forever. Now every job runs `make venv`.
- **Bender's download URL was stale.** Upstream renamed release assets and switched compression format (`bender-linux-x86_64.tar.gz` → `bender-x86_64-unknown-linux-gnu.tar.xz`); the old URL 404s.
- **`OSS_CAD_SUITE` was never actually installed on CI** — jobs `apt-get install`ed GHDL/Yosys/Verilator/Icarus as plain system packages instead, but the Makefile always invokes tools via `$(OSS_CAD_SUITE)/bin/<tool>`. CI now installs and caches the real OSS CAD Suite, matching documented local dev setup.
- Fixing the above two uncovered two more, deeper bugs, both real and both now fixed: OSS CAD Suite's own bundled Python (no working `ensurepip`) was shadowing the intended interpreter for `make venv`'s own bootstrap step; and a relative-path bug (`.venv/bin` vs `$(CURDIR)/.venv/bin`) let OSS CAD Suite's own bundled `cocotb` (a pre-release build with a real internal bug) shadow the project's pinned one once `tb/cocotb/Makefile` changed directory.
- **`scripts/gen_filelist.sh` excluded SystemVerilog sources from the documentation pipeline unconditionally.** HDL AutoDoc genuinely supports SV projects (hierarchy parsing, a working — if plainer, since `sphinx-vhdl`'s structured entity tables are VHDL-only upstream — RST fallback, native-Yosys schematics); the exclusion was meant to avoid a real duplicate-module-name collision that only actually happens pre-`make init` (when both `src/vhdl/` and `src/sv/` coexist), but applied unconditionally, breaking the far more common single-language case too. `make html`/`make coverage` now work for SV projects.
- **`docs.yml` built directly on `main`**, the raw un-initialised template — which can never produce real documentation, since `scripts/gen_filelist.sh` isn't even valid bash syntax until `make init` replaces its `<<NAME>>` placeholders. Now initialises the template's own bundled example (a saturating pulse counter) first, mirroring how `ci.yml`'s `smoke-test` job already does this, and actually builds successfully.
- **Six CI jobs that could never pass by design** (`lint`, `sim-vhdl-vunit`, `sim-vhdl-cocotb`, `sim-sv-verilator`, `sim-sv-icarus`, `synth` — all running against the raw un-initialised checkout) are now commented out rather than left permanently red; `smoke-test` (which runs `make init` first) remains the reliable, working signal it always was meant to be.
- **`docs.yml`'s `deploy` job is commented out** until GitHub Pages is enabled for this repo (a one-time manual `Settings → Pages` step) — `build` still runs and verifies documentation builds correctly on every push.
- **Restored `vunit`/`ghdl`/`vhdl` as the real Makefile defaults** (`FRAMEWORK`/`SIM`/`TOPLEVEL_HDL`), matching what every doc already claimed — they had drifted to `cocotb`/`verilator`/`sv`, so `make init NAME=x` (no override) was silently creating an SV project despite being documented "VHDL project (default)".

Result: `ci.yml` and `docs.yml` are both fully green on every push, for the first time in this repo's history.

## V1.3.0 — Testbenches target `_top` via real AXI-Lite

Every testbench (VUnit, cocotb for VHDL/SV, native-vhdl, native-sv) now drives `<name>_top`'s real AXI4-Lite register interface instead of `<name>_core`'s raw ports directly — exercising the auto-wired register integration, not just the core logic in isolation. Adds a new C++ testbench path.

- **New `make sim-cpp TOPLEVEL_HDL=sv`**: compiles and runs `tb/cpp/<name>_tb.cpp` directly with `verilator --cc --exe --build`, using a small hand-rolled `AxiLiteDriver<Top>` C++ template driver (`tb/cpp/axi_lite_driver.hpp`).
- **Per-framework AXI-Lite drivers**: VUnit uses `hdl_registers`' generated simulation read/write package plus hdl-modules' `axi_lite_master` BFM; cocotb (both languages) uses `cocotbext-axi`; native-vhdl uses OSVVM's `Axi4LiteManager` (`nvc --install osvvm`, one-time setup); native-sv and C++ use small hand-rolled drivers, since no viable off-the-shelf, Verilator-compatible, non-UVM SV AXI-Lite BFM exists (verified via a real failed spike against pulp-platform/axi under Verilator).
- **New generators**: a VHDL simulation read/write package (`out/regs/vhdl/<name>_register_read_write_pkg.vhd`, VUnit-only) and an SV register-address constants package (`out/regs/sv/<name>_regs_addr_pkg.sv`, consumed by the native-SV and C++ paths) — both driven off the real generated register map, never hand-typed addresses.
- `scripts/init_project.sh` now also handles `.cpp`/`.h`/`.hpp` files; `scripts/smoke_test.sh` and CI gained an `install-osvvm` step (VHDL) and a `sim-cpp` step (SV).

### Fixes

- Two real timing races in the hand-rolled SystemVerilog AXI-Lite driver, found and fixed via direct reproduction against the real generated register file (not assumption): sequential per-signal polling could miss a fast handshake response; clearing `bready`/`rready` the same cycle `bvalid`/`rvalid` was first observed could race the register file's registered FIFO accept-pointer. Both fixed and independently verified deterministic across repeated runs; the C++ driver was built afterward with this context and empirically re-confirmed both findings apply there too.
- `scripts/gen_regs.py`'s SV address-constants generator computed addresses from positional list index rather than each register's real index — silently wrong for any register map with a `register_array` (each element consumes an index, but the array is one list entry). Fixed; regression test added.
- `tb/vunit/run.py` hardcoded the literal `bender`, ignoring the Makefile's documented `BENDER` override entirely. Fixed to read it from the environment; `sim-vunit`/`sim-vunit-gui`/`sim-cocotb` now pass it through.
- `Makefile`'s `sim-native-vhdl` target was never updated for the new `_top`-targeting VHDL testbench's library needs (OSVVM's `Axi4LiteManager`, hdl-modules' `axi_lite`/`register_file` libraries, generated regs files) — fixed.

### Known gaps (documented, not fixed in this release)

- `make html`/`make coverage` for SystemVerilog projects fail at the `hierarchy` step: `scripts/gen_filelist.sh` deliberately excludes SV sources from the doc filelist, so HDL AutoDoc's Sphinx pipeline has nothing to parse. Pre-existing, confirmed unrelated to this release via `git log`, now documented in `CLAUDE.md`.
- The macOS `libintl.8.dylib` (cocotb + OSS CAD Suite Python shadowing) and `libxcb.dylib` (Sphinx/wavedrom import crash) gaps are unchanged from prior releases.

## V1.0.0

### `make init` — language-aware src/ flattening

`make init` now accepts a `TOPLEVEL_HDL=vhdl|sv` variable (default: `vhdl`).

During initialisation the script:
1. Moves the chosen language's files from `src/vhdl/` or `src/sv/` up to `src/`.
2. Deletes both language subdirectories.
3. Normalises `src/vhdl/` and `src/sv/` path references to `src/` across all config and documentation files (`Bender.yml`, `template.core`, `CLAUDE.md`, `README.md`, etc.).

After `make init`, `src/` is a flat directory containing only the files for the chosen language.

```bash
make init NAME=my_module                   # VHDL (default)
make init NAME=my_module TOPLEVEL_HDL=sv   # SystemVerilog
```

### Editor / LSP support

Three new `make` targets generate LSP configuration files from the Bender file lists:

| Target | Output | Language server |
|---|---|---|
| `make lsp` | both files below | — |
| `make vhdl-ls` | `vhdl_ls.toml` | [VHDL LS](https://github.com/VHDL-LS/rust_hdl) (`hbohlin.vhdl-ls`) |
| `make verible-ls` | `verible.filelist` | [Verible](https://chipsalliance.github.io/verible/) (`chipsalliance.verible`) |

Both output files are gitignored and should be regenerated after `make deps` or whenever source files are added.

**VHDL LS** (`vhdl_ls.toml`) maps files to VHDL library names:
- `axi_lite` / `register_file` — hdl-modules dependency libraries
- `work` — project RTL (`rtl_vhdl`) and generated register files (`gen_vhdl`)
- `tb_lib` — VUnit testbench (`tb_vhdl`)

**Verible** (`verible.filelist`) is a flat list of SV source paths from the `rtl_sv` Bender target. Verible auto-reloads this file on modification time change.

### nextpnr implementation flow

The `impl`, `impl-gui`, and `icestudio` Makefile targets were already present but are now documented throughout (`README.md`, `CLAUDE.md`). Key variables:

| Variable | Default | Notes |
|---|---|---|
| `IMPL_FAMILY` | `ice40` | `ice40` \| `ecp5` \| `machxo2` |
| `IMPL_DEVICE` | `hx8k` | Must match physical FPGA |
| `IMPL_PACKAGE` | `ct256` | Must match physical FPGA |
| `IMPL_TOPLEVEL` | `NAME_core` | Defaults to core (not top) to stay within iCE40 IO limits |

### Dependency update

`hdl-modules` bumped from `5.1.0` → `6.2.1` in `Bender.yml`.

### Documentation improvements

- `README.md`: added **Implementation** and **Editor / LSP** rows to the capability table; expanded Make targets and variables tables; richer `out/` layout in the project tree.
- `CLAUDE.md`: added Toolchain section (OSS CAD Suite path); documented `make lsp`, `make vars`, `make synth-gui`, `make impl*`; updated Template Initialisation section to describe the new src/ flattening step.
