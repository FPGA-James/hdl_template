# Sync the template from the AES project — Design Spec

## Intent

This template (`hdl_template`) was forked into the AES project (`/Users/james/Workspace/AES`) on 2026-08-31. AES has since improved the template's generic machinery a great deal. This work carries those improvements back so new projects start from them, while the template stays a **VHDL and SystemVerilog** template with a `NAME` placeholder and no AES content.

The template has not changed since the fork (only `.claude/settings.json` exists solely here), so this is a one-way port. There are no merge conflicts to resolve, only a choice of what to carry and how to un-specialise it.

## Sources

| Source | Commit | Role |
|---|---|---|
| AES `main` | `791ad7c` | SystemVerilog flow, build system, docs pipeline, register generation, testbench style. Reference for everything generic. |
| AES `vhdl-2008` | `e1db0d9` | A parked VHDL-2008 port of an *older* AES (forked from AES `main` on 2026-10-25, before the Makefile split, cipher v2 and the ECP5 flow). Mined only for VHDL-side tooling. |

## Goals

1. **Build system.** Adopt AES's `scripts/mk/` layout (one file per flow, one per tool backend under `scripts/mk/tools/`, a registry in `core.mk`, the `unknown-tool` error, help stubs). The template's top-level `Makefile` becomes the thin entry point that decides which tools run, through its variables (`FRAMEWORK`, `SIM`, `TOPLEVEL_HDL`, `SYNTH_TOOL`, `IMPL_TOOL`, `NATIVE_SIM`, `IMPL_FAMILY`, …). Adding a backend means adding one file in `scripts/mk/tools/`.
2. **ECP5 implementation flow** (Yosys + nextpnr, `check_nextpnr_timing.sh`, `IMPL_PNR_OPT`, reports into `out/reports`) comes across as one selectable backend, not a hard-wired flow.
3. **Both languages stay first class.** Everything in goal 1–2 and below works for `TOPLEVEL_HDL=vhdl` and `TOPLEVEL_HDL=sv`, after `make init` for either.
4. **Example design in AES's style.** The template's example (`NAME_pkg`, `NAME_core`, `NAME_top`, the pulse counter) is rewritten, not replaced by AES files:
   - SystemVerilog: AXI4-Lite through an `axil_if` interface (as in `aes_top.sv`), plain `.s_axil(s_axil)` connections.
   - VHDL: the equivalent hdl-modules `axi_lite_m2s_t`/`axi_lite_s2m_t` records (already used by the template).
   - A pyuvm testbench for `NAME_top` (env, sequences, golden model, register model, as under `tb/cocotb/aes_pyuvm/`), alongside the existing cocotb, VUnit, native and C++ benches.
5. **Generic improvements** carried over: `gen_regs.py` (SV regblock path, `_make_sv_synthesizable`, register-decode stage registration, auto-wiring), `gen_filelist.sh`, `init_project.sh`, the `autodoc.mk`-based docs pipeline (`docs.mk`, `docs/conf.py`, Testbenches/Build/Coverage pages, Mermaid), `tb/cocotb/Makefile` (un-specialised), CI, `smoke_test.sh`, `scripts/tests/test_gen_regs.py` additions.
6. **VHDL tooling from `vhdl-2008`**: the rewritten `vsg.yml`, `lint-vhdl` actually running `vsg`, the `gen_vhdl_ls` fix (project RTL mapped to `rtl_lib`), the init guard and smoke-test fixes, the VHDL cocotb flattening wrapper pattern, the NVC native bench, `template.core` changes, and the HDLAutoDoc pin if newer.
7. Documentation (`CLAUDE.md`, `README.md`, `RELEASE_NOTES.md`) describes the new template, generically.

## Non-goals

- No AES RTL, register map, testbenches, references, plans/specs or numbers (250 MHz, 256 MHz, LUT counts) in the template.
- No self-checking implementation wrapper (`aes_impl_top` equivalent) and therefore no `make impl-sim`. The owner may add a metrics wrapper later; the impl flow must not block that (a different `IMPL_TOPLEVEL` must work). `axis_if` is not shipped because the counter example has no stream.
- No new tool backends beyond those AES already has (Questa/Vivado stay as the documented extension recipe).
- No syncing mechanism for the future; this is a one-off port.
- AES and its branches are not modified.

## Anti-goals (would make it a failure even if it builds)

- Any `aes` (any case) left in the template tree outside this spec and git history.
- A regression in `make init NAME=<x> TOPLEVEL_HDL=vhdl|sv`, or an SV-only user needing VHDL tools (or vice versa).
- Hard-wiring a tool: changing `SYNTH_TOOL`/`IMPL_TOOL`/`NATIVE_SIM`/family from the top-level `Makefile` or command line must be enough to switch backends.
- Features that pass only for SV. AES `main` has no VHDL RTL, so the VHDL side of every new flow must be verified in the template itself.

## Constraints and decisions

Decided by the owner:
- Use the new `mk` format; tooling chosen by the template's top-level `Makefile`.
- ECP5 flow may be used, as a selectable backend.
- All `aes` files are project-specific (and may have been generated from the template).
- Keep SystemVerilog and VHDL; use `vhdl-2008` to keep the VHDL side current.
- Example design adopts AES's interface style plus the pyuvm testbench.
- Work on a branch of `hdl_template`; SV is the reference and VHDL is written to match it.
- Self-checking wrapper deferred.

Calls made while writing this (change any you disagree with):
- Branch name `sync-from-aes`, in reviewable commits (build system, regs/docs, example design + testbenches, VHDL tooling, docs).
- The example stays the pulse counter (`pulse_i`, `conf`/`command`/`status` registers) so existing register tests keep their meaning.
- Only `axil_if.sv` is added to the template's SV sources.
- `impl` default top is `NAME_top` with unplaced pins (`--lpf-allow-unconstrained`), implemented to get area/Fmax; `make impl` still gates on `IMPL_FREQ_MHZ`, whose default is a builder choice suited to a counter.
- The register-decode registration in `gen_regs.py` (one extra cycle on reads/writes, added in AES for 250 MHz) is carried over, together with the overlapped-access test ported to the counter, because it is generator behaviour every project would otherwise have to re-derive.
- Top-level defaults mirror AES's `Makefile` unless a template reason says otherwise.

## Constraints from the code (for the builder)

- Placeholder: the template uses `<<NAME>>` in file contents and `NAME_` in file names; AES's generic files have `aes` substituted in. Each file taken from AES must be turned back into the template's placeholder form.
- Source layout: template ships `src/sv/` and `src/vhdl/`; `make init` flattens to `src/`. Bender targets `rtl_vhdl`/`rtl_sv`/`gen_*`/`tb_vhdl` must keep working both pre- and post-init. AES's `gen_filelist.sh` already handles the pre-init duplicate-module case.
- Interface-typed SV ports and Yosys: pass the interface instance plain (`.s_axil(s_axil)`), never with a modport selected (documented in AES `CLAUDE.md`).
- HDL AutoDoc: `parse_hierarchy.py` matches `#(...)` up to the first `)`; instances with parenthesised parameter overrides are invisible, so pass parameters by position. A port's description is only the single comment line directly above it.
- macOS `DYLD_LIBRARY_PATH` prefix for Sphinx (`libxcb`) must stay.
- Submodules: the template tracks six (`HDLAutoDoc`, `axi`, `common_cells`, `common_verification`, `Interfaces`, `hooks`); AES tracks only `HDLAutoDoc` in its tree. Leave the other five alone unless a task needs them.

## Success criteria

On the `sync-from-aes` branch, from a clean checkout:
1. `scripts/smoke_test.sh vhdl` and `scripts/smoke_test.sh sv` pass every step (regs, lsp, lint, every testbench flow incl. pyuvm, synth, html, coverage).
2. `make impl` runs for the example and the timing check passes at the default frequency (SV; and VHDL via the ghdl-yosys-plugin if that path is supported — if not, document it).
3. `make test-autodoc` and the `scripts/tests` pytest suite pass.
4. Switching tools works by variable only (e.g. `SYNTH_TOOL=`, `IMPL_TOOL=`, `NATIVE_SIM=`, `IMPL_FAMILY=ice40`); an unregistered tool prints the `unknown-tool` list.
5. `grep -ri aes` over tracked files (excluding this spec) is empty.
6. CI workflow updated and consistent with the Makefile.

## Left to the builder

Task ordering, commit granularity, the exact `IMPL_FREQ_MHZ` default, which VHDL tooling from `vhdl-2008` is still relevant after the Makefile rewrite, whether `RELEASE_NOTES.md` gets a version bump, how to write the VHDL pyuvm flattening wrapper, and the contents of the counter's pyuvm golden model.
