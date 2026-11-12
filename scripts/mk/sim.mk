# =============================================================================
# scripts/mk/sim.mk — simulation flows
#
# `sim` dispatches on FRAMEWORK (vunit | cocotb | native). The native
# (framework-less) bench is run by whichever tool NATIVE_SIM selects; each
# backend lives in scripts/mk/tools/ (nvc.mk, verilator.mk, ...) and registers itself
# in SIM_NATIVE_TOOLS. To add a simulator (e.g. Questa) provide a
# `sim-native-<tool>` target in scripts/mk/tools/<tool>.mk; cocotb and VUnit pick their
# simulator from SIM / VUNIT_SIMULATOR (see tb/cocotb/Makefile, tb/vunit/run.py).
# =============================================================================
.PHONY: sim sim-vunit sim-vunit-gui sim-cocotb sim-native sim-native-vhdl sim-native-sv sim-cpp

##@ Simulation

# Simulator VUnit drives. Only ghdl is wired up in tb/vunit/run.py today.
VUNIT_SIMULATOR ?= ghdl

# Native (framework-less) bench: NVC for VHDL, Verilator for SystemVerilog.
NATIVE_SIM  ?= $(if $(filter sv,$(HDL_KIND)),verilator,nvc)
NATIVE_RDIR  = out/native

sim: regs ## Run simulation  [FRAMEWORK=vunit|cocotb|native  SIM=ghdl|verilator  TOPLEVEL_HDL=vhdl|sv]
	$(if $(filter vunit cocotb native,$(FRAMEWORK)),@$(MAKE) --no-print-directory sim-$(FRAMEWORK),$(error Unknown FRAMEWORK=$(FRAMEWORK). Valid: vunit | cocotb | native))

sim-vunit: regs ## Run VUnit testbench via GHDL (VHDL only)
	$(call check-venv)
	@printf "\n\033[1m  Running VUnit simulation (GHDL)...\033[0m\n\n"
	@BENDER=$(BENDER) VUNIT_SIMULATOR=$(VUNIT_SIMULATOR) $(PYTHON) tb/vunit/run.py $(VUNIT_ARGS)

sim-vunit-gui: regs ## Open VUnit testbench in the GHDL waveform viewer
	$(call check-venv)
	@BENDER=$(BENDER) VUNIT_SIMULATOR=$(VUNIT_SIMULATOR) $(PYTHON) tb/vunit/run.py --gui $(VUNIT_ARGS)

sim-cocotb: regs ## Run cocotb testbench  [SIM=  TOPLEVEL_HDL=vhdl|sv  PYUVM=1 for the pyuvm bench]
	@printf "\n\033[1m  Running cocotb simulation ($(SIM))...\033[0m\n\n"
	@mkdir -p waves
	@$(MAKE) -C tb/cocotb SIM=$(SIM) TOPLEVEL_HDL=$(TOPLEVEL_HDL) BENDER=$(BENDER) $(if $(PYUVM),PYUVM=$(PYUVM))

# Native bench: dispatch to the selected tool's backend.
sim-native: regs sim-native-$(NATIVE_SIM) ## Run the native (framework-less) testbench  [NATIVE_SIM=nvc|verilator  TOPLEVEL_HDL=vhdl|sv]
	@:

# Language-named shortcuts for the two tools that ship with the template.
# (The explicit `@:` recipes stop make trying the sim-native-% fallback below on them.)
sim-native-vhdl: sim-native-nvc       ## Compile+elaborate+run tb/native/vhdl/<<NAME>>_tb.vhd directly with NVC (no framework)
	@:
sim-native-sv:   sim-native-verilator ## Compile+run tb/native/sv/<<NAME>>_tb.sv directly with Verilator --binary (no framework)
	@:
# Help entry only; the recipe is in scripts/mk/tools/verilator.mk.
sim-cpp: ## Compile+run tb/cpp/<<NAME>>_tb.cpp directly with Verilator --cc --exe --build (SV only)

sim-native-%:
	$(call unknown-tool,sim-native,NATIVE_SIM,$(SIM_NATIVE_TOOLS))
