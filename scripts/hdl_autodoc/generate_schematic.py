#!/usr/bin/env python3
"""
generate_schematic.py
---------------------
Generates an RTL schematic for a VHDL or SystemVerilog module using yosys
and netlistsvg.

Pipeline:
  yosys (synthesis + opt) → write_json → netlistsvg → <module>_schematic.svg

For VHDL modules, requires yosys with the ghdl-yosys-plugin (OSS CAD Suite).
For SystemVerilog modules, requires yosys with native SV support.
netlistsvg is required for both: install with `npm install -g netlistsvg`.

Writes:
  <module_name>_schematic.svg  — clean gate-level schematic

Usage:
    python generate_schematic.py <file.vhd|file.sv> <module_name> <output_dir>

Always exits with code 0 — schematic generation is optional and failures are
non-fatal.  The build continues; the block diagram RST simply omits the
schematic section if the SVG was not produced.
"""

import shutil
import subprocess
import sys
from pathlib import Path


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


def _have_ghdl_plugin() -> bool:
    """Return True if yosys can load the ghdl plugin."""
    r = subprocess.run(
        ["yosys", "-m", "ghdl", "-p", ""],
        capture_output=True,
        text=True,
    )
    return "Can't load module" not in r.stderr


def _run_yosys(args: list[str]) -> tuple[bool, str]:
    """Run yosys with *args; return (success, stderr_snippet)."""
    r = subprocess.run(["yosys"] + args, capture_output=True, text=True)
    return r.returncode == 0, r.stderr[:600] if r.stderr else ""


def _synth_vhdl(src: Path, module_name: str, json_path: Path,
                extra_srcs: list[Path]) -> bool:
    if not _have_ghdl_plugin():
        print(f"  ! SCHEMATIC [{module_name}]: ghdl-yosys-plugin not available — skipping")
        return False

    # Collect all VHDL files: extra deps first (leaves before top), then src.
    # Deduplicate while preserving order so ghdl sees units before they're used.
    seen: set[Path] = set()
    vhdl_files: list[Path] = []
    sv_deps: list[str] = []
    for f in extra_srcs + [src]:
        if f in seen:
            continue
        seen.add(f)
        if f.suffix.lower() in (".vhd", ".vhdl"):
            vhdl_files.append(f)
        elif f.suffix.lower() in (".sv", ".svh"):
            sv_deps.append(f.stem)

    # If this module instantiates SystemVerilog submodules, ghdl cannot
    # elaborate it — skip cleanly rather than dumping a synthesis error.
    if sv_deps:
        sv_names = ", ".join(sv_deps)
        print(f"  ! SCHEMATIC [{module_name}]: mixed-language design "
              f"(SystemVerilog deps: {sv_names}) — ghdl cannot elaborate, skipping")
        return False

    files_str = " ".join(str(f) for f in vhdl_files)
    script = (
        f"ghdl --std=08 {files_str} -e {module_name}; "
        f"proc; opt; "
        f"write_json {json_path}"
    )
    ok, err = _run_yosys(["-m", "ghdl", "-p", script])
    if not ok:
        print(f"  ! SCHEMATIC [{module_name}]: yosys/ghdl synthesis failed")
        if err:
            print("    " + err.replace("\n", "\n    "))
    return ok


def _synth_sv(src: Path, module_name: str, json_path: Path,
              extra_srcs: list[Path]) -> bool:
    # For SV, read all SV files (extra deps first), then elaborate the target module.
    seen = set()
    sv_files: list[Path] = []
    for f in extra_srcs + [src]:
        if f not in seen and f.suffix.lower() in (".sv", ".svh"):
            seen.add(f)
            sv_files.append(f)

    read_cmds = " ".join(f"read_verilog -sv {f};" for f in sv_files)
    script = (
        f"{read_cmds} "
        f"proc; opt; "
        f"write_json {json_path}"
    )
    ok, err = _run_yosys(["-p", script])
    if not ok:
        print(f"  ! SCHEMATIC [{module_name}]: yosys synthesis failed")
        if err:
            print("    " + err.replace("\n", "\n    "))
    return ok


def _run_netlistsvg(json_path: Path, svg_path: Path, module_name: str) -> bool:
    r = subprocess.run(
        ["netlistsvg", str(json_path), "-o", str(svg_path)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(f"  ! SCHEMATIC [{module_name}]: netlistsvg failed")
        if r.stderr:
            print("    " + r.stderr[:400].replace("\n", "\n    "))
        return False
    return True


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit("Usage: generate_schematic.py <file.vhd|file.sv> <module_name> <output_dir>")

    src_path    = Path(sys.argv[1])
    module_name = sys.argv[2]
    output_dir  = Path(sys.argv[3])
    output_dir.mkdir(parents=True, exist_ok=True)

    if not _have("yosys"):
        print(f"  ! SCHEMATIC [{module_name}]: yosys not found — skipping")
        sys.exit(0)

    if not _have("netlistsvg"):
        print(f"  ! SCHEMATIC [{module_name}]: netlistsvg not found — skipping")
        print(f"    Install with: npm install -g netlistsvg")
        sys.exit(0)

    extra_srcs = [Path(f) for f in sys.argv[4:]]
    json_path  = output_dir / f"{module_name}_schematic.json"
    svg_path   = output_dir / f"{module_name}_schematic.svg"
    ext        = src_path.suffix.lower()

    if ext in (".vhd", ".vhdl"):
        ok = _synth_vhdl(src_path, module_name, json_path, extra_srcs)
    elif ext in (".sv", ".svh"):
        ok = _synth_sv(src_path, module_name, json_path, extra_srcs)
    else:
        print(f"  ! SCHEMATIC [{module_name}]: unsupported file type '{ext}' — skipping")
        sys.exit(0)

    if ok:
        ok = _run_netlistsvg(json_path, svg_path, module_name)

    # Remove intermediate JSON regardless of outcome
    if json_path.exists():
        json_path.unlink()

    if ok and svg_path.exists():
        print(f"  → {svg_path}")

    sys.exit(0)  # Always non-fatal
