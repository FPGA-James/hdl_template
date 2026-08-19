#!/usr/bin/env bash
# smoke_test.sh — end-to-end smoke test of the template after `make init`.
#
# Copies the working tree into an isolated temp directory per language,
# runs `make init`, then walks it through register generation, LSP config
# generation, every applicable testbench flow, linting, synthesis, and
# documentation generation. Every step runs regardless of earlier failures
# (not `set -e`) so a single invocation surfaces the full list of what's
# broken, rather than stopping at the first failure.
#
# Usage:
#   scripts/smoke_test.sh              # both VHDL and SV
#   scripts/smoke_test.sh vhdl         # VHDL project only
#   scripts/smoke_test.sh sv           # SystemVerilog project only
#   KEEP=1 scripts/smoke_test.sh       # keep the temp project dirs afterwards
#
# Requires network access (make deps fetches hdl-modules via git) and the
# full toolchain on PATH: OSS CAD Suite (ghdl/yosys/verilator/icarus),
# bender, and NVC. The submodules/HDLAutoDoc submodule must be checked out
# (git submodule update --init --recursive) for the docs steps.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "${1:-}" in
    vhdl) LANGS=(vhdl) ;;
    sv)   LANGS=(sv) ;;
    "")   LANGS=(vhdl sv) ;;
    *)    echo "Usage: $0 [vhdl|sv]" >&2; exit 2 ;;
esac

ROOT_WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/hdl_template_smoke.XXXXXX")"
cleanup() {
    if [[ -n "${KEEP:-}" ]]; then
        echo ""
        echo "Kept project dirs and logs: $ROOT_WORKDIR"
    else
        rm -rf "$ROOT_WORKDIR"
    fi
}
trap cleanup EXIT

RESULTS=()
OVERALL=0

# step <lang> <name> <command...> — run a command, log its output, record pass/fail.
step() {
    local lang="$1" name="$2"
    shift 2
    local logfile="$LOGDIR/${name// /_}.log"
    printf "\033[1m▶ [%s] %s\033[0m ... " "$lang" "$name"
    if "$@" >"$logfile" 2>&1; then
        printf "\033[32mpass\033[0m\n"
        RESULTS+=("${lang}	${name}	PASS")
    else
        printf "\033[31mFAIL\033[0m  (log: %s)\n" "$logfile"
        tail -n 15 "$logfile" | sed 's/^/    | /'
        RESULTS+=("${lang}	${name}	FAIL")
        OVERALL=1
    fi
}

run_lang() {
    local lang="$1"
    local dir="$ROOT_WORKDIR/$lang"
    LOGDIR="$ROOT_WORKDIR/logs-$lang"
    mkdir -p "$dir" "$LOGDIR"

    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo "  $lang project"
    echo "════════════════════════════════════════════════════════════"

    rsync -a \
        --exclude='.git' --exclude='out' --exclude='.venv' --exclude='deps' \
        --exclude='__pycache__' --exclude='vunit_out' --exclude='sim_build' \
        --exclude='waves' \
        "$REPO_ROOT/" "$dir/"
    cd "$dir"

    step "$lang" "init" bash scripts/init_project.sh smoketest "$lang"
    step "$lang" "venv" make venv
    step "$lang" "deps" make deps
    step "$lang" "regs" make regs
    step "$lang" "lsp"  make lsp

    if [[ "$lang" == vhdl ]]; then
        step "$lang" "lint-vhdl"        make lint-vhdl
        step "$lang" "sim-native"       make sim-native TOPLEVEL_HDL=vhdl
        step "$lang" "sim-cocotb-ghdl"  make sim FRAMEWORK=cocotb SIM=ghdl TOPLEVEL_HDL=vhdl
        step "$lang" "sim-vunit"        make sim FRAMEWORK=vunit
        step "$lang" "synth"            make synth TOPLEVEL_HDL=vhdl
    else
        step "$lang" "lint-sv"              make lint-sv
        step "$lang" "sim-native"           make sim-native TOPLEVEL_HDL=sv
        step "$lang" "sim-cocotb-verilator" make sim FRAMEWORK=cocotb SIM=verilator TOPLEVEL_HDL=sv
        step "$lang" "synth"                make synth TOPLEVEL_HDL=sv
    fi

    step "$lang" "html"            make html
    step "$lang" "coverage"        make coverage
    step "$lang" "clean-generated" make clean-generated
}

for lang in "${LANGS[@]}"; do
    run_lang "$lang"
done

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Summary"
echo "════════════════════════════════════════════════════════════"
printf '%s\n' "${RESULTS[@]}" | column -t -s "$(printf '\t')"

exit "$OVERALL"
