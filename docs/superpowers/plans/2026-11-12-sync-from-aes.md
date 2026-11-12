# Sync the Template from AES Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry AES's generic improvements back into `hdl_template` (VHDL and SystemVerilog both kept), with no AES content left behind.

**Architecture:** One-way port on branch `sync-from-aes`. AES `main` (`791ad7c`) supplies the build system, generators, docs pipeline and SV flow; AES `vhdl-2008` (`e1db0d9`) supplies VHDL tooling. Every file taken from AES is turned back into the template's placeholder form, and the pulse-counter example is rewritten in AES's interface style. `scripts/smoke_test.sh` is the end-to-end check for both languages.

**Tech Stack:** GNU make, Bender, OSS CAD Suite (GHDL, Yosys, Verilator, Icarus, nextpnr), NVC, cocotb + pyuvm + cocotbext-axi, VUnit, hdl_registers/PeakRDL-regblock, Sphinx + HDLAutoDoc, pytest.

**Spec:** `docs/superpowers/specs/2026-11-12-sync-from-aes-design.md`

## Global Constraints

- **Placeholder form.** File contents use `<<NAME>>`; file names use a `NAME_` prefix (`NAME_core.sv`). `make init` substitutes the first and renames only **files** (`.vhd .sv .v .py .toml .ys .xdc .rst .cpp .h .hpp`), never directories. Directories therefore get neutral names (`tb/cocotb/pyuvm/`, not `NAME_pyuvm/`). AES's generic files have `aes` substituted in; convert every `aes` back to `<<NAME>>` (or `NAME_` in names).
- **Sources of AES files:** read them with `git -C /Users/james/Workspace/AES show 791ad7c:<path>` (main) or `git -C /Users/james/Workspace/AES show e1db0d9:<path>` (vhdl-2008). Do not read AES's working tree, and never modify AES.
- Template ships `src/sv/` and `src/vhdl/`; `make init` flattens to `src/`. Bender targets `rtl_vhdl`, `rtl_sv`, `gen_vhdl`, `gen_sv`, `tb_vhdl` must work pre- and post-init.
- Tools are chosen by top-level `Makefile` variables only (`FRAMEWORK`, `SIM`, `TOPLEVEL_HDL`, `SYNTH_TOOL`, `IMPL_TOOL`, `NATIVE_SIM`, `IMPL_FAMILY`). A new backend is one file in `scripts/mk/tools/`.
- No AES RTL, register map, testbench, reference, plan/spec or figure (250 MHz, 256 MHz, LUT counts) in the template. No `impl-sim`, no self-checking impl wrapper, no `axis_if.sv`.
- Interface-typed SV ports are connected plain (`.s_axil(s_axil)`), never with a modport selected (Yosys leaves them undriven otherwise).
- HDL AutoDoc: instance parameter overrides are passed by position (`#(X)`), never `#(.X(X))`; a port's description is the single comment line directly above it; a diagram in a module-header comment follows a paragraph ending in `::`.
- macOS: Sphinx runs keep the inline `DYLD_LIBRARY_PATH=/opt/homebrew/lib:/usr/local/lib` prefix (libxcb).
- Toolchain: OSS CAD Suite at `~/tools/oss-cad-suite`, NVC on PATH, `bender` on PATH.
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

**Verify loop (used by every task).** The tree is a pre-init template, so build checks run in a throwaway initialised copy:

```bash
L=sv   # or vhdl
T=$(mktemp -d) && rsync -a --exclude .git --exclude .venv ./ $T/ && cd $T \
  && make init NAME=demo TOPLEVEL_HDL=$L && make venv deps regs && make <target> TOPLEVEL_HDL=$L
```

`scripts/smoke_test.sh [vhdl|sv]` runs the whole thing; `KEEP=1` keeps the directories.

## Review Focus

1. `make init` with a name containing digits and underscores (`my_ip2`), both languages, leaves no `<<NAME>>`, `NAME_` or `aes` in the tree (Task 2; smoke row in Task 9).
2. A pre-init tree, where both languages exist, still yields a single-language filelist for docs (Task 2).
3. An SV-only user with no `ghdl`, `nvc` or `vsg` on PATH can run `make help`, `make lint-sv` and the Verilator cocotb flow; nothing calls a VHDL tool at parse time (Task 1).
4. `SYNTH_TOOL=nope`, `IMPL_TOOL=nope`, `NATIVE_SIM=nope` each exit non-zero and list the registered tools, not a cryptic make error (Task 1).
5. `make sim FRAMEWORK=cocotb SIM=icarus TOPLEVEL_HDL=sv` against the register file: pass, or a documented gap (AES found Icarus rejects PeakRDL-regblock's unpacked structs and `automatic`) (Task 5).

---

### Task 1: Build system (`scripts/mk/`)

**Files:**
- Create: `scripts/mk/{core,setup,sim,synth,impl,docs,lint,clean,help}.mk`, `scripts/mk/tools/{yosys,nextpnr,nvc,verilator,ghdl,icestudio}.mk` (from AES `791ad7c`, same paths)
- Modify: `Makefile` (replace the 680-line file with AES's 62-line thin entry point)

**Interfaces:**
- Produces: variables `SYNTH_TOOL` (default `yosys`), `IMPL_TOOL` (`nextpnr`), `NATIVE_SIM`, `IMPL_FAMILY`, `IMPL_DEVICE`, `IMPL_PACKAGE`, `IMPL_SPEED`, `IMPL_FREQ_MHZ`, `IMPL_TOPLEVEL` (default `<<NAME>>_top`), `IMPL_CONSTRAINT`; registries `SYNTH_TOOLS`, `IMPL_TOOLS`, `SIM_NATIVE_TOOLS`; macro `unknown-tool`; `HDL_KIND` (`sv`|`vhdl`); target families `synth-<tool>`, `impl-<tool>`, `sim-native-<tool>`.
- Consumes: nothing.

- [ ] **Step 1:** Copy the files, replace every `aes` with `<<NAME>>` (verilator.mk, impl.mk, nvc.mk, sim.mk, nextpnr.mk, setup.mk, Makefile). Keep the template's `PROJECT ?= $(notdir $(CURDIR))` and its `TOPLEVEL ?= <<NAME>>_top`.
- [ ] **Step 2:** Remove the impl-sim path: the `impl-sim` target and help stub, `IMPL_SIM_*` variables, `-DIMPL_SIM_CORRUPT_CT`, and any reference to `tb/impl_sim/` or `aes_impl_top`. `IMPL_TOPLEVEL` stays overridable.
- [ ] **Step 3: Test, tool selection errors.** In the verify loop run `make synth SYNTH_TOOL=nope`, `make impl IMPL_TOOL=nope`, `make sim-native NATIVE_SIM=nope`. Expected: each exits non-zero and prints the registered tools (Review Focus 4).
- [ ] **Step 4: Test, no VHDL tools needed for SV.** `env PATH="$(dirname $(command -v bender)):/usr/bin:/bin" make help` and `make lint-sv TOPLEVEL_HDL=sv` (with OSS CAD Suite supplying Verilator via `OSS_CAD_SUITE`) exit 0 with no "ghdl/nvc not found" at parse time (Review Focus 3). If something calls a VHDL tool at parse time, defer it into the recipe.
- [ ] **Step 5: Test, help and vars.** `make help` lists every flow target including dispatched ones; `make vars` prints the new variables.
- [ ] **Step 6: Commit** `git add Makefile scripts/mk && git commit -m "Adopt the scripts/mk build system layout"`.

### Task 2: Generators and helper scripts

**Files:**
- Modify: `scripts/gen_regs.py`, `scripts/tests/test_gen_regs.py`, `scripts/gen_filelist.sh`, `scripts/init_project.sh`, `requirements.txt`, `pytest.ini`, `.gitignore`
- Create: `scripts/check_nextpnr_timing.sh`

**Interfaces:**
- Produces: `generate_sv()` with `_make_sv_synthesizable` and `_register_sv_decode` (register decode stage registered: reads and writes gain one cycle, map and ports unchanged); `gen_filelist.sh` emitting only VHDL when `.vhd` files exist, else SV; `check_nextpnr_timing.sh <log> <MHz>` exits non-zero if the routed `Max frequency` misses the target.

- [ ] **Step 1:** Port each file from AES `791ad7c`, converting `aes` to the placeholder. In test fixtures use neutral names that do not contain `aes`.
- [ ] **Step 2:** `init_project.sh`: take AES's changes, but keep the template's `<<NAME>>` wording in comments and messages; keep the "already initialised" guard with a generic message.
- [ ] **Step 3: Test, generator.** `.venv/bin/python3 -m pytest scripts/tests -q` passes, including AES's added tests for `_make_sv_synthesizable` and `_register_sv_decode`.
- [ ] **Step 4: Test, init residue.** In a copy, `scripts/init_project.sh my_ip2 sv` and `... vhdl`, then `grep -rI -e '<<NAME>>' -e 'NAME_' -e aes . --exclude-dir=.git --exclude-dir=submodules` is empty and `find . -name 'NAME_*'` is empty (Review Focus 1). A name with uppercase is still rejected.
- [ ] **Step 5: Test, pre-init filelist.** In the pre-init tree, run the `filelist` target's script; the output lists `.vhd` only, no duplicate module names (Review Focus 2).
- [ ] **Step 6: Commit** `"Port generators, filelist and init updates from AES"`.

### Task 3: SystemVerilog example with `axil_if`

**Files:**
- Create: `src/sv/axil_if.sv` (from AES `791ad7c:src/axil_if.sv`)
- Modify: `src/sv/NAME_top.sv`, `Bender.yml`, `template.core`

**Interfaces:**
- Produces: `module <<NAME>>_top (input logic clk, input logic rst_n, input logic pulse_i, axil_if.slave s_axil)`; Bender `rtl_sv` lists `axil_if.sv` before `NAME_top.sv`. The `BEGIN/END AUTOGEN REGISTERS` markers are unchanged.
- Consumes: `generate_sv()` from Task 2.

- [ ] **Step 1:** Rewrite `NAME_top.sv`'s bus ports as `s_axil` and wire the generated register file from the interface members, following `aes_top.sv` in AES `791ad7c`; pass the interface plain.
- [ ] **Step 2:** Add `axil_if.sv` to `rtl_sv` in `Bender.yml` and `template.core`, with the ordering comment from AES.
- [ ] **Step 3: Test.** Verify loop with `make lint-sv` exits 0 with no warnings; `make regs` twice leaves `git diff` empty (markers stable); `make synth TOPLEVEL_HDL=sv` prints no `has no driver` warnings and the netlist keeps the counter (cell count well above zero).
- [ ] **Step 4: Commit** `"SV example: AXI4-Lite through axil_if"`.

### Task 4: VHDL tooling from `vhdl-2008`

**Files:**
- Modify: `vsg.yml`, `scripts/gen_vhdl_ls.py`, `scripts/mk/lint.mk`, `scripts/mk/tools/ghdl.mk`, `template.core` (VHDL part)

**Interfaces:**
- Produces: `make lint-vhdl` runs GHDL analysis and then `vsg` (a style violation fails it); `gen_vhdl_ls.py` maps project RTL to library `rtl_lib`.

- [ ] **Step 1:** Diff each file between AES's fork point (`f543ea4`) and `e1db0d9`; apply only the generic changes (vsg rules, the `rtl_lib` mapping, vsg wiring in lint) onto the Task 1 versions. Do not take AES RTL or VHDL file lists. Compare the HDLAutoDoc pin in `e1db0d9` (`8011f97`) with AES `main`'s v3.13.0 using `git merge-base --is-ancestor` and note which is newer for Task 7.
- [ ] **Step 2: Test.** Verify loop with `L=vhdl`: `make lint-vhdl` exits 0; add a deliberate style violation to `src/NAME_core.vhd` and it exits non-zero; `make lsp` produces a vhdl_ls config naming `rtl_lib`.
- [ ] **Step 3: Commit** `"VHDL tooling: real vsg lint, rtl_lib mapping"`.

### Task 5: Testbench entry points

**Files:**
- Create: `tb/cocotb/NAME_top_cocotb_top.sv` (flat wrapper around the interface top, as AES's `aes_top_cocotb_top.sv`), `tb/cpp/NAME_top_cpp_flat.sv`
- Modify: `tb/cocotb/Makefile` (AES version, un-specialised, keeping the template's VHDL/GHDL branch via `tb/cocotb/vhdl/NAME_cocotb_top.vhd`), `tb/native/sv/NAME_tb.sv` (instantiates `axil_if`), `tb/cpp/NAME_tb.cpp`, `tb/vunit/run.py` (RTL list from Bender `rtl_vhdl`), `tb/cocotb/test_NAME.py` if port names changed

**Interfaces:**
- Produces: `make sim` (VUnit+GHDL), `make sim FRAMEWORK=cocotb SIM=ghdl|verilator|icarus`, `make sim-native` (NVC for VHDL, Verilator for SV), `make sim-cpp` all pass against the counter.
- Consumes: Task 3's top ports; Task 1's sim dispatcher.

- [ ] **Step 1:** Add the SV flat wrappers (cocotb and Verilator C++ cannot see interface ports) and update the SV benches to the new top.
- [ ] **Step 2:** Un-specialise `tb/cocotb/Makefile` (71 `aes` mentions) and keep the valid `FRAMEWORK`/`SIM`/`TOPLEVEL_HDL` combination guard.
- [ ] **Step 3: Test.** Verify loop: `make sim` (vhdl), `make sim FRAMEWORK=cocotb SIM=ghdl` (vhdl), `make sim FRAMEWORK=cocotb SIM=verilator` (sv), `make sim-native` for both, `make sim-cpp` (sv): each passes. Flip one expected value in `test_NAME.py` and the cocotb run fails; revert.
- [ ] **Step 4: Test, Icarus** (Review Focus 5). `make sim FRAMEWORK=cocotb SIM=icarus TOPLEVEL_HDL=sv`: if it passes, add it to the smoke test; if not, record the failure reason in `CLAUDE.md` under the SV register-file note and leave it out of the smoke test.
- [ ] **Step 5: Commit** `"Testbenches target the interface-based top"`.

### Task 6: pyuvm testbench

**Files:**
- Create: `tb/cocotb/pyuvm/{__init__.py,NAME_golden_model.py,NAME_regs.py,NAME_top_env.py,NAME_top_sequences.py,test_NAME_regs.py,test_NAME_top.py}` (mirror AES's `tb/cocotb/aes_pyuvm/`; directory name stays neutral)
- Modify: `tb/cocotb/Makefile` (select the pyuvm modules), `requirements.txt` if pyuvm/cocotbext-axi are not yet pinned

**Interfaces:**
- Produces: `class CounterModel` in `NAME_golden_model.py` with `reset()`, `write(addr: int, data: int)`, `pulse()`, `read(addr: int) -> int` (enable, increment step, saturation, reset_count); register accessors in `NAME_regs.py` that use the generated `out/regs/c` addresses or the generated Python/TOML map, not hard-coded offsets; tests `test_NAME_regs`, `test_NAME_top`, and `TestOverlappedRegisterAccess` (several AXI4-Lite transactions in flight, every value read back; fails if the decode stage becomes combinational again).

- [ ] **Step 1:** Write the golden model and the test classes first; run, see them fail for lack of env.
- [ ] **Step 2:** Implement env, sequences and regs following AES's structure.
- [ ] **Step 3: Test.** Verify loop: `make sim FRAMEWORK=cocotb SIM=verilator TOPLEVEL_HDL=sv` and `... SIM=ghdl TOPLEVEL_HDL=vhdl` run the pyuvm tests and pass. Negative controls: make the golden model off by one saturation value, and in a copy remove the decode registration from `gen_regs.py`; each makes the relevant test fail.
- [ ] **Step 4: Commit** `"Add pyuvm testbench for the counter top"`.

### Task 7: Documentation pipeline

**Files:**
- Modify: `submodules/HDLAutoDoc` (pin; newer of AES `main`'s v3.13.0 and `vhdl-2008`'s `8011f97`, per Task 4 step 1), `docs/conf.py`, `scripts/mk/docs.mk` (if Task 1 left gaps), `.gitignore` (generated docs pages)
- Delete: template-owned `docs/_static/*` and `docs/_templates/*` that the tool's conf now supplies (as AES did; keep the generated-pages mechanism)
- Modify: module-header comments in `src/sv/NAME_*.sv` and `src/vhdl/NAME_*.vhd` where needed to satisfy the Global Constraints on HDL AutoDoc

**Interfaces:**
- Produces: `make html`, `make pdf`, `make doc`, `make coverage`, `make test-autodoc` working for both languages.

- [ ] **Step 1:** Update the submodule pin and port `docs/conf.py` (wrapper that `exec`s the tool's conf, adds `sphinxcontrib.rsvgconverter`).
- [ ] **Step 2: Test.** Verify loop for both languages: `make html SCHEMATICS=1` exits 0 with no Sphinx warnings about unbalanced backticks or nested indentation; the Overview lists `NAME_top` and `NAME_core` (the hierarchy sees both); `make coverage` exits 0; `make test-autodoc` passes.
- [ ] **Step 3: Commit** `"Docs: autodoc.mk pipeline, HDLAutoDoc pin"`.

### Task 8: Implementation flow defaults

**Files:**
- Create: `synth/constraints/NAME.lpf` (pins unconstrained, as `synth/constraints/aes_impl_top.lpf` in AES `791ad7c`)
- Modify: `scripts/mk/tools/nextpnr.mk`, `scripts/mk/impl.mk`

**Interfaces:**
- Produces: `make impl` (ECP5 25F CABGA256 speed 8 by default, mirroring AES) implements `IMPL_TOPLEVEL=<<NAME>>_top` with `--lpf-allow-unconstrained`, then `check_nextpnr_timing.sh` gates on `IMPL_FREQ_MHZ`; reports land in `out/reports/yosys/`.

- [ ] **Step 1:** Choose the `IMPL_FREQ_MHZ` default by running `make impl` for the counter and picking a round figure with margin; record the measured value only in the commit message.
- [ ] **Step 2: Test.** Verify loop (sv): `make impl` produces a bitstream and the timing check passes. `make impl IMPL_TOPLEVEL=<another module>` also runs (so a metrics wrapper can be added later). `make impl IMPL_FAMILY=ice40 IMPL_DEVICE=hx8k IMPL_PACKAGE=ct256` runs once; if it fails, leave it listed as untested in `help`.
- [ ] **Step 3: Test, VHDL.** `make impl TOPLEVEL_HDL=vhdl`: if it works via the ghdl-yosys-plugin, keep it; otherwise make the target print a clear "SV only" message and say so in `CLAUDE.md`.
- [ ] **Step 4: Commit** `"ECP5 implementation flow with unplaced-pin top"`.

### Task 9: CI, smoke test, prose and sweep

**Files:**
- Modify: `.github/workflows/ci.yml`, `.github/workflows/docs.yml`, `scripts/smoke_test.sh`, `CLAUDE.md`, `README.md`, `RELEASE_NOTES.md`

**Interfaces:**
- Consumes: every target from Tasks 1-8.

- [ ] **Step 1:** CI: port AES's jobs (lint, sim matrix, synth, impl, test-autodoc, `regs` drift diff, smoke-test vhdl/sv) with the template's names; drop anything tied to AES.
- [ ] **Step 2:** `smoke_test.sh`: add rows for the pyuvm run, `make impl` (sv), and an init with name `my_ip2` per language (Review Focus 1).
- [ ] **Step 3:** `CLAUDE.md`: rewrite from the template's version using AES's generic sections (Makefile layout, adding a backend, toolchain notes, regs, docs pipeline, interface notes); omit all cipher and AES-specific sections. Update `README.md` and add a `RELEASE_NOTES.md` entry (version bump is your call).
- [ ] **Step 4: Test, sweep.** `git grep -iI aes -- . ':!docs/superpowers'` is empty.
- [ ] **Step 5: Test, full.** `scripts/smoke_test.sh vhdl` and `scripts/smoke_test.sh sv` finish with every row PASS; `.venv/bin/python3 -m pytest scripts/tests -q` and `make test-autodoc` pass.
- [ ] **Step 6: Commit** `"CI, smoke test and docs for the synced template"`.
