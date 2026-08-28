#!/usr/bin/env bash
# init_project.sh — Initialise the HDL template with a project name.
#
# Usage:
#   bash scripts/init_project.sh <project_name> [vhdl|sv]
#   make init NAME=<project_name> TOPLEVEL_HDL=vhdl|sv
#
# What it does:
#   0. Moves src/<hdl>/ files to src/, removes both src/vhdl/ and src/sv/,
#      and normalises src/vhdl/ and src/sv/ path references to src/.
#   1. Validates the project name (lowercase letters, digits, underscores).
#   2. Replaces all <<NAME>> placeholders inside files with the project name.
#   3. Renames files whose stem begins with NAME_ to <project_name>_.
#
# Placeholder convention:
#   File contents : <<NAME>>          (e.g. entity <<NAME>>_core is)
#   File names    : NAME_<rest>.ext   (e.g. NAME_core.vhd → my_module_core.vhd)
#
# Safe to run multiple times IF the project name is the same each time.
# Do NOT run with a different name after initialisation.

set -euo pipefail

# ── Argument validation ────────────────────────────────────────────────────────
NAME="${1:-}"
TOPLEVEL_HDL="${2:-vhdl}"

if [[ -z "$NAME" ]]; then
    echo "ERROR: No project name supplied."
    echo "Usage: bash scripts/init_project.sh <project_name> [vhdl|sv]"
    exit 1
fi

if ! [[ "$NAME" =~ ^[a-z][a-z0-9_]*$ ]]; then
    echo "ERROR: Project name must start with a lowercase letter and contain"
    echo "       only lowercase letters, digits, and underscores."
    echo "       Received: '$NAME'"
    exit 1
fi

if [[ "$TOPLEVEL_HDL" != "vhdl" && "$TOPLEVEL_HDL" != "sv" ]]; then
    echo "ERROR: TOPLEVEL_HDL must be 'vhdl' or 'sv'. Got: '$TOPLEVEL_HDL'"
    exit 1
fi

echo "Initialising project: <<NAME>> → $NAME (HDL: $TOPLEVEL_HDL)"
echo ""

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Directories to process ─────────────────────────────────────────────────────
# Excluded: .venv/, deps/, .git/, out/
EXCLUDE_PATHS=(
    "./.venv"
    "./deps"
    "./.git"
    "./out"
    "./submodules"
)

# Build find -prune expression
PRUNE_EXPR=()
for p in "${EXCLUDE_PATHS[@]}"; do
    PRUNE_EXPR+=(-path "$p" -prune -o)
done

# macOS/GNU sed compatibility
if sed --version 2>/dev/null | grep -q GNU; then
    SED_I=(-i)
else
    SED_I=(-i '')
fi

# ── Step 0: Flatten src/ layout ────────────────────────────────────────────────
echo "Step 0: Flattening src/ (keeping src/$TOPLEVEL_HDL/ → src/)..."

DROP_SUBDIR="$([[ "$TOPLEVEL_HDL" == "vhdl" ]] && echo "sv" || echo "vhdl")"

# Move chosen language files up to src/
if [[ -d "src/$TOPLEVEL_HDL" ]]; then
    for f in "src/$TOPLEVEL_HDL"/*; do
        [[ -e "$f" ]] || continue
        mv "$f" "src/$(basename "$f")"
        echo "  moved: $f → src/$(basename "$f")"
    done
    rmdir "src/$TOPLEVEL_HDL"
fi

# Remove the unused language folder
if [[ -d "src/$DROP_SUBDIR" ]]; then
    rm -rf "src/$DROP_SUBDIR"
    echo "  removed: src/$DROP_SUBDIR/"
fi

# Normalise path references: replace src/vhdl/ and src/sv/ → src/ in all
# config and documentation files so Bender.yml, template.core, CLAUDE.md etc.
# reflect the new flat layout.
for subdir in vhdl sv; do
    while IFS= read -r -d '' f; do
        if grep -qF "src/$subdir/" "$f" 2>/dev/null; then
            sed "${SED_I[@]}" "s|src/$subdir/|src/|g" "$f"
            echo "  normalised paths in: $f"
        fi
    done < <(find . \
        "${PRUNE_EXPR[@]}" \
        \( \
            -name "*.yml" -o -name "*.yaml" -o -name "*.core" \
            -o -name "*.md"  -o -name "*.rst" -o -name "*.py"  \
            -o -name "*.sh"  -o -name "*.f"   -o -name "Makefile" \
        \) -print0 2>/dev/null)
done

echo ""

# ── Step 1: Replace <<NAME>> in file contents ──────────────────────────────────
echo "Step 1: Replacing <<NAME>> in file contents..."
CONTENT_COUNT=0

while IFS= read -r -d '' f; do
    if grep -qF '<<NAME>>' "$f" 2>/dev/null; then
        sed "${SED_I[@]}" "s/<<NAME>>/$NAME/g" "$f"
        echo "  updated: $f"
        (( CONTENT_COUNT++ )) || true
    fi
done < <(find . \
    "${PRUNE_EXPR[@]}" \
    \( \
        -name "*.vhd" -o -name "*.sv"   -o -name "*.v"    \
        -o -name "*.py"  -o -name "*.sh"  -o -name "*.toml" \
        -o -name "*.yml" -o -name "*.yaml"\
        -o -name "*.rst" -o -name "*.md"  -o -name "*.txt"  \
        -o -name "Makefile" -o -name "*.mk" -o -name "*.core" \
        -o -name "*.f"   -o -name "*.ys"  -o -name "*.xdc"  \
        -o -name "*.cpp" -o -name "*.h"   -o -name "*.hpp"  \
        -o -name "Bender.yml" \
    \) -print0 2>/dev/null)

echo "  $CONTENT_COUNT file(s) updated."
echo ""

# ── Step 2: Rename files with NAME_ prefix ─────────────────────────────────────
echo "Step 2: Renaming files with NAME_ prefix..."
RENAME_COUNT=0

# Collect files first (avoid renaming while iterating). Built with a
# read loop rather than `mapfile` for portability — macOS ships bash 3.2,
# which lacks the `mapfile`/`readarray` builtins (added in bash 4).
RENAME_CANDIDATES=()
while IFS= read -r -d '' f; do
    RENAME_CANDIDATES+=("$f")
done < <(find . \
    "${PRUNE_EXPR[@]}" \
    \( \
        -name "NAME_*.vhd" -o -name "NAME_*.sv" -o -name "NAME_*.v" \
        -o -name "NAME_*.py" -o -name "NAME_*.toml" -o -name "NAME_*.ys" \
        -o -name "NAME_*.xdc" -o -name "NAME_*.rst" \
        -o -name "NAME_*.cpp" -o -name "NAME_*.h" -o -name "NAME_*.hpp" \
    \) -print0 2>/dev/null)

for f in "${RENAME_CANDIDATES[@]}"; do
    dir="$(dirname "$f")"
    base="$(basename "$f")"
    newbase="${base/NAME_/${NAME}_}"
    newf="$dir/$newbase"
    if [[ "$f" != "$newf" ]]; then
        mv "$f" "$newf"
        echo "  renamed: $f → $newf"
        (( RENAME_COUNT++ )) || true
    fi
done

echo "  $RENAME_COUNT file(s) renamed."
echo ""

# ── Done ───────────────────────────────────────────────────────────────────────
echo "Project '$NAME' initialised successfully."
echo ""
echo "Next steps:"
echo "  make venv              # Create Python virtual environment (once)"
echo "  make deps              # Fetch HDL dependencies via Bender"
echo "  make regs              # Generate register VHDL/C/HTML from regs/*.toml"
if [[ "$TOPLEVEL_HDL" == "sv" ]]; then
echo "  make sim FRAMEWORK=cocotb SIM=verilator TOPLEVEL_HDL=sv"
else
echo "  make sim               # Run VHDL testbench via VUnit + GHDL"
fi
echo "  make html              # Build Sphinx documentation"
echo ""
