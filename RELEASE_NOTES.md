# Release Notes

## Unreleased

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
