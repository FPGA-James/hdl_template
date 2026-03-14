#!/usr/bin/env python3
"""
parse_hierarchy.py
------------------
Reads filelist.f, extracts entity/module names and instantiation
relationships, detects the top-level module, and writes hierarchy.json.

hierarchy.json structure:
{
  "top": "top",
  "modules": {
    "top": {
      "file": "src/top.vhd",
      "children": ["traffic_light", "blinky", "pwm_controller"],
      "parents": [],
      "shared": false
    },
    "traffic_light": {
      "file": "src/traffic_light.vhd",
      "children": [],
      "parents": ["top"],
      "shared": false
    },
    "pwm_controller": {
      "file": "src/pwm_controller.sv",
      "children": [],
      "parents": ["top"],
      "shared": false          ← true if parents > 1
    }
  }
}

Usage:
    python scripts/parse_hierarchy.py filelist.f docs/hierarchy.json
"""

import json
import re
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# filelist.f reader
# ─────────────────────────────────────────────────────────────────────────────

def read_filelist(filelist_path: Path) -> list[Path]:
    """Read filelist.f, return list of source Paths (comments and blanks stripped)."""
    files = []
    for line in filelist_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = Path(line)
        if not p.exists():
            # Try relative to filelist location
            p = filelist_path.parent / line
        if p.exists():
            files.append(p)
        else:
            print(f"  WARNING: file not found: {line}", file=sys.stderr)
    return files


# ─────────────────────────────────────────────────────────────────────────────
# Module name extraction
# ─────────────────────────────────────────────────────────────────────────────

VHDL_ENTITY_RE = re.compile(r"\bentity\s+(\w+)\s+is\b", re.IGNORECASE)
SV_MODULE_RE   = re.compile(r"^\s*module\s+(\w+)", re.IGNORECASE | re.MULTILINE)


def extract_module_name(src: Path) -> str | None:
    text = src.read_text()
    ext  = src.suffix.lower()
    if ext in (".vhd", ".vhdl"):
        m = VHDL_ENTITY_RE.search(text)
    elif ext in (".sv", ".svh"):
        m = SV_MODULE_RE.search(text)
    else:
        return None
    return m.group(1).lower() if m else None


# ─────────────────────────────────────────────────────────────────────────────
# Instantiation extraction
# ─────────────────────────────────────────────────────────────────────────────

def strip_comments_vhdl(text: str) -> str:
    return re.sub(r"--[^\n]*", " ", text)

def strip_comments_sv(text: str) -> str:
    text = re.sub(r"//[^\n]*", " ", text)
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)


def extract_instantiations_vhdl(text: str, known_names: set[str]) -> list[str]:
    """
    Find all entity instantiations in VHDL.
    Handles:
      - Direct:    u1 : entity work.traffic_light port map (...)
      - Component: u1 : traffic_light port map (...)
    """
    text  = strip_comments_vhdl(text)
    found = set()

    # entity work.NAME  or  entity lib.NAME
    for m in re.finditer(
        r":\s*entity\s+\w+\s*\.\s*(\w+)\s+(?:generic|port)\s+map",
        text, re.IGNORECASE
    ):
        found.add(m.group(1).lower())

    # label : component_name  port map  (component instantiation style)
    for m in re.finditer(
        r":\s*(\w+)\s+(?:generic\s+map\s*\([^)]*\)\s*)?port\s+map",
        text, re.IGNORECASE
    ):
        name = m.group(1).lower()
        if name in known_names:
            found.add(name)

    return sorted(found)


def extract_instantiations_sv(text: str, known_names: set[str]) -> list[str]:
    """
    Find all module instantiations in SystemVerilog.
    Handles:
      - module_name #(...) inst_name (...)
      - module_name inst_name (...)
    """
    text  = strip_comments_sv(text)
    found = set()

    SV_INST_RE = re.compile(
        r"^\s*(\w+)\s*(?:#\s*\([^)]*\)\s*)?\w+\s*\(",
        re.MULTILINE
    )
    SV_KEYWORDS = {
        "module","endmodule","input","output","inout","logic","wire","reg",
        "always","begin","end","if","else","case","endcase","assign",
        "parameter","localparam","typedef","enum","struct","import",
        "always_ff","always_comb","always_latch","initial","generate",
        "endgenerate","for","while","function","endfunction","task","endtask"
    }

    for m in SV_INST_RE.finditer(text):
        name = m.group(1).lower()
        if name not in SV_KEYWORDS and name in known_names:
            found.add(name)

    return sorted(found)


def extract_instantiations(src: Path, known_names: set[str]) -> list[str]:
    text = src.read_text()
    ext  = src.suffix.lower()
    if ext in (".vhd", ".vhdl"):
        return extract_instantiations_vhdl(text, known_names)
    elif ext in (".sv", ".svh"):
        return extract_instantiations_sv(text, known_names)
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Hierarchy builder
# ─────────────────────────────────────────────────────────────────────────────

def build_hierarchy(source_files: list[Path]) -> dict:
    # Pass 1: extract all module names
    name_to_file = {}
    for src in source_files:
        name = extract_module_name(src)
        if name:
            name_to_file[name] = str(src)
        else:
            print(f"  WARNING: could not extract module name from {src}",
                  file=sys.stderr)

    known = set(name_to_file.keys())

    # Pass 2: extract instantiations
    children_of = {name: [] for name in known}
    parents_of  = {name: [] for name in known}

    for src in source_files:
        name = extract_module_name(src)
        if not name:
            continue
        insts = extract_instantiations(src, known - {name})
        for child in insts:
            if child not in children_of[name]:
                children_of[name].append(child)
            if name not in parents_of[child]:
                parents_of[child].append(name)

    # Detect top-level: module with no parents
    tops = [n for n in known if not parents_of[n]]
    if len(tops) == 1:
        top = tops[0]
    elif len(tops) > 1:
        print(f"  WARNING: multiple root modules found: {tops}", file=sys.stderr)
        print(f"  Using last file in filelist as top: {source_files[-1].stem}",
              file=sys.stderr)
        top = extract_module_name(source_files[-1]) or tops[0]
    else:
        print("  WARNING: no root module detected (circular?), using last file",
              file=sys.stderr)
        top = extract_module_name(source_files[-1]) or list(known)[-1]

    modules = {}
    for name in known:
        modules[name] = {
            "file":     name_to_file[name],
            "children": children_of[name],
            "parents":  parents_of[name],
            "shared":   len(parents_of[name]) > 1,
        }

    return {"top": top, "modules": modules}


# ─────────────────────────────────────────────────────────────────────────────
# Pretty-print hierarchy tree
# ─────────────────────────────────────────────────────────────────────────────

def print_tree(name: str, modules: dict, prefix: str = "", visited: set = None):
    if visited is None:
        visited = set()
    shared_tag = " [shared]" if modules[name]["shared"] else ""
    already    = " (see above)" if name in visited else ""
    print(f"{prefix}{name}{shared_tag}{already}")
    if name in visited:
        return
    visited.add(name)
    children = modules[name]["children"]
    for i, child in enumerate(children):
        connector = "└── " if i == len(children) - 1 else "├── "
        extension = "    " if i == len(children) - 1 else "│   "
        print_tree(child, modules, prefix + connector, visited)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Usage: parse_hierarchy.py <filelist.f> <output_hierarchy.json>")

    filelist_path = Path(sys.argv[1])
    output_path   = Path(sys.argv[2])

    if not filelist_path.exists():
        sys.exit(f"ERROR: filelist not found: {filelist_path}")

    print(f"Reading filelist: {filelist_path}")
    sources = read_filelist(filelist_path)
    print(f"Found {len(sources)} source files")

    hierarchy = build_hierarchy(sources)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(hierarchy, indent=2))

    print(f"\nHierarchy tree:")
    print_tree(hierarchy["top"], hierarchy["modules"])
    print(f"\nTop-level: {hierarchy['top']}")
    shared = [n for n, m in hierarchy["modules"].items() if m["shared"]]
    if shared:
        print(f"Shared components: {shared}")
    print(f"\nWritten: {output_path}")