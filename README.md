# HDL Template

A GitHub template repository for FPGA/ASIC projects supporting VHDL and SystemVerilog side-by-side, with a fully wired build system from day one.

Click **Use this template** to create your own repository, then run `make init NAME=<project>` to rename everything.

---

## What you get

| Capability | Tools |
|---|---|
| **Dependency management** | [Bender](https://github.com/pulp-platform/bender) (primary) + [FuseSoC](https://fusesoc.readthedocs.io) (`template.core`) |
| **Register generation** | [hdl-registers](https://hdl-registers.com) — TOML → VHDL package, AXI-Lite wrapper, C header, HTML |
| **Simulation — VHDL** | GHDL + [VUnit](https://vunit.github.io) or [cocotb](https://www.cocotb.org) |
| **Simulation — SV** | Verilator or Icarus Verilog + cocotb |
| **Synthesis** | [Yosys](https://yosyshq.net/yosys/) targeting Xilinx XC7 (`synth_xilinx -family xc7`) |
| **Linting — VHDL** | GHDL analysis + [vsg](https://vsg-hdl.readthedocs.io) (VHDL Style Guide) |
| **Linting — SV** | Verilator `--lint-only -Wall` |
| **Documentation** | [HDLAutoDoc](https://github.com/FPGA-James/HDLAutoDoc) Sphinx pipeline — block diagrams, FSM diagrams, WaveDrom waveforms, CDC analysis, register map |
| **CI** | GitHub Actions matrix covering all simulator/framework combinations, synthesis, and GitHub Pages deployment |

---

## Getting started

### 1 — Create your repository

Click **Use this template → Create a new repository** on GitHub.

Clone your new repo:

```bash
git clone https://github.com/<you>/<your-repo>.git
cd <your-repo>
```

### 2 — Initialise the project

Replace all `<<NAME>>` placeholders in file contents and rename `NAME_*` files:

```bash
make init NAME=my_module
```

Valid names: lowercase letters, digits, and underscores (e.g. `uart_ctrl`, `axi_dma`).

### 3 — Set up the Python environment

```bash
make venv
```

Creates `.venv/` and installs all Python dependencies from `requirements.txt`. All subsequent `make` targets use `.venv/bin/python3` automatically.

### 4 — Fetch HDL dependencies

```bash
make deps
```

Runs `bender update && bender vendor init`, fetching external repos (including `hdl-modules` for the AXI-Lite register file) into `deps/`.

### 5 — Generate register files

```bash
make regs
```

Reads `regs/<name>_regs.toml` and writes to `gen/vhdl/`, `gen/sv/`, and `gen/c/`.

### 6 — Run the testbench

```bash
make sim                                              # VHDL + VUnit + GHDL (default)
make sim FRAMEWORK=cocotb SIM=ghdl TOPLEVEL_HDL=vhdl  # VHDL + cocotb + GHDL
make sim FRAMEWORK=cocotb SIM=verilator TOPLEVEL_HDL=sv # SV + cocotb + Verilator
make sim FRAMEWORK=cocotb SIM=icarus TOPLEVEL_HDL=sv    # SV + cocotb + Icarus
```

---

## HDL structure

The template ships with a saturating pulse counter as the example design. Three-module hierarchy:

```
<name>_top       ← AXI-Lite slave port + design I/O
  ├── <name>_regs  ← generated AXI-Lite register block (never hand-written)
  └── <name>_core  ← pure logic, register signals in/out
```

Both VHDL (`src/vhdl/`) and SystemVerilog (`src/sv/`) implementations have identical port names, so the cocotb testbench (`tb/cocotb/test_<name>.py`) runs unchanged against either.

---

## Make targets

```
make init NAME=<n>   Replace <<NAME>> placeholders and rename NAME_* files
make venv            Create .venv/ and install Python deps
make deps            Fetch external HDL repos via Bender into deps/
make regs            Generate register files from regs/*.toml
make sim             Run testbench (see FRAMEWORK/SIM/TOPLEVEL_HDL vars)
make lint            VHDL: GHDL analysis + vsg  |  SV: Verilator --lint-only
make lint-vhdl       VHDL lint only
make lint-sv         SV lint only
make synth           Yosys XC7 synthesis (VHDL path via ghdl-yosys-plugin)
make synth TOPLEVEL_HDL=sv   SV synthesis path
make html            Build Sphinx documentation
make test-autodoc    Run the HDLAutoDoc pytest suite
make clean           Remove generated artefacts
```

### Key Makefile variables

| Variable | Default | Options |
|---|---|---|
| `SIM` | `ghdl` | `ghdl` \| `verilator` \| `icarus` |
| `FRAMEWORK` | `vunit` | `vunit` \| `cocotb` |
| `TOPLEVEL_HDL` | `vhdl` | `vhdl` \| `sv` |

**Compatibility:** `SIM=ghdl` requires `TOPLEVEL_HDL=vhdl`. `SIM=verilator` or `SIM=icarus` requires `TOPLEVEL_HDL=sv`. The cocotb Makefile enforces this with a guard.

---

## Project layout

```
hdl_template/
├── Bender.yml              HDL dependency manifest (primary source of truth for file lists)
├── template.core           FuseSoC CAPI=2 manifest (kept in sync with Bender.yml)
├── Makefile
├── requirements.txt
├── vsg.yml                 VHDL Style Guide linter config
├── pytest.ini
│
├── src/
│   ├── vhdl/               VHDL source (NAME_pkg, NAME_core, NAME_top)
│   └── sv/                 SV mirror (identical port names)
│
├── tb/
│   ├── vunit/
│   │   ├── run.py          VUnit runner
│   │   └── vhdl/NAME_tb.vhd
│   └── cocotb/
│       ├── Makefile        cocotb sim Makefile
│       └── test_NAME.py    cocotb tests (language-agnostic)
│
├── regs/
│   └── NAME_regs.toml      Register definitions (hdl-registers TOML format)
│
├── gen/                    GENERATED — never hand-edit (gitignored)
│   ├── vhdl/               VHDL register package + AXI-Lite wrapper
│   ├── sv/                 SV register package
│   └── c/                  C header
│
├── synth/
│   ├── NAME_vhdl_xc7.ys    Yosys script — VHDL path (ghdl-yosys-plugin)
│   ├── NAME_sv_xc7.ys      Yosys script — SV path
│   └── constraints/NAME.xdc  XDC pin/timing template (Arty A7-35T)
│
├── scripts/
│   ├── hdl_autodoc/        HDLAutoDoc extraction pipeline (do not modify)
│   ├── gen_regs.py         hdl-registers generation driver
│   ├── gen_filelist.sh     Bender → filelist.f
│   └── init_project.sh     <<NAME>> placeholder replacement
│
├── docs/                   Sphinx documentation source
└── deps/                   GENERATED — external repos fetched by Bender (gitignored)
```

---

## Template placeholder system

All example files use `<<NAME>>` in file contents and `NAME_` as a filename prefix. `make init NAME=<project>` replaces all occurrences and renames files in one step.

Files excluded from replacement: `.venv/`, `deps/`, `.git/`, `gen/`.

---

## CI

GitHub Actions runs on every push and pull request:

| Job | Tools |
|---|---|
| `regs` | hdl-registers + drift check (regenerate + diff) |
| `lint` | GHDL + vsg (VHDL), Verilator (SV) |
| `sim-vhdl-vunit` | GHDL + VUnit |
| `sim-vhdl-cocotb` | GHDL + cocotb |
| `sim-sv-verilator` | Verilator + cocotb |
| `sim-sv-icarus` | Icarus Verilog + cocotb |
| `synth` | Yosys XC7 |
| `test-autodoc` | pytest (HDLAutoDoc test suite) |

The `docs.yml` workflow builds Sphinx HTML and deploys to GitHub Pages on every push to `main`. Enable it under **Settings → Pages → Source: GitHub Actions**.

---

## Tool requirements

| Tool | Required for | Install |
|---|---|---|
| Python 3.13 | Everything | `brew install python` / `apt install python3` |
| GHDL | VHDL sim, lint, synthesis | `apt install ghdl` / [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build/releases) |
| Verilator | SV sim + lint | `apt install verilator` / `brew install verilator` |
| Icarus Verilog | SV sim (icarus path) | `apt install iverilog` / `brew install icarus-verilog` |
| Yosys | Synthesis | `apt install yosys` / [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build/releases) |
| Graphviz | Documentation diagrams | `apt install graphviz` / `brew install graphviz` |
| Bender | Dependency management | [releases](https://github.com/pulp-platform/bender/releases) |

> **VHDL synthesis** requires `ghdl-yosys-plugin`. The easiest way to get GHDL, Yosys, and the plugin together is the [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build/releases).

---

## License

MIT
