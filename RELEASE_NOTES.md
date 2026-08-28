# Release Notes

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
