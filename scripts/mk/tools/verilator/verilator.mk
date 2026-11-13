# =============================================================================
# scripts/mk/tools/verilator/verilator.mk — Verilator: native SV bench, C++ bench, SV lint
# =============================================================================
SIM_NATIVE_TOOLS += verilator
.PHONY: sim-native-verilator sim-cpp lint-sv

# RTL (and generated register file) for the Verilator-based native/C++ benches.
SV_SIM_SRC = $(SV_GEN) $(SV_RTL)

# Reports: lint.log, <bench>_build.log / <bench>_sim.log, and for the two benches (<bench> = native | cpp)
# <bench>_stats.txt (--stats), <bench>_coverage.dat/.info and the annotated sources <bench>_coverage/
# (--coverage: line + toggle).
VERILATOR_RDIR = $(AUTODOC_REPORTS_DIR)/verilator
VERILATOR_REPORT_FLAGS = --stats --coverage

# verilator-sim — run a built bench and write its coverage under the report dir, then turn that
# into the stats copy, annotated sources and an lcov file.
# $(1) = bench tag  $(2) = Mdir  $(3) = bench binary  $(4) = model prefix (V<top>, names the stats file)
define verilator-sim
	$(call run-logged,$(VERILATOR_RDIR)/$(1)_sim.log,$(2)/$(3) +verilator+coverage+file+$(VERILATOR_RDIR)/$(1)_coverage.dat)
	@cp $(2)/$(4)__stats.txt $(VERILATOR_RDIR)/$(1)_stats.txt
	@$(OSS_CAD_SUITE)/bin/verilator_coverage --annotate $(VERILATOR_RDIR)/$(1)_coverage \
	  --write-info $(VERILATOR_RDIR)/$(1)_coverage.info $(VERILATOR_RDIR)/$(1)_coverage.dat \
	  > $(VERILATOR_RDIR)/$(1)_coverage.log
endef

sim-native-verilator: regs
	@printf "\n\033[1m  Running native SystemVerilog simulation (Verilator)...\033[0m\n\n"
	@mkdir -p $(NATIVE_RDIR)/verilator_obj
	$(call run-logged,$(VERILATOR_RDIR)/native_build.log,$(OSS_CAD_SUITE)/bin/verilator --binary --timing -Wall -Wno-fatal -j 0 -Isrc \
	  $(VERILATOR_REPORT_FLAGS) -Mdir $(NATIVE_RDIR)/verilator_obj --top-module <<NAME>>_tb \
	  tb/native/sv/axi_lite_driver_pkg.sv \
	  $(SV_SIM_SRC) \
	  tb/native/sv/<<NAME>>_tb.sv)
	$(call verilator-sim,native,$(NATIVE_RDIR)/verilator_obj,V<<NAME>>_tb,V<<NAME>>_tb)
	@printf "\n\033[32m  ✓\033[0m Native SystemVerilog simulation passed\n\n"

sim-cpp: regs
ifneq ($(TOPLEVEL_HDL),sv)
	$(error sim-cpp requires TOPLEVEL_HDL=sv -- Verilator does not read VHDL)
endif
	@printf "\n\033[1m  Running C++ testbench (Verilator --cc --exe --build)...\033[0m\n\n"
	@mkdir -p $(NATIVE_RDIR)/cpp_obj
	$(call run-logged,$(VERILATOR_RDIR)/cpp_build.log,$(OSS_CAD_SUITE)/bin/verilator --cc --exe --build -Wall -Wno-fatal -j 0 -Isrc \
	  $(VERILATOR_REPORT_FLAGS) -Mdir $(NATIVE_RDIR)/cpp_obj --top-module <<NAME>>_top_cpp_flat \
	  $(SV_SIM_SRC) \
	  tb/cpp/<<NAME>>_top_cpp_flat.sv \
	  tb/cpp/<<NAME>>_tb.cpp \
	  -CFLAGS "-I$(CURDIR)/tb/cpp -I$(CURDIR)/out/regs/c" \
	  -o <<NAME>>_tb_cpp)
	$(call verilator-sim,cpp,$(NATIVE_RDIR)/cpp_obj,<<NAME>>_tb_cpp,V<<NAME>>_top_cpp_flat)
	@printf "\n\033[32m  ✓\033[0m C++ testbench passed\n\n"

lint-sv: regs
	@printf "\n\033[1m  Linting SystemVerilog...\033[0m\n\n"
	$(call run-logged,$(VERILATOR_RDIR)/lint.log,$(BENDER) script verilator -t rtl_sv -t gen_sv 2>/dev/null | \
	  xargs $(OSS_CAD_SUITE)/bin/verilator --lint-only --top-module "$(TOPLEVEL)" -Wall -Wno-fatal -Werror-WIDTHTRUNC -Isrc)
	@printf "\n\033[32m  ✓\033[0m SV lint passed\n\n"
