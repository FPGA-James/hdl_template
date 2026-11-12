# =============================================================================
# scripts/mk/tools/icestudio/icestudio.mk — IceStudio: device programming after `make impl`
# =============================================================================
.PHONY: icestudio

# IceStudio application name / binary
# macOS: app bundle name passed to `open -a`  (default: IceStudio)
# Linux: binary name on PATH                   (default: icestudio)
ICESTUDIO ?= IceStudio

ifeq ($(shell uname),Darwin)
ICESTUDIO_CMD  = open -a "$(ICESTUDIO)"
ICESTUDIO_HINT = /path/to/IceStudio
else
ICESTUDIO_CMD  = $(ICESTUDIO)
ICESTUDIO_HINT = icestudio
endif

# Declared (with its `impl` prerequisite and help text) in scripts/mk/impl.mk.
icestudio:
	@printf "\n\033[1m  Opening IceStudio...\033[0m\n"
	@printf "    Bitstream: \033[36m$(IMPL_BIT)\033[0m\n\n"
	@$(ICESTUDIO_CMD) 2>/dev/null || \
	  (printf "\n\033[1;31m  ERROR:\033[0m IceStudio not found.\n" && \
	   printf  "         Install from \033[36mhttps://icestudio.io\033[0m\n" && \
	   printf  "         or override: \033[36mmake icestudio ICESTUDIO=$(ICESTUDIO_HINT)\033[0m\n\n" && \
	   exit 1)
