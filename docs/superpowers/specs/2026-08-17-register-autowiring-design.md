# Register auto-instantiation & auto-wiring — design

Date: 2026-08-17
Status: Approved (via brainstorming dialogue), pending implementation plan

## Problem

`<<NAME>>_top.vhd` today hand-wires the generated register file's typed
record fields (`regs_down.conf.enable`, `regs_up.status.pulse_count`, ...)
to `<<NAME>>_core`'s ports one at a time. `<<NAME>>_top.sv` has no
register integration at all — it's a stub with a literal
`// TODO: Instantiate your register block here` and a hand-rolled,
unconnected AXI4-Lite port list.

Goal: a single script generates the register file *and* the
register↔core wiring in `_top`, for both VHDL and SV, from the same
`regs/<name>_regs.toml`.

## Toolchain

- **VHDL** (unchanged): `hdl_registers`'s existing three VHDL generators
  (`VhdlRegisterPackageGenerator`, `VhdlRecordPackageGenerator`,
  `VhdlAxiLiteWrapperGenerator`) — register constants package, typed
  record package (`regs_down_t`/`regs_up_t`), AXI-Lite wrapper entity.
  Depends on `hdl-modules`'s `axi_lite`/`register_file` VHDL packages,
  already a Bender dependency.
- **SV** (new): `hdl_registers.generator.systemverilog.axi_lite.register_file
  .SystemVerilogAxiLiteGenerator`, called with `create(flatten_axi_lite=True)`.
  Internally converts the register list to a SystemRDL model and hands it to
  **PeakRDL-regblock** (new Python dependency: `peakrdl-regblock`) to emit
  the SystemVerilog. `flatten_axi_lite=True` produces discrete AXI-Lite
  signals (`s_axil_awvalid`, `s_axil_awaddr`, `s_axil_awprot`, ...) instead
  of a bundled `axi4lite_intf` SV interface — verified empirically; no
  interface type to vendor, and the generated module's bus side is left for
  the user to wire to their own interface convention by hand, same as today.
- Both languages expose the register↔hardware boundary as a typed
  struct/record the auto-wiring step walks: VHDL `regs_down_t`/`regs_up_t`,
  SV `hwif_out`/`hwif_in` (auto-named per project, e.g. `demo__out_t`/
  `demo__in_t`).
- **Verified constraint**: the SV generator only translates register modes
  `r`/`w`/`r_w` — not `wpulse`, not signed integers. This project's own
  `command` register (mode `wpulse`) hits this and is addressed below.

## Register map change

`regs/NAME_regs.toml`:
- Rename `command.reset_counter` → `command.reset_count` (aligns the field
  name with the existing `reset_count_i` core port under the naming
  convention below — this is the only field in the current map that
  doesn't already match).
- Change `command` mode `wpulse` → `w`, applied to **both** languages
  (single mode per field, no per-language asymmetry). Plain `w` fields
  hold their written value with no auto-clear and no companion strobe
  signal (verified: the generated struct for a `w` field is just
  `{ logic value; }`, nothing else) — this is a real behavior change, not
  just a rename, addressed in `_core` below.

All other fields (`conf.enable`, `conf.increment`, `status.enabled`,
`status.pulse_count`) already fit the naming convention and use modes
(`r_w`/`r`) SV supports natively — no changes needed.

## `_core` RTL change

Because `command.reset_count` no longer auto-clears, `reset_count_i` is now
a held level (stays `1` until software writes it back to `0`) rather than a
one-cycle pulse. `NAME_core.vhd`'s and `NAME_core.sv`'s existing logic
(`elsif reset_count_i = '1' then count_r <= 0`) would clear the counter on
every cycle the bit stays high, not just once.

Fix, mirrored in both languages: add a one-cycle rising-edge detector on
`reset_count_i` (register the previous value; internal pulse =
`current AND NOT previous`), and switch the clear condition to check that
internal pulse instead of the raw port. Timing at the port boundary is
unchanged (a rising edge still produces exactly one clear cycle), so the
existing VUnit/cocotb/native testbenches — which already hold the signal
high for exactly one cycle before deasserting — should continue to pass
unmodified.

## Auto-wiring mechanism

### Naming convention (strict, no TOML annotation)

For each register field, the expected core port name is
`<field leaf name>_i` (fields under `w`/`r_w` registers — host writes,
core receives) or `<field leaf name>_o` (fields under `r` registers — core
drives, host reads). Direction comes from the register's mode; no
per-field metadata needed.

### Port discovery

The core's port list is parsed directly from `<<NAME>>_core.vhd`/`.sv`
(entity/module port declarations) — not from a separately declared list.

### Marker-delimited rewrite in `_top`

`<<NAME>>_top.vhd`/`.sv` stays a real, hand-edited file. The generator
looks for a marker comment pair:

```vhdl
-- BEGIN AUTOGEN REGISTERS
...
-- END AUTOGEN REGISTERS
```

(SV: `// BEGIN AUTOGEN REGISTERS` / `// END AUTOGEN REGISTERS`) and
replaces only the text between them with the register-instantiation +
core port-map block. Everything outside the markers — bus-side wiring to
the user's own interface, any additional logic — is left untouched.
Re-running generation is idempotent (replacing the same region produces
the same output for an unchanged register map).

### Type bridging

- **VHDL**: `bit` fields → `std_logic`, direct connect. `bit_vector`
  fields → `unsigned` in the generated record, so the connection is
  wrapped in an explicit `std_logic_vector(...)`/`unsigned(...)` cast when
  the core port is a plain vector (same pattern used to fix
  `NAME_top.vhd`'s `pulse_count` connection earlier this session).
  `integer` fields → direct connect (compatible integer subtypes, no cast
  needed).
- **SV**: struct fields are already raw `logic`/`logic [N:0]`, matching
  `_core`'s own port types directly — no casts needed in any case.

### Error handling

Every register field must resolve to a matching core port, or generation
fails with a clear error naming the unmatched field (and which side —
missing on the core, or a type it doesn't know how to bridge). The reverse
is not required: `_core` may have ports the generator never touches (e.g.
`clk`, `rst_n`, `pulse_i`) — anything outside the register struct is left
for the user to wire by hand, outside the marker region.

## Driver

Single script: extend the existing `scripts/gen_regs.py` (not a new file)
with two responsibilities per language, run together from `make regs`:
1. Register file generation (as today for VHDL; new SV path as above).
2. Top-level auto-wiring (new, both languages) — runs after generation,
   rewrites the marker region in `_top`.

Language is selected the same way the rest of the Makefile already infers
it post-`make init` (whichever of `src/*.vhd` / `src/*.sv` is present).

## Testing

- **Integration**: `scripts/smoke_test.sh` already runs `make regs` →
  `lint` → every testbench flow → `synth` for both languages after
  `make init`. Wrong port names or type mismatches fail compilation;
  wrong pulse-detection logic fails the `test_reset_count`/native-tb reset
  checks. This is strong end-to-end evidence the wiring is correct.
- **Unit** (new): a pytest suite under `scripts/tests/` covering the new
  Python logic in isolation — leaf-name/direction matching, the
  type-bridging decision per VHDL field type, marker-region text
  replacement (idempotent re-run; content outside markers preserved), and
  the unmapped-field error path. No toolchain required — just the
  `hdl_registers` parse result and fixture port lists.
- No changes needed to the three existing testbenches themselves.

## Out of scope

- Changing the SV top's AXI-Lite bus-side port convention beyond what
  `flatten_axi_lite=True` already produces — the user wires the generated
  register module's bus-side ports to their own interface declaration by
  hand, same as today's VHDL flow.
- Any register mode beyond what SV's generator supports today (`r`/`w`/
  `r_w`) — if a future register needs `wpulse`-equivalent behavior, the
  edge-detect-in-`_core` pattern established here is the template to
  follow, not a register-file-level feature.
