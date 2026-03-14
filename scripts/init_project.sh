#!/usr/bin/env bash
# init_project.sh — Initialise the HDL template with a project name.
#
# Usage:
#   bash scripts/init_project.sh <project_name>
#   make init NAME=<project_name>
#
# What it does:
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
if [[ -z "$NAME" ]]; then
    echo "ERROR: No project name supplied."
    echo "Usage: bash scripts/init_project.sh <project_name>"
    exit 1
fi

if ! [[ "$NAME" =~ ^[a-z][a-z0-9_]*$ ]]; then
    echo "ERROR: Project name must start with a lowercase letter and contain"
    echo "       only lowercase letters, digits, and underscores."
    echo "       Received: '$NAME'"
    exit 1
fi

echo "Initialising project: <<NAME>> → $NAME"
echo ""

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Directories to process ─────────────────────────────────────────────────────
# Excluded: .venv/, deps/, .git/, gen/, synth/output/, docs/_build/
EXCLUDE_PATHS=(
    "./.venv"
    "./deps"
    "./.git"
    "./gen"
    "./synth/output"
    "./docs/_build"
)

# Build find -prune expression
PRUNE_EXPR=()
for p in "${EXCLUDE_PATHS[@]}"; do
    PRUNE_EXPR+=(-path "$p" -prune -o)
done

# ── Step 1: Replace <<NAME>> in file contents ──────────────────────────────────
echo "Step 1: Replacing <<NAME>> in file contents..."
CONTENT_COUNT=0

while IFS= read -r -d '' f; do
    if grep -qF '<<NAME>>' "$f" 2>/dev/null; then
        # macOS sed requires -i '' ; GNU sed requires -i alone
        if sed --version 2>/dev/null | grep -q GNU; then
            sed -i "s/<<NAME>>/$NAME/g" "$f"
        else
            sed -i '' "s/<<NAME>>/$NAME/g" "$f"
        fi
        echo "  updated: $f"
        (( CONTENT_COUNT++ )) || true
    fi
done < <(find . \
    "${PRUNE_EXPR[@]}" \
    -print \
    \( \
        -name "*.vhd" -o -name "*.sv"   -o -name "*.v"    \
        -o -name "*.py"  -o -name "*.sh"  -o -name "*.toml" \
        -o -name "*.yml" -o -name "*.yaml"\
        -o -name "*.rst" -o -name "*.md"  -o -name "*.txt"  \
        -o -name "Makefile" -o -name "*.mk" -o -name "*.core" \
        -o -name "*.f"   -o -name "*.ys"  -o -name "*.xdc"  \
        -o -name "Bender.yml" \
    \) -print0 2>/dev/null)

echo "  $CONTENT_COUNT file(s) updated."
echo ""

# ── Step 2: Rename files with NAME_ prefix ─────────────────────────────────────
echo "Step 2: Renaming files with NAME_ prefix..."
RENAME_COUNT=0

# Collect files first (avoid renaming while iterating)
mapfile -d '' RENAME_CANDIDATES < <(find . \
    "${PRUNE_EXPR[@]}" \
    -print \
    \( \
        -name "NAME_*.vhd" -o -name "NAME_*.sv" -o -name "NAME_*.v" \
        -o -name "NAME_*.py" -o -name "NAME_*.toml" -o -name "NAME_*.ys" \
        -o -name "NAME_*.xdc" -o -name "NAME_*.rst" \
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
echo "  make sim               # Run VHDL testbench via VUnit + GHDL"
echo "  make html              # Build Sphinx documentation"
echo ""
