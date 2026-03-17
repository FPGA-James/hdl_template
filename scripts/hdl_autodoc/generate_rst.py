#!/usr/bin/env python3
"""
generate_rst.py
---------------
Generates RST scaffolding for all modules, hierarchy-aware when
docs/hierarchy.json is present (written by parse_hierarchy.py),
falling back to flat src/ glob otherwise.

Per-module files under docs/modules/<name>/:
  index.rst    — toctree (always regenerated); includes submodules section if children exist
  entity.rst   — vhdl:autoentity / source listing (write-if-missing)
  fsm.rst      — includes extracted FSM rst (always regenerated)
  timing.rst   — aggregated wavedrom diagrams (always regenerated)
  processes/   — written by extract_processes.py

Top-level:
  docs/index.rst          — always regenerated
  docs/overview.rst       — always regenerated
  docs/hierarchy.rst      — always regenerated (when hierarchy present)

Usage:
    python scripts/generate_rst.py <src_dir> <docs_dir>
"""

import json
import re
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# VHDL / SV entity extraction (used for flat fallback mode)
# ─────────────────────────────────────────────────────────────────────────────

ENTITY_RE = re.compile(r"\bentity\s+(\w+)\s+is\b", re.IGNORECASE)
MODULE_RE  = re.compile(r"^\s*module\s+(\w+)", re.IGNORECASE | re.MULTILINE)

PORT_RE    = re.compile(
    r"^\s*(\w+)\s*:\s*(in|out|inout)\s+(\w[\w_]*)",
    re.IGNORECASE
)


def extract_entities(src_path: Path) -> list[dict]:
    lines  = src_path.read_text().splitlines()
    is_sv  = src_path.suffix.lower() in (".sv", ".svh")
    pat    = MODULE_RE if is_sv else ENTITY_RE
    prefix = "//" if is_sv else "--"
    sv_port = re.compile(
        r"(input|output|inout)\s+(?:logic|wire|reg)?\s*(?:\[[^\]]*\])?\s*(\w+)",
        re.IGNORECASE
    )
    end_pat = re.compile(r"endmodule|\);", re.IGNORECASE) if is_sv \
              else re.compile(r"\bend\s+entity\b", re.IGNORECASE)

    entities = []
    for i, line in enumerate(lines):
        m = pat.search(line)
        if not m:
            continue
        name = m.group(1)

        # Brief from preceding comments
        brief_lines = []
        j = i - 1
        while j >= 0:
            s = lines[j].strip()
            if s.startswith(prefix):
                text = re.sub(rf"^{re.escape(prefix)}\s?", "", s).strip()
                if text and not re.match(r"^[-=*#/]+$", text):
                    brief_lines.insert(0, text)
            elif s == "":
                j -= 1; continue
            else:
                break
            j -= 1
        brief = " ".join(brief_lines[:2]) if brief_lines else f"{name} entity."

        # Port extraction
        ports = []
        k = i + 1
        while k < len(lines):
            if end_pat.search(lines[k]):
                break
            if is_sv:
                pm = sv_port.search(lines[k])
                if pm:
                    ports.append({"name": pm.group(2), "dir": pm.group(1).lower(),
                                  "type": "logic"})
            else:
                pm = PORT_RE.match(lines[k])
                if pm:
                    ports.append({"name": pm.group(1), "dir": pm.group(2).lower(),
                                  "type": pm.group(3).lower()})
            k += 1

        entities.append({"name": name, "brief": brief,
                         "file": src_path.name, "ports": ports})
    return entities


def scan_src(src_dir: Path) -> list[dict]:
    entities = []
    for path in sorted(src_dir.glob("**/*")):
        if path.suffix.lower() in (".vhd", ".vhdl", ".sv", ".svh"):
            entities.extend(extract_entities(path))
    return entities


# ─────────────────────────────────────────────────────────────────────────────
# Hierarchy loader
# ─────────────────────────────────────────────────────────────────────────────

def load_hierarchy(docs_dir: Path) -> dict | None:
    h_path = docs_dir / "hierarchy.json"
    if not h_path.exists():
        return None
    return json.loads(h_path.read_text())


def hierarchy_tree_depth(hierarchy: dict) -> int:
    """
    Return the maximum module nesting depth (top = 1, child = 2, …).
    Cycles are broken by tracking visited names.
    """
    modules = hierarchy["modules"]

    def depth(name: str, visited: frozenset) -> int:
        if name in visited:
            return 0
        children = modules.get(name, {}).get("children", [])
        if not children:
            return 1
        return 1 + max(depth(c, visited | {name}) for c in children)

    return depth(hierarchy["top"], frozenset())


def toc_maxdepth(hierarchy: dict) -> int:
    """
    Compute the root toctree maxdepth that makes every process page visible.

    The sidebar depth contributed by one hardware level is 2 (one for the
    module index and one for its content pages).  Process pages sit one level
    deeper than the module's content pages (processes/index) plus one more
    for the individual process files:

        root(1) → top_index(1) → top_content(2)
                               → core_index(3) → core_content(4)
                                               → tx_index(5) → tx_content(6)
                                                             → processes/(7)
                                                             → p_baud    (7)

    Formula: 2 * tree_depth + 1  (the +1 covers the processes/ sub-level).
    A floor of 4 is applied for flat (single-level) designs.
    """
    depth = hierarchy_tree_depth(hierarchy)
    return max(4, 2 * depth + 1)


def entity_from_hierarchy(name: str, hmod: dict) -> dict:
    """Build a minimal entity dict from a hierarchy module entry."""
    src_path = Path(hmod["file"])
    entities = extract_entities(src_path)
    for e in entities:
        if e["name"].lower() == name.lower():
            return e
    # Fallback if name not matched
    return {"name": name, "brief": f"{name} module.",
            "file": src_path.name, "ports": []}


# ─────────────────────────────────────────────────────────────────────────────
# Writers
# ─────────────────────────────────────────────────────────────────────────────

def write_if_missing(path: Path, content: str) -> str:
    if path.exists():
        return f"  (skipped — already exists) {path}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"  → {path}"


def write_always(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"  → (regenerated) {path}"


# ─────────────────────────────────────────────────────────────────────────────
# Per-module RST generators
# ─────────────────────────────────────────────────────────────────────────────

def module_index_rst(entity: dict, children: list[str],
                     shared_children: set[str],
                     has_processes: bool = True,
                     is_top: bool = False,
                     sub_maxdepth: int = 4) -> str:
    """Always-regenerated toctree for one module."""
    name  = entity["name"]
    title = name
    lines = [
        title, "=" * len(title), "",
        ".. toctree::",
        f"   :maxdepth: {sub_maxdepth}",
        "",
        "   entity",
        "   block",
        "   fsm",
        "   timing",
    ]
    if has_processes:
        lines.append("   processes/index")
    lines.append("   cdc")
    lines.append("   reset")
    lines.append("")

    if is_top:
        lines += ["   ../../registers", ""]

    if children:
        lines += [
            "Submodules",
            "----------",
            "",
            ".. toctree::",
            "   :maxdepth: 5",
            "   :caption: Submodules",
            "",
        ]
        for child in sorted(children):
            lines.append(f"   ../{child}/index")
        lines.append("")

        if shared_children & set(children):
            lines += [
                ".. note::",
                "",
                "   Modules marked **shared** are instantiated by multiple parents.",
                "   Their documentation appears once; all parents link to the same page.",
                "",
            ]

    return "\n".join(lines)


def entity_rst(entity: dict, src_file_rel: str = "") -> str:
    name  = entity["name"]
    fname = entity.get("file", f"{name}.vhd")
    ext   = fname.rsplit(".", 1)[-1].lower()
    is_sv = ext in ("sv", "svh")
    lang  = "systemverilog" if is_sv else "vhdl"
    title = f"{name} — Entity"
    # src_file_rel is the path from the entity's mod_dir to the source file.
    # Fall back to fname if not provided (legacy / flat-scan mode).
    lit_path = src_file_rel if src_file_rel else fname
    # Caption: prefer relative fname; if it's an absolute path use just the
    # filename so the caption stays readable.
    caption = fname if not Path(fname).is_absolute() else Path(fname).name

    lines = [title, "=" * len(title), "", f"Source file: ``{caption}``.", ""]

    if not is_sv:
        # sphinx-vhdl only handles VHDL entities
        lines += [f".. vhdl:autoentity:: {name}", ""]

    lines += [
        "Annotated Source",
        "----------------", "",
        f".. literalinclude:: {lit_path}",
        f"   :language: {lang}",
        "   :linenos:",
        f"   :caption: {caption}",
        "",
    ]
    return "\n".join(lines)


def reset_rst(entity: dict, module_dir: Path | None = None) -> str:
    name      = entity["name"]
    extracted = module_dir / f"{name}_reset.rst" if module_dir else None
    if extracted and extracted.exists():
        return "\n".join([f".. include:: {name}_reset.rst", ""])
    title = f"{name} — Reset Domain Analysis"
    return "\n".join([
        title, "=" * len(title), "",
        ".. note::", "",
        "   Reset domain analysis pending — run ``make extract`` to generate.", "",
    ])


def block_rst(entity: dict, module_dir: Path | None = None) -> str:
    name      = entity["name"]
    extracted = module_dir / f"{name}_block.rst" if module_dir else None
    if extracted and extracted.exists():
        return "\n".join([f".. include:: {name}_block.rst", ""])
    title = f"{name} — Block Diagram"
    return "\n".join([
        title, "=" * len(title), "",
        ".. note::", "",
        "   Block diagram pending — run ``make extract`` to generate.", "",
    ])


def cdc_rst(entity: dict, module_dir: Path | None = None) -> str:
    name        = entity["name"]
    extracted   = module_dir / f"{name}_cdc.rst" if module_dir else None
    if extracted and extracted.exists():
        return "\n".join([f".. include:: {name}_cdc.rst", ""])
    title = f"{name} — Clock Domain Analysis"
    return "\n".join([
        title, "=" * len(title), "",
        ".. note::", "",
        "   CDC analysis pending — run ``make extract`` to generate.", "",
    ])


def fsm_rst(entity: dict, module_dir: Path | None = None) -> str:
    name = entity["name"]
    # Only include if the extracted FSM rst actually exists
    if module_dir and (module_dir / f"{name}.rst").exists():
        return "\n".join([f".. include:: {name}.rst", ""])
    title = f"{name} — State Machine"
    return "\n".join([
        title, "=" * len(title), "",
        f"No FSM detected in ``{entity['file']}``.", "",
        "This module is either a structural wrapper (no combinational",
        "state logic) or uses a coding style not yet supported by the",
        "FSM extractor.", "",
    ])


def timing_rst(entity: dict, processes_dir: Path | None = None) -> str:
    name  = entity["name"]
    title = f"{name} — Timing Diagrams"

    lines = [
        title, "=" * len(title), "",
        f"All timing diagrams extracted from ``{entity['file']}``.",
        "Diagrams are sourced from ``.. wavedrom::`` blocks in the VHDL",
        "source comments above each process.",
        "",
    ]

    found_any = False
    if processes_dir and processes_dir.exists():
        for proc_file in sorted(processes_dir.glob("p_*.rst")):
            blocks = extract_wavedrom_blocks(proc_file.read_text())
            if not blocks:
                continue
            proc_name = proc_file.stem
            heading   = proc_name.replace("_", " ").title()
            lines += [heading, "-" * len(heading), ""]
            for block in blocks:
                lines.extend(block)
            found_any = True

    if not found_any:
        lines += [
            "No wavedrom diagrams found in process comments.", "",
            "Add ``.. wavedrom::`` blocks in the VHDL source above each",
            "process to have them appear here automatically.", "",
        ]

    return "\n".join(lines)


def extract_wavedrom_blocks(rst_text: str) -> list[list[str]]:
    blocks = []
    lines  = rst_text.splitlines()
    i      = 0
    while i < len(lines):
        if re.match(r"^\.\.\s+wavedrom::\s*$", lines[i]):
            block = [".. wavedrom::", ""]
            i += 1
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            while i < len(lines):
                line = lines[i]
                if line == "" or line.startswith("   "):
                    block.append(line)
                    i += 1
                else:
                    break
            while block and block[-1].strip() == "":
                block.pop()
            block.append("")
            blocks.append(block)
        else:
            i += 1
    return blocks


# ─────────────────────────────────────────────────────────────────────────────
# Top-level RST generators
# ─────────────────────────────────────────────────────────────────────────────

def hierarchy_dot(hierarchy: dict) -> str:
    """Graphviz dot for the full instantiation tree."""
    top     = hierarchy["top"]
    modules = hierarchy["modules"]
    lines   = [
        "digraph hierarchy {",
        "    rankdir=TB;",
        "    node [shape=box, style=filled, fillcolor=lightblue,",
        "          fontname=Helvetica, fontsize=12];",
        "    edge [fontname=Helvetica, fontsize=10];",
        "",
    ]
    # Style the top module distinctly
    lines.append(f'    {top} [fillcolor=lightgreen, style="filled,bold"];')
    lines.append("")
    # Mark shared nodes
    for name, mod in modules.items():
        if mod["shared"]:
            lines.append(
                f'    {name} [fillcolor=lightyellow, '
                f'label="{name}\\n(shared)"];'
            )
    lines.append("")
    # Edges
    visited_edges = set()
    for name, mod in modules.items():
        for child in mod["children"]:
            edge = (name, child)
            if edge not in visited_edges:
                lines.append(f"    {name} -> {child};")
                visited_edges.add(edge)
    lines.append("}")
    return "\n".join(lines)


def hierarchy_rst(hierarchy: dict) -> str:
    top     = hierarchy["top"]
    modules = hierarchy["modules"]
    shared  = [n for n, m in modules.items() if m["shared"]]
    title   = "Design Hierarchy"

    lines = [
        title, "=" * len(title), "",
        f"Top-level module: ``{top}``",
        f"Total modules: {len(modules)}",
        "",
        "Instantiation Tree", "-------------------", "",
        ".. graphviz:: hierarchy.dot", "",
    ]

    if shared:
        lines += [
            "Shared Components", "-----------------", "",
            "The following modules are instantiated by more than one parent:", "",
        ]
        for name in shared:
            parents = modules[name]["parents"]
            lines.append(f"- ``{name}`` — instantiated by: "
                         + ", ".join(f"``{p}``" for p in parents))
        lines.append("")

    lines += [
        "Module List", "-----------", "",
        ".. list-table::", "   :header-rows: 1", "",
        "   * - Module", "     - Source File", "     - Parents", "     - Children",
        "",
    ]
    for name in sorted(modules.keys()):
        mod = modules[name]
        parents  = ", ".join(f"``{p}``" for p in mod["parents"])  or "*(top)*"
        children = ", ".join(f"``{c}``" for c in mod["children"]) or "—"
        lines.append(f"   * - :doc:`modules/{name}/index`")
        lines.append(f"     - ``{mod['file']}``")
        lines.append(f"     - {parents}")
        lines.append(f"     - {children}")
        lines.append("")

    return "\n".join(lines)


def index_rst(entities: list[dict], project_name: str,
              hierarchy: dict | None = None) -> str:
    root_depth = toc_maxdepth(hierarchy) if hierarchy else 4
    lines = [
        project_name, "=" * len(project_name), "",
        ".. toctree::",
        f"   :maxdepth: {root_depth}",
        "   :caption: Contents",
        "",
        "   overview",
    ]

    if hierarchy:
        # List only the top module; it nests submodule toctrees beneath it.
        # maxdepth is computed from the actual hierarchy depth so every process
        # page is reachable without hardcoding a magic number.
        top = hierarchy["top"]
        lines += [
            f"   modules/{top}/index",
            "   hierarchy",
        ]
    else:
        for e in entities:
            lines.append(f"   modules/{e['name']}/index")
        lines.append("   registers")

    lines += [
        "",
        "Indices", "-------", "",
        "* :ref:`genindex`",
        "* :ref:`search`",
        "",
    ]
    return "\n".join(lines)


def overview_rst(entities: list[dict], project_name: str,
                 hierarchy: dict | None = None) -> str:
    title = f"{project_name} — Overview"
    lines = [
        title, "=" * len(title), "",
        f"This project contains {len(entities)} VHDL/SV "
        f"{'module' if len(entities) == 1 else 'modules'}.",
        "",
    ]

    if hierarchy:
        top = hierarchy["top"]
        lines += [
            f"Top-level module: :doc:`modules/{top}/index`", "",
        ]

    lines += [
        "Modules", "-------", "",
        ".. list-table::", "   :header-rows: 1", "",
        "   * - Module", "     - Source File", "     - Description", "",
    ]
    for e in entities:
        lines.append(f"   * - :doc:`modules/{e['name']}/index`")
        lines.append(f"     - ``{e['file']}``")
        lines.append(f"     - {e['brief']}")
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Usage: generate_rst.py <src_dir> <docs_dir>")

    src_dir  = Path(sys.argv[1])
    docs_dir = Path(sys.argv[2])

    # Project name — from argument, or derived from parent folder name
    GENERIC_NAMES = {"src", "docs", "files", "hdl", "rtl", "vhdl", "verilog",
                     "source", "sources", "project", "projects", "workspace"}

    if len(sys.argv) > 3 and sys.argv[3].strip():
        project_name = sys.argv[3].strip()
    else:
        candidate = docs_dir.resolve().parent
        for _ in range(4):
            if candidate.name.lower() not in GENERIC_NAMES:
                break
            candidate = candidate.parent
        project_name = candidate.name.replace("_", " ").replace("-", " ").title()

    print(f"Project: {project_name}")

    # Load hierarchy if available
    hierarchy = load_hierarchy(docs_dir)

    if hierarchy:
        print(f"Hierarchy mode: top={hierarchy['top']}, "
              f"{len(hierarchy['modules'])} modules")
        entities = []
        for name, hmod in hierarchy["modules"].items():
            e = entity_from_hierarchy(name, hmod)
            # Store the file path relative to src_dir so literalinclude
            # resolves correctly (e.g. "vhdl/<<NAME>>_tx.vhd" not "<<NAME>>_tx.vhd").
            src_file = Path(hmod["file"]).resolve()
            try:
                e["file"] = str(src_file.relative_to(src_dir.resolve()))
            except ValueError:
                # File is outside src_dir (e.g. out/regs/vhdl/) — keep absolute;
                # the literalinclude call site will use relpath from mod_dir.
                e["file"] = str(src_file)
            entities.append(e)
    else:
        print("Flat mode: scanning src/")
        entities = scan_src(src_dir)
        if not entities:
            sys.exit(f"ERROR: No VHDL/SV entities found in {src_dir}")

    print(f"Found {len(entities)} entities: {[e['name'] for e in entities]}")
    print("Generating RST files...")

    # Build lookup by name
    entity_map = {e["name"].lower(): e for e in entities}

    # Pre-compute toc maxdepth from the hierarchy tree so it grows automatically
    # when deeper designs are added, without any hardcoded magic numbers.
    sub_maxdepth = toc_maxdepth(hierarchy) if hierarchy else 4
    print(f"Hierarchy depth: {hierarchy_tree_depth(hierarchy) if hierarchy else 1}, "
          f"toctree maxdepth: {sub_maxdepth}")

    # Shared components set
    shared_names = set()
    if hierarchy:
        shared_names = {n for n, m in hierarchy["modules"].items() if m["shared"]}

    results = []

    for entity in entities:
        name    = entity["name"].lower()
        mod_dir = docs_dir / "modules" / name

        children = []
        if hierarchy and name in hierarchy["modules"]:
            children = hierarchy["modules"][name]["children"]

        # Always regenerated
        has_processes = (mod_dir / "processes" / "index.rst").exists()
        results.append(write_always(
            mod_dir / "index.rst",
            module_index_rst(entity, children, shared_names,
                             has_processes=has_processes,
                             is_top=bool(hierarchy and name == hierarchy["top"]),
                             sub_maxdepth=sub_maxdepth)
        ))
        results.append(write_always(
            mod_dir / "fsm.rst",
            fsm_rst(entity, module_dir=mod_dir)
        ))
        results.append(write_always(
            mod_dir / "timing.rst",
            timing_rst(entity, processes_dir=mod_dir / "processes")
        ))
        results.append(write_always(
            mod_dir / "cdc.rst",
            cdc_rst(entity, module_dir=mod_dir)
        ))
        results.append(write_always(
            mod_dir / "block.rst",
            block_rst(entity, module_dir=mod_dir)
        ))
        results.append(write_always(
            mod_dir / "reset.rst",
            reset_rst(entity, module_dir=mod_dir)
        ))

        # Write-if-missing
        # literalinclude paths must be relative to the RST file's own directory
        # (mod_dir).  entity["file"] is now relative to src_dir (set above at
        # the entities loop), OR an absolute path for files outside src/ (e.g.
        # out/regs/vhdl/).  Compute a single relpath from mod_dir → source file.
        import os as _os
        raw_file = entity.get("file", "")
        raw_path = Path(raw_file)
        if raw_path.is_absolute():
            src_file_abs = raw_path
        else:
            src_file_abs = (src_dir / raw_file).resolve()
        src_file_rel = _os.path.relpath(src_file_abs, mod_dir.resolve())
        results.append(write_if_missing(
            mod_dir / "entity.rst",
            entity_rst(entity, src_file_rel=src_file_rel)
        ))

    # Top-level always-regenerated
    results.append(write_always(
        docs_dir / "index.rst",
        index_rst(entities, project_name, hierarchy)
    ))
    results.append(write_always(
        docs_dir / "overview.rst",
        overview_rst(entities, project_name, hierarchy)
    ))

    if hierarchy:
        results.append(write_always(
            docs_dir / "hierarchy.dot",
            hierarchy_dot(hierarchy)
        ))
        results.append(write_always(
            docs_dir / "hierarchy.rst",
            hierarchy_rst(hierarchy)
        ))

    for r in results:
        print(r)