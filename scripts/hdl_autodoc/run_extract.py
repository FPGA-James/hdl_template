#!/usr/bin/env python3
"""
run_extract.py
--------------
Reads hierarchy.json and runs extract_fsm.py + extract_processes.py
for every module. Called by the Makefile extract target.

Usage:
    python scripts/run_extract.py <hierarchy.json> <docs_dir> <scripts_dir>
        [--schematics] [--ghdl-lib-path PATH]

Flags:
    --schematics          Run generate_schematic.py (requires yosys) and
                          include the RTL schematic in each module's block
                          diagram page.
    --ghdl-lib-path PATH  Directory of pre-compiled VHDL libraries (passed
                          to generate_schematic.py as -P<PATH> in the ghdl
                          command).
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
        sys.exit(
            "Usage: run_extract.py <hierarchy.json> <docs_dir> "
            "<scripts_dir> [--schematics]"
        )

    hierarchy_path = Path(sys.argv[1])
    docs_dir = Path(sys.argv[2])
    scripts_dir = Path(sys.argv[3])
    args = sys.argv[4:]
    schematics = "--schematics" in args

    ghdl_lib_path = None  # type: ignore[assignment]
    for i, a in enumerate(args):
        if a == "--ghdl-lib-path" and i + 1 < len(args):
            ghdl_lib_path = args[i + 1]
        elif a.startswith("--ghdl-lib-path="):
            ghdl_lib_path = a.split("=", 1)[1]

    hierarchy = json.loads(hierarchy_path.read_text())

    for name, mod in hierarchy["modules"].items():
        src_file = mod["file"]
        module_dir = docs_dir / "modules" / name
        proc_dir = module_dir / "processes"

        print(f"Extracting: {name} ({src_file})...")

        run(["python", str(scripts_dir / "extract_fsm.py"),
             src_file, name, str(module_dir)])

        run(["python", str(scripts_dir / "extract_processes.py"),
             src_file, str(proc_dir)])

        run(["python", str(scripts_dir / "extract_cdc.py"),
             src_file, name, str(module_dir)])

        # Generate RTL schematic before extract_block so the SVG is available
        # for inclusion in the block diagram RST.  All source files are passed
        # so that ghdl can resolve cross-unit references.
        if schematics:
            # Use the full filelist (includes package-only files) so ghdl can
            # resolve cross-unit references.
            all_src = list(
                hierarchy.get("files")
                or [m["file"] for m in hierarchy["modules"].values()]
            )
            # Append generated VHDL files so that top-level modules that use
            # generated register packages can be elaborated by ghdl.
            # Order: *_regs_pkg → *_register_record_pkg → *_axi_lite
            gen_vhdl_dir = (
                hierarchy_path.parent.parent / "out" / "regs" / "vhdl"
            )
            if gen_vhdl_dir.is_dir():
                def _gen_order(p: Path) -> int:
                    s = p.stem
                    if s.endswith("_regs_pkg"):
                        return 0
                    if s.endswith("_record_pkg"):
                        return 1
                    return 2
                gen_files = sorted(
                    (
                        f for f in gen_vhdl_dir.glob("*.vhd")
                        if str(f) not in all_src
                    ),
                    key=_gen_order,
                )
                all_src += [str(f) for f in gen_files]
            schematic_cmd = [
                "python", str(scripts_dir / "generate_schematic.py"),
                src_file, name, str(module_dir),
            ] + all_src
            if ghdl_lib_path:
                schematic_cmd += ["--ghdl-lib-path", ghdl_lib_path]
            run(schematic_cmd)

        run(["python", str(scripts_dir / "extract_block.py"),
             src_file, name, str(module_dir)])

        run(["python", str(scripts_dir / "extract_reset.py"),
             src_file, name, str(module_dir)])
