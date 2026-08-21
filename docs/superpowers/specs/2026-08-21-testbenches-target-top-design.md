# Testbenches target `_top` via AXI-Lite — Design Spec

## Goal

Every testbench in this template — VUnit, cocotb, native (VHDL and SystemVerilog), and a new C++ path — instantiates `<name>_top` and drives it over its AXI-Lite slave interface, instead of instantiating `<name>_core` and poking its plain ports directly. This exercises the auto-wired register integration (the feature built in the `register-autowiring` branch) end-to-end, in every simulation path, not just the pytest suite that tests the generator itself.

## Non-goals

- No change to `_core`'s RTL or its port list.
- No change to the register auto-wiring generator (`scripts/gen_regs.py`) itself, except a small addition described below (an SV register-address package) needed so SV testbenches can address registers without hardcoding offsets.
- Not adding real BFMs for `native-sv` or the new `cpp` path in this round — hand-rolled drivers are the deliberate, confirmed-necessary choice here (see "Why native-sv is hand-rolled, not a third-party BFM" below); a real BFM can replace them later without touching anything else in this design (the hand-rolled drivers are given a narrow, self-contained module/class boundary specifically to make this swap cheap).

## Current state (what's being replaced)

Every existing testbench instantiates `<name>_core` directly and drives its plain ports (`enable_i`, `increment_i`, `reset_count_i`, reads `enabled_o`, `pulse_count_o`). This was a deliberate original design choice — see `tb/cocotb/Makefile`'s own comment: *"The top-level for cocotb tests is `<<NAME>>_core` (not `_top`), so the AXI-Lite register block is not involved and no hdl-modules dependency is needed."* Four testbenches carry this pattern: `tb/vunit/vhdl/NAME_tb.vhd`, `tb/cocotb/test_NAME.py` (+ `tb/cocotb/Makefile`), `tb/native/vhdl/NAME_tb.vhd`, `tb/native/sv/NAME_tb.sv`. All four exercise the same five logical scenarios: `count_up`, `increment_step` (cocotb only), `saturation`, `reset_count`, `disable`/`test_disable_holds_count`.

## Architecture

Every testbench instantiates `<name>_top`, drives the AXI-Lite slave port with a per-framework driver (table below), and re-expresses the same five scenarios as register reads/writes instead of direct port stimulus:

| Path | Driver | Status |
|---|---|---|
| VUnit | `hdl_registers`' generated VHDL read/write package (field-typed procedures) + `hdl-modules`' `axi_lite_master` BFM entity underneath it | both already exist as dependencies; the read/write package generator is currently unused — this design turns it on |
| cocotb (VHDL-via-GHDL, SV-via-Verilator/Icarus) | `cocotbext-axi`'s `AxiLiteMaster` | new Python dependency |
| native-vhdl | OSVVM's `Axi4LiteManager` VC | new dependency, installed via `nvc --install osvvm` |
| native-sv | hand-rolled AXI-Lite driver tasks (`tb/native/sv/axi_lite_driver_pkg.sv`, new file) | confirmed necessary — see below |
| cpp (new) | hand-rolled AXI-Lite driver class (`tb/cpp/axi_lite_driver.hpp`, new file) | idiomatic for Verilator C++ harnesses |

### Why native-sv is hand-rolled, not a third-party BFM

`pulp-platform/axi`'s `axi_test.sv` was investigated as a real candidate (it's Bender-fetchable exactly like `hdl-modules` already is, and has an `axi_lite_rand_master` class with clean `write()`/`read()` methods). It does not work under Verilator: compiling the file with Verilator 5.039 in `--binary --timing` mode produces `%Error-UNSUPPORTED: virtual interface never assigned any actual interface` on the *unused* full-AXI classes (`axi_driver`, `axi_rand_master`, `axi_rand_slave`, all typed `virtual AXI_BUS_DV`) — Verilator's class analysis is whole-compilation-unit, so declaring `axi_lite_rand_master` (which does work fine as an isolated class) forces the whole `package axi_test` — including the classes never instantiated — through Verilator's stricter virtual-interface elaboration. This was verified directly (not assumed): a minimal spike testbench instantiating `AXI_LITE_DV` + `axi_lite_rand_master` against a trivial slave DUT, compiled with the exact toolchain this project uses, reproduced the error. It also explains a fact already visible in pulp-platform's own repo: their Verilator lint/elaboration CI (`scripts/run_verilator.sh`, `scripts/run_yosys_slang.sh`) explicitly excludes the `simulation` Bender target (where `axi_test.sv` lives) — they don't claim Verilator support for this file either.

No other well-established, non-UVM, Verilator-compatible open-source AXI-Lite SV BFM was found. UVM-based options exist but are a much heavier dependency than fits a "native, framework-less" testbench (this template's `native` path exists specifically to have zero framework/verification-library dependency beyond the simulator itself, apart from what this design already adds for VUnit/cocotb/native-vhdl).

### Register addressing

Tests need register byte addresses now, not port names.

- **VHDL** (VUnit, native-vhdl): use the already-generated `<name>_regs_pkg.vhd`, which has a `<name>_register_range` enumeration (`demo_conf`, `demo_command`, `demo_status`, ...) — the byte address of register `R` is `4 * <name>_register_range'pos(<name>_R)` (this is exactly the computation `hdl_registers`' own generated read/write package does internally — see below). No new generator needed.
- **C++**: `#include` the already-generated C header (`out/regs/c/<name>_regs.h`) directly — it already has `#define <NAME>_<REG>_ADDR` (or equivalent) macros; C headers are plain enough that C++ can include them with no changes.
- **SV** (cocotb-SV, native-sv): the generated SV package (`out/regs/sv/<name>_register_file_axi_lite_pkg.sv`) currently only exposes `hwif_in`/`hwif_out` struct types and bus-width localparams — no address offsets. `` `include ``-ing the generated C header directly was considered and **ruled out by actually generating one and checking**: it contains a `typedef struct { uint32_t ...; } <name>_regs_t` block — `uint32_t` isn't a defined type in SV, so this fails to compile as-is, not just theoretically. The real fix: `scripts/gen_regs.py` gets a new function generating a small, address-only SV package, e.g. (verified: generated for this project's real register map, compiled and run cleanly under both Verilator 5.039 and Icarus, addresses came out correct — `conf=0 command=4 status=8`):
  ```systemverilog
  package demo_regs_addr_pkg;
      localparam int unsigned demo_conf_addr = 4 * 0;
      localparam int unsigned demo_command_addr = 4 * 1;
      localparam int unsigned demo_status_addr = 4 * 2;
  endpackage
  ```
  Generated by iterating `register_list.register_objects` with an index, exactly mirroring the byte-address computation the VHDL path already uses. Written to `out/regs/sv/<name>_regs_addr_pkg.sv`, called from `generate_sv()` alongside the existing register-file generation. **Naming is deliberately lowercase** (`demo_conf_addr`, not `DEMO_CONF_ADDR`) — matching this project's own already-established VHDL constant convention (`<name>_regs_pkg.vhd`'s `demo_conf`/`demo_command`/`demo_status` are lowercase too) and, critically, making the names directly usable from a `<<NAME>>`-template-substituted testbench file: `<<NAME>>_conf_addr` becomes `myproject_conf_addr` after `make init NAME=myproject`, matching the freshly-generated package exactly. An uppercased name (as C header macros use, via `hdl_registers`' own `.upper()` convention) would NOT be reachable this way, since `<<NAME>>` substitution is a literal, case-preserving text replacement — it cannot produce `MYPROJECT_CONF_ADDR` from a template containing `<<NAME>>_CONF_ADDR` typed pre-init as `NAME_CONF_ADDR` unless the user's project name happens to already be all-caps.
- **C++**: for the same reason, don't reference the C header's uppercase `#define` macros by name in `tb/cpp/NAME_tb.cpp` — instead use `offsetof()` against the header's `<name>_regs_t` struct type, whose field names are the bare, un-prefixed, un-cased register names (`conf`, `command`, `status`) and whose type name (`<name>_regs_t`) is lowercase-project-name-prefixed, both directly `<<NAME>>`-substitutable: `offsetof(<<NAME>>_regs_t, conf)` becomes `offsetof(myproject_regs_t, conf)`, matching the real generated header exactly, with no casing mismatch possible.

### `pulse_i`

`_top` has a `pulse_i` input port that isn't wired to anything internally (a pre-existing, unrelated orphan port, not something this design fixes). Every testbench instantiating `_top` needs to tie it to `'0'`/`1'b0` — the five test scenarios don't exercise it, so a constant tie-off is sufficient; note this consistently in each testbench rather than leaving it dangling (VHDL requires driving an `in` port anyway).

## Per-framework technical design

### VUnit

`hdl_registers.generator.vhdl.simulation.read_write_package.VhdlSimulationReadWritePackageGenerator` (installed, currently never called by `scripts/gen_regs.py`) generates `<name>_register_read_write_pkg.vhd` with one procedure per register/field, e.g. (verified by actually running the generator against this project's real register map):

```vhdl
procedure write_demo_conf_enable(
    signal net : inout network_t;
    value : in std_ulogic;
    base_address : in unsigned(32 - 1 downto 0) := (others => '0');
    bus_handle : in bus_master_t := register_bus_master
);
procedure read_demo_status_pulse_count(
    signal net : inout network_t;
    value : out integer;
    base_address : in unsigned(32 - 1 downto 0) := (others => '0');
    bus_handle : in bus_master_t := register_bus_master
);
```

These call VUnit's own `vunit_lib.bus_master_pkg.write_bus`/`read_bus` internally, addressed via `register_bus_master`'s message-passing network (`net`). That network is driven by an actual bus-master verification component wired to the DUT's real signals — `hdl-modules`' `axi_lite_master` entity (`modules/bfm/sim/axi_lite_master.vhd`, already fetched as part of the existing `hdl_modules` Bender dependency), whose default `bus_handle` generic is `register_bus_master` — the same default the generated procedures use, so no explicit wiring of the handle is needed. The testbench instantiates this entity once, port-mapped directly to `_top`'s `s_axi_m2s`/`s_axi_s2m` ports (both are `hdl-modules`' own `axi_lite_pkg.axi_lite_m2s_t`/`s2m_t` types, so this is a same-type port map, no bridging needed).

`gen_regs.py`'s `generate_from_toml` gets a new call (VHDL branch only): `VhdlSimulationReadWritePackageGenerator(register_list=register_list, output_folder=GEN_VHDL).create()`.

`tb/vunit/run.py` needs new libraries compiled in: `axi_lite` (`hdl-modules` `modules/axi_lite/src/axi_lite_pkg.vhd`), `register_file` (`hdl-modules` `modules/register_file/src/register_file_pkg.vhd`, `axi_lite_register_file.vhd`, and — new — `modules/register_file/sim/register_operations_pkg.vhd`, which defines the `register_bus_master` constant), plus `hdl-modules`' `axi_lite_master` BFM (`modules/bfm/sim/axi_lite_master.vhd`), plus the generated `<name>_top`-adjacent packages (`<name>_regs_pkg.vhd`, `<name>_register_record_pkg.vhd`, `<name>_register_file_axi_lite.vhd`, and the new `<name>_register_read_write_pkg.vhd`), plus `<name>_top.vhd` itself (replacing `<name>_core.vhd` in `rtl_lib`).

### cocotb (VHDL-via-GHDL, SV-via-Verilator/Icarus)

`cocotbext-axi`'s `AxiLiteMaster`, verified against its real source (`alexforencich/cocotbext-axi`, PyPI package `cocotbext-axi`, latest `0.1.28`, actively maintained):

```python
from cocotbext.axi import AxiLiteBus, AxiLiteMaster

axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi"), dut.clk, dut.rst_n, reset_active_level=False)
...
await axil.write(address, data)              # data: bytes/bytearray
result = await axil.read(address, length)    # result.data: bytes
```

Two verified details that matter: (1) `reset_active_level=False` is required — the library defaults to active-high, and this project's reset is `rst_n` (active-low); getting this wrong would silently hold the driver in reset forever. (2) `AxiLiteBus.from_prefix(dut, "s_axi")` auto-discovers `s_axi_awvalid`/`s_axi_awready`/etc. via a `name + "_" + signal` convention — an exact match for this project's signal names — and `awprot`/`arprot` are already declared `optional_signals` inside the library itself, so the VHDL side (which has no AWPROT/ARPROT on `_top`'s ports) needs no special handling.

`tb/cocotb/Makefile` needs, per language: VHDL branch adds `<name>_top.vhd` (replacing `<name>_core.vhd`) plus `hdl-modules`' `axi_lite_pkg.vhd`/`register_file_pkg.vhd`/`axi_lite_register_file.vhd` plus the generated VHDL register files, each needing correct GHDL library mapping (mirrors what `lint-vhdl`/`synth` already do via `HDL_MODULES`/`VHDL_AXI_LITE`/`VHDL_REG_FILE`, which this Makefile can now reuse). SV branch adds `<name>_top.sv` (replacing `<name>_core.sv`) plus the generated SV register file package + module. `requirements.txt` gets `cocotbext-axi`. The header comment explaining "AXI-Lite not involved" is deleted since it's no longer true.

### native-vhdl

OSVVM's `Axi4LiteManager` (`OSVVM/AXI4` repo, `Axi4Lite/src/Axi4LiteManager.vhd`; fetched transitively as part of `OsvvmLibraries` via `nvc --install osvvm`, which pins tag `2025.06a` — verified this is also the tag whose `Write`/`Read` procedures use plain VHDL-2008 signatures, not the VHDL-2019 "interface mode view" rewrite present in later OSVVM tags):

```vhdl
entity Axi4LiteManager is
  generic ( MODEL_ID_NAME : string := ""; tperiod_Clk : time := 10 ns; ... );
  port ( Clk : in std_logic; nReset : in std_logic;
         AxiBus : inout Axi4LiteRecType; TransRec : inout AddressBusRecType );
end entity;

-- from OSVVM-Common's AddressBusTransactionPkg (tag 2025.06):
procedure Write(signal TransactionRec : InOut AddressBusRecType; iAddr, iData : In std_logic_vector; StatusMsgOn : In boolean := false);
procedure Read(signal TransactionRec : InOut AddressBusRecType; iAddr : In std_logic_vector; variable oData : Out std_logic_vector; StatusMsgOn : In boolean := false);
```

No `TestCtrl`/`Configuration`/`AlertLog` ceremony is required — OSVVM's own test suite uses that structure for its *own* swappable test cases, but `Write`/`Read` only need the constrained `TransRec`/`AxiBus` signals and the instantiated entity; they can be called directly from an ordinary process, matching this project's existing native-testbench style. `library osvvm; context osvvm.OsvvmContext;` and `library osvvm_axi4; context osvvm_axi4.Axi4LiteContext;` are needed regardless (the Manager entity itself calls OSVVM's `Log`/`AlertIf` internally).

**`nReset` is vestigial in this version — verified by reading the full 1026-line `Axi4LiteManager.vhd` (tag `2025.06a`)**: the port is declared but never referenced anywhere in the architecture body (only `Clk`, `AxiBus`, `TransRec` are actually used). Polarity doesn't matter and there's no reset-release timing to coordinate with — tie it to `rst_n` directly for documentation/future-proofing, but don't expect it to affect the Manager's behavior, and don't spend implementation time debugging an apparent "reset does nothing" — that's expected, not a wiring bug.

`AxiBus`'s type (`Axi4LiteRecType`, with nested `WriteAddress`/`WriteData`/`WriteResponse`/`ReadAddress`/`ReadData` records, unconstrained `std_logic_vector` fields — verified field-by-field against `Axi4LiteInterfacePkg.vhd`) is a *different* type from `hdl-modules`' `axi_lite_m2s_t`/`s2m_t` that `_top`'s ports actually use. The testbench needs an explicit field-by-field bridge (plain concurrent signal assignments — e.g. `s_axi_m2s.write.aw.valid <= AxiBus.WriteAddress.Valid; AxiBus.WriteAddress.Ready <= s_axi_s2m.write.aw.ready;` and so on for all five channels), not a direct port map. This is mechanical, standard VHDL — the plan's task spells out every field pairing.

### native-sv

New file `tb/native/sv/axi_lite_driver_pkg.sv` — a small package with `automatic` tasks (`axil_write`, `axil_read`) taking the testbench's flat `s_axi_*` signals as `ref`/`output` arguments (no interface, no class, no virtual interface — exactly the constructs already confirmed to compile fine under Verilator, since this project's existing native-sv testbench already uses plain tasks). Each task drives one full AXI-Lite write or read transaction (AW+W concurrently via `fork`/`join`, then wait for B; or AR then wait for R) — this is a small, well-understood, single-beat protocol with no bursting to implement.

### cpp (new)

New files `tb/cpp/axi_lite_driver.hpp` (a small class wrapping the same write/read sequence, operating on the Verilated model's generated port members directly — `top->s_axi_awvalid = 1; top->eval(); ...`) and `tb/cpp/NAME_tb.cpp` (the actual test sequence, mirroring the five scenarios). Built via `verilator --cc --exe --build` — no bespoke Makefile, no external test framework, plain `assert`/`exit(1)` for failures matching the native testbenches' self-checking style.

## `make init` / file-type handling

`scripts/init_project.sh`'s content-substitution glob and file-rename glob both need `.cpp`, `.h`, `.hpp` added, or `tb/cpp/NAME_tb.cpp` (and the new driver header) survive `make init` un-renamed and with `<<NAME>>` still literally in them.

## Dependency changes

- `Bender.yml`: no new entry needed for OSVVM (installed via NVC, not Bender) or `cocotbext-axi` (pip). No new Bender dependency at all, in fact — `hdl-modules` (already present) covers VUnit/cocotb-VHDL, and native-sv/cpp are hand-rolled with no new library.
- `requirements.txt`: add `cocotbext-axi`.
- Document `nvc --install osvvm` as a one-time setup step, alongside NVC's own existing install instructions (README, CLAUDE.md).
- `scripts/gen_regs.py`: add the `VhdlSimulationReadWritePackageGenerator` call (VHDL branch of `generate_from_toml`).

## CI / smoke test

`scripts/smoke_test.sh`: VHDL row needs `nvc --install osvvm` before `sim-native`; SV row gets a new `sim-cpp` step. `.github/workflows/ci.yml`'s `smoke-test` job needs the same OSVVM install step added to its toolchain setup.

## Testing plan

- After each framework's testbench is ported, run it directly (not just trust that it compiles) — same verification discipline as the register-autowiring plan: real scratch-copy runs, real pass/fail output, not just "it builds."
- Full `scripts/smoke_test.sh` for both languages at the end, matching every prior feature's final verification gate in this repo.
- The new SV address-package generator function (see "Register addressing" above) gets the same TDD treatment as every other `scripts/gen_regs.py` change in this repo — unit tests in `scripts/tests/test_gen_regs.py` against a real parsed register list, not just the manual verification already done during design.

## Known residual gaps (documented, not solved by this design)

- `native-sv` and `cpp`'s hand-rolled drivers are not independently verified against a real AXI-Lite protocol checker (no assertions on illegal handshake sequences, no backpressure/delay randomization) — they drive and check the golden path this project's test scenarios need, nothing more. Swapping in a real BFM later (a future Verilator-compatible SV BFM could replace `axi_lite_driver_pkg.sv`, and a real C++ VIP could replace `axi_lite_driver.hpp`, each without touching anything else in this design) is explicitly anticipated, not precluded.
- This design does not attempt to fix the pre-init CI job gap found in the previous session's work (most per-tool CI jobs not exercising real files pre-`make init`) — `smoke-test` remains the reliable signal, as documented in `README.md`.
