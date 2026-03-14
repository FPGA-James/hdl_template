#!/usr/bin/env python3
"""
run_extract.py
--------------
Reads hierarchy.json and runs extract_fsm.py + extract_processes.py
for every module. Called by the Makefile extract target.

Usage:
    python scripts/run_extract.py <hierarchy.json> <docs_dir> <scripts_dir> [--schematics]

Flags:
    --schematics   Run generate_schematic.py (requires yosys) and include the
                   RTL schematic in each module's block diagram page.
"""

import json
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]):
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit("Usage: run_extract.py <hierarchy.json> <docs_dir> <scripts_dir> [--schematics]")

    hierarchy_path = Path(sys.argv[1])
    docs_dir       = Path(sys.argv[2])
    scripts_dir    = Path(sys.argv[3])
    schematics     = "--schematics" in sys.argv[4:]

    hierarchy = json.loads(hierarchy_path.read_text())

    for name, mod in hierarchy["modules"].items():
        src_file   = mod["file"]
        module_dir = docs_dir / "modules" / name
        proc_dir   = module_dir / "processes"

        print(f"Extracting: {name} ({src_file})...")

        run(["python", str(scripts_dir / "extract_fsm.py"),
             src_file, name, str(module_dir)])

        run(["python", str(scripts_dir / "extract_processes.py"),
             src_file, str(proc_dir)])

        run(["python", str(scripts_dir / "extract_cdc.py"),
             src_file, name, str(module_dir)])

        # Generate RTL schematic before extract_block so the SVG is available
        # for inclusion in the block diagram RST.  All source files are passed
        # so that ghdl can resolve cross-unit references (e.g. top-level entities
        # that instantiate submodules).
        if schematics:
            all_src = [m["file"] for m in hierarchy["modules"].values()]
            run(["python", str(scripts_dir / "generate_schematic.py"),
                 src_file, name, str(module_dir)] + all_src)

        run(["python", str(scripts_dir / "extract_block.py"),
             src_file, name, str(module_dir)])

        run(["python", str(scripts_dir / "extract_reset.py"),
             src_file, name, str(module_dir)])