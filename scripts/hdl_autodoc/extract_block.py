#!/usr/bin/env python3
"""
extract_block.py
----------------
Extracts the port interface, generics/parameters, and internal signals from a
VHDL entity or SystemVerilog module and writes:

  <module_name>_block.dot  — Graphviz block diagram (inputs left, outputs right)
  <module_name>_block.rst  — RST page with the diagram, port table,
                              generics/parameters table, and signals table

Port comments are captured from:
  - Same-line:      clk : in std_logic;  -- System clock.
  - Preceding-line: -- System clock.
                    clk : in std_logic;

Bus widths are computed from the port range where possible and shown as edge
labels on the diagram (e.g. "8" for std_logic_vector(7 downto 0)).

Usage:
    python scripts/hdl_autodoc/extract_block.py <file.vhd|file.sv> <module_name> <output_dir>
"""

import re
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Section extraction (depth-aware, handles nested parens)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_paren_section(text: str, keyword: str) -> str:
    """
    Find 'keyword (' in text (ignoring VHDL -- comments when scanning) and
    return everything between the opening paren and its matching close paren.
    Returns an empty string if the keyword is not found.
    """
    # Replace comments with spaces of equal length so character indices stay valid
    stripped = re.sub(r"--[^\n]*", lambda m: " " * len(m.group(0)), text)
    m = re.compile(rf"\b{keyword}\s*\(", re.IGNORECASE).search(stripped)
    if not m:
        return ""

    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        ch = text[i]
        # Skip VHDL line comments when depth-counting
        if ch == "-" and i + 1 < len(text) and text[i + 1] == "-":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1

    return text[start:i]


# ─────────────────────────────────────────────────────────────────────────────
# Comment helpers
# ─────────────────────────────────────────────────────────────────────────────

def _inline_comment_vhdl(line: str) -> str:
    """Return text after -- on the line, or empty string."""
    m = re.search(r"--\s*(.*)", line)
    return m.group(1).strip() if m else ""


def _inline_comment_sv(line: str) -> str:
    """Return text after // on the line, or empty string."""
    m = re.search(r"//\s*(.*)", line)
    return m.group(1).strip() if m else ""


def _preceding_comment(lines: list[str], idx: int, prefix: str) -> str:
    """
    Look back from line idx for a comment line immediately above (ignoring
    blank lines).  Returns the comment text or empty string.
    """
    i = idx - 1
    while i >= 0 and lines[i].strip() == "":
        i -= 1
    if i >= 0 and lines[i].strip().startswith(prefix):
        return re.sub(rf"^{re.escape(prefix)}\s*", "", lines[i].strip()).strip()
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# VHDL extraction
# ─────────────────────────────────────────────────────────────────────────────

# Matches: name [, name2] : direction type[(range)]
_VHDL_PORT_RE = re.compile(
    r"(\w+(?:\s*,\s*\w+)*)\s*:\s*(in|out|inout)\s+"
    r"(std_logic(?:_vector)?|unsigned|signed|integer|natural|positive|"
    r"boolean|real|bit(?:_vector)?|std_ulogic(?:_vector)?|\w+)"
    r"(?:\s*\(\s*(.*?)\s*\))?",
    re.IGNORECASE,
)

# Matches: name : type := default
_VHDL_GENERIC_RE = re.compile(
    r"(\w+)\s*:\s*(\w+)\s*:=\s*([^;,\n]+)",
    re.IGNORECASE,
)


def extract_ports_vhdl(text: str) -> list[dict]:
    """
    Extract port declarations from a VHDL entity.
    Returns list of {name, dir, type, range, comment}.
    Comments are taken from same-line or the preceding comment line.
    """
    section = _extract_paren_section(text, "port")
    if not section:
        return []

    lines  = section.splitlines()
    ports  = []

    for idx, line in enumerate(lines):
        m = _VHDL_PORT_RE.search(re.sub(r"--.*", "", line))  # strip for matching
        if not m:
            continue

        comment = _inline_comment_vhdl(line) or _preceding_comment(lines, idx, "--")
        for name in [n.strip() for n in m.group(1).split(",")]:
            ports.append({
                "name":    name,
                "dir":     m.group(2).lower(),
                "type":    m.group(3).lower(),
                "range":   (m.group(4) or "").strip(),
                "comment": comment,
            })

    return ports


def extract_generics_vhdl(text: str) -> list[dict]:
    """
    Extract generic declarations from a VHDL entity.
    Returns list of {name, type, default, comment}.
    """
    section = _extract_paren_section(text, "generic")
    if not section:
        return []

    lines    = section.splitlines()
    generics = []

    for idx, line in enumerate(lines):
        m = _VHDL_GENERIC_RE.search(re.sub(r"--.*", "", line))
        if not m:
            continue

        comment = _inline_comment_vhdl(line) or _preceding_comment(lines, idx, "--")
        generics.append({
            "name":    m.group(1),
            "type":    m.group(2).lower(),
            "default": m.group(3).strip().rstrip(";,").strip(),
            "comment": comment,
        })

    return generics


# ─────────────────────────────────────────────────────────────────────────────
# SystemVerilog extraction
# ─────────────────────────────────────────────────────────────────────────────

# Matches: input/output/inout [logic/wire/reg] [[range]] name
_SV_PORT_RE = re.compile(
    r"^\s*(input|output|inout)\s+"
    r"(?:(logic|wire|reg|bit)\s*)?"
    r"(?:\[([^\]]*)\]\s*)?"
    r"(\w+)",
    re.IGNORECASE,
)

# Matches: parameter [type] name = default
_SV_PARAM_RE = re.compile(
    r"^\s*(parameter|localparam)\s+(?:(\w+)\s+)?(\w+)\s*=\s*([^,;/]+)",
    re.IGNORECASE,
)


def extract_ports_sv(text: str) -> list[dict]:
    """
    Extract port declarations from a SystemVerilog module.
    Returns list of {name, dir, type, range, comment}.
    """
    lines = text.splitlines()
    ports = []

    for idx, line in enumerate(lines):
        m = _SV_PORT_RE.match(line)
        if not m:
            continue

        comment = _inline_comment_sv(line) or _preceding_comment(lines, idx, "//")
        # Normalise SV "input"/"output" to "in"/"out" to match VHDL convention
        raw_dir = m.group(1).lower()
        norm_dir = {"input": "in", "output": "out"}.get(raw_dir, raw_dir)
        ports.append({
            "name":    m.group(4),
            "dir":     norm_dir,
            "type":    (m.group(2) or "logic").lower(),
            "range":   (m.group(3) or "").strip(),
            "comment": comment,
        })

    return ports


def extract_params_sv(text: str) -> list[dict]:
    """
    Extract parameter and localparam declarations from a SystemVerilog module.
    Returns list of {name, type, default, comment, kind}.
    """
    lines  = text.splitlines()
    params = []

    for idx, line in enumerate(lines):
        m = _SV_PARAM_RE.match(line)
        if not m:
            continue

        comment = _inline_comment_sv(line) or _preceding_comment(lines, idx, "//")
        params.append({
            "name":    m.group(3),
            "type":    (m.group(2) or "").lower(),
            "default": m.group(4).strip().rstrip(",;").strip(),
            "comment": comment,
            "kind":    m.group(1).lower(),
        })

    return params


# ─────────────────────────────────────────────────────────────────────────────
# Internal signal extraction
# ─────────────────────────────────────────────────────────────────────────────

# Matches: signal name [, name2] : type[(range)] [:= init]
_VHDL_SIGNAL_RE = re.compile(
    r"^\s*signal\s+(\w+(?:\s*,\s*\w+)*)\s*:\s*([\w_]+)"
    r"(?:\s*\(\s*(.*?)\s*\))?"
    r"(?:\s*:=\s*([^;]+))?",
    re.IGNORECASE,
)

# Matches internal SV: logic/wire/reg [[range]] name [, name2]
_SV_SIGNAL_RE = re.compile(
    r"^\s*(logic|wire|reg)\s*(?:\[([^\]]*)\]\s*)?(\w+(?:\s*,\s*\w+)*)\s*;",
    re.IGNORECASE,
)

_SV_PORT_KW = {"input", "output", "inout"}


def extract_signals_vhdl(text: str) -> list[dict]:
    """
    Extract internal signal declarations from a VHDL architecture.

    Scans the declaration region between 'architecture X of Y is' and the
    first bare 'begin' line.  Returns list of {name, type, range, init, comment}.
    Comments from the preceding line or same line are captured.
    """
    lines = text.splitlines()

    arch_re  = re.compile(r"^\s*architecture\s+\w+\s+of\s+\w+\s+is\b", re.IGNORECASE)
    begin_re = re.compile(r"^\s*begin\s*$", re.IGNORECASE)

    decl_lines: list[str] = []
    in_decl = False
    for line in lines:
        if not in_decl:
            if arch_re.match(line):
                in_decl = True
        else:
            if begin_re.match(line):
                break
            decl_lines.append(line)

    signals = []
    for idx, line in enumerate(decl_lines):
        m = _VHDL_SIGNAL_RE.search(re.sub(r"--.*", "", line))
        if not m:
            continue
        comment = _inline_comment_vhdl(line) or _preceding_comment(decl_lines, idx, "--")
        for name in [n.strip() for n in m.group(1).split(",")]:
            signals.append({
                "name":    name,
                "type":    m.group(2).lower(),
                "range":   (m.group(3) or "").strip(),
                "init":    (m.group(4) or "").strip().rstrip(";").strip(),
                "comment": comment,
            })
    return signals


def extract_signals_sv(text: str) -> list[dict]:
    """
    Extract internal signal declarations from a SystemVerilog module.

    Matches 'logic', 'wire', or 'reg' declarations that are not port
    declarations (i.e. not prefixed with input/output/inout).
    Returns list of {name, type, range, init, comment}.
    """
    lines   = text.splitlines()
    signals = []

    for idx, line in enumerate(lines):
        stripped = line.strip().lower()
        if any(stripped.startswith(k) for k in _SV_PORT_KW):
            continue
        m = _SV_SIGNAL_RE.match(line)
        if not m:
            continue
        comment = _inline_comment_sv(line) or _preceding_comment(lines, idx, "//")
        for name in [n.strip() for n in m.group(3).split(",")]:
            signals.append({
                "name":    name,
                "type":    m.group(1).lower(),
                "range":   (m.group(2) or "").strip(),
                "init":    "",
                "comment": comment,
            })
    return signals


# ─────────────────────────────────────────────────────────────────────────────
# Width label helper
# ─────────────────────────────────────────────────────────────────────────────

def _width_label(port: dict) -> str:
    """
    Return a compact width string for diagram edge labels.
    Computes the numeric width from downto/to ranges where possible;
    returns the raw range expression for parametric widths.
    """
    rng = port.get("range", "")
    if rng:
        # Numeric: "7 downto 0" or "7:0"
        m = re.match(r"(\d+)\s+(?:downto|to)\s+(\d+)", rng, re.IGNORECASE)
        if m:
            return str(abs(int(m.group(1)) - int(m.group(2))) + 1)
        m = re.match(r"(\d+)\s*:\s*(\d+)", rng)
        if m:
            return str(abs(int(m.group(1)) - int(m.group(2))) + 1)
        # Parametric: return the expression
        return f"[{rng}]"

    t = port.get("type", "").lower()
    if t in ("integer", "natural", "positive", "real", "int"):
        return t
    return "1"


# ─────────────────────────────────────────────────────────────────────────────
# Graphviz dot writer  (TerosHDL-inspired style)
# ─────────────────────────────────────────────────────────────────────────────

import html as _html

def _safe(name: str) -> str:
    return re.sub(r"\W", "_", name)


def write_dot_block(module_name: str, ports: list[dict],
                    generics: list[dict]) -> str:
    """
    Generate a TerosHDL-inspired block diagram using Graphviz HTML table labels.

    Layout mirrors the TerosHDL documenter output:
      - Green box (top):   generics/parameters, one per row, stub on the left.
      - Yellow box (below): port interface.
          Left column  — inputs  (► name [width])
          Right column — outputs (name ◄)
      - Thick black stub lines on both sides; bus width labels on output stubs.

    Two separate flat-table nodes are used so that PORT attributes work for
    precise per-row edge attachment.  rank=same keeps them in one column;
    an invisible edge orders gen_box above port_box.
    """
    safe_mod   = _safe(module_name)
    inputs     = [p for p in ports if p["dir"] == "in"]
    outputs    = [p for p in ports if p["dir"] == "out"]
    inouts     = [p for p in ports if p["dir"] == "inout"]
    left_ports = inputs + inouts
    n_rows     = max(len(left_ports), len(outputs), 1)
    _ONE_BIT   = {"1", "integer", "natural", "positive", "real", "int"}

    lines = [
        f"digraph {safe_mod}_block {{",
        "    rankdir=LR;",
        "    nodesep=0.5;",
        "    ranksep=0.8;",
        '    node [fontname="Helvetica", fontsize=12, shape=none, margin=0];',
        '    edge [dir=none, penwidth=2.5, color="black"];',
        "",
    ]

    # ── Generics box (green) ──────────────────────────────────────────────────
    if generics:
        gen_rows = []
        for g in generics:
            name    = _html.escape(g["name"])
            default = f' = {_html.escape(str(g["default"]))}' if g.get("default") else ""
            gen_rows.append(
                f'<TR>'
                f'<TD PORT="g_{_safe(g["name"])}" ALIGN="LEFT" CELLPADDING="5">'
                f'{name}{default}'
                f'</TD>'
                f'</TR>'
            )
        gen_label = (
            '<\n        '
            '<TABLE BORDER="2" CELLBORDER="0" CELLSPACING="3" CELLPADDING="0"'
            ' BGCOLOR="#c8f5c4" COLOR="#1a5c1a">\n          '
            + "\n          ".join(gen_rows)
            + "\n        </TABLE>>"
        )
        lines += [
            f"    // Generics box",
            f"    gen_box_{safe_mod} [label={gen_label}];",
            "",
        ]

    # ── Ports box (yellow) ────────────────────────────────────────────────────
    port_rows = []
    for i in range(n_rows):
        lp = left_ports[i] if i < len(left_ports) else None
        rp = outputs[i]    if i < len(outputs)    else None

        if lp:
            w     = _width_label(lp)
            sym   = "&#x25C2;&#x25B8;" if lp["dir"] == "inout" else "&#x25B8;"
            # _width_label returns "[expr]" for parametric, bare number for numeric
            _w_display = w if w.startswith("[") else f"[{w}]"
            w_ann = f' {_html.escape(_w_display)}' if w not in _ONE_BIT else ""
            left_td = (
                f'<TD PORT="i_{_safe(lp["name"])}" ALIGN="LEFT" CELLPADDING="5">'
                f'{sym} {_html.escape(lp["name"])}{w_ann}</TD>'
            )
        else:
            left_td = '<TD CELLPADDING="5"> </TD>'

        if rp:
            right_td = (
                f'<TD PORT="o_{_safe(rp["name"])}" ALIGN="RIGHT" CELLPADDING="5">'
                f'{_html.escape(rp["name"])} &#x25C2;</TD>'
            )
        else:
            right_td = '<TD CELLPADDING="5"> </TD>'

        port_rows.append(
            f'<TR>{left_td}<TD WIDTH="50"> </TD>{right_td}</TR>'
        )

    port_label = (
        '<\n        '
        '<TABLE BORDER="2" CELLBORDER="0" CELLSPACING="3" CELLPADDING="0"'
        ' BGCOLOR="#fffde7" COLOR="#5d4200">\n          '
        + "\n          ".join(port_rows)
        + "\n        </TABLE>>"
    )
    lines += [
        f"    // Ports box",
        f"    port_box_{safe_mod} [label={port_label}];",
        "",
    ]

    # ── Stack gen_box above port_box (rank=same + invisible ordering edge) ────
    if generics:
        lines += [
            f"    {{ rank=same; gen_box_{safe_mod}; port_box_{safe_mod} }}",
            f"    gen_box_{safe_mod} -> port_box_{safe_mod}"
            f' [style=invis, weight=100];',
            "",
        ]

    lines.append("}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# RST writer
# ─────────────────────────────────────────────────────────────────────────────

_DIR_RST = {"in": "``in``", "out": "``out``", "inout": "``inout``"}


def _type_str(port: dict) -> str:
    """
    Format port type + range as a readable string.
    VHDL uses parentheses: std_logic_vector(7 downto 0)
    SV uses square brackets:  logic[7:0]
    Detected from whether the range contains 'downto'/'to' (VHDL) or ':' (SV).
    """
    t = port["type"]
    r = port["range"]
    if r:
        if re.search(r"\bdownto\b|\bto\b", r, re.IGNORECASE):
            return f"``{t}({r})``"   # VHDL
        return f"``{t}[{r}]``"       # SV
    return f"``{t}``"


def write_rst_block(module_name: str, src_filename: str,
                    ports: list[dict], generics: list[dict],
                    signals: list[dict],
                    include_schematic: bool = False) -> str:
    dot_file = f"{module_name}_block.dot"
    title    = f"{module_name} — Block Diagram"
    lines    = [title, "=" * len(title), "",
                f"Auto-extracted from ``{src_filename}``.", "",
                f".. graphviz:: {dot_file}", ""]

    # ── Port table ──────────────────────────────────────────────────────────
    if ports:
        lines += [
            "Ports", "-----", "",
            ".. list-table::", "   :header-rows: 1", "",
            "   * - Port", "     - Direction", "     - Type", "     - Description", "",
        ]
        for p in ports:
            lines += [
                f'   * - ``{p["name"]}``',
                f'     - {_DIR_RST.get(p["dir"], p["dir"])}',
                f'     - {_type_str(p)}',
                f'     - {p["comment"] or "—"}',
                "",
            ]

    # ── Generics / parameters table ──────────────────────────────────────────
    if generics:
        heading = "Generics" if any(
            g.get("kind", "generic") == "generic" or "kind" not in g
            for g in generics
        ) else "Parameters"

        lines += [
            "",
            heading, "-" * len(heading), "",
            ".. list-table::", "   :header-rows: 1", "",
            "   * - Name", "     - Type", "     - Default", "     - Description", "",
        ]
        for g in generics:
            type_str = f'``{g["type"]}``' if g.get("type") else "—"
            lines += [
                f'   * - ``{g["name"]}``',
                f'     - {type_str}',
                f'     - ``{g["default"]}``',
                f'     - {g["comment"] or "—"}',
                "",
            ]

    # ── Signals table ────────────────────────────────────────────────────────
    if signals:
        lines += [
            "",
            "Signals", "-------", "",
            ".. list-table::", "   :header-rows: 1", "",
            "   * - Signal", "     - Type", "     - Description", "",
        ]
        for s in signals:
            lines += [
                f'   * - ``{s["name"]}``',
                f'     - {_type_str(s)}',
                f'     - {s["comment"] or "—"}',
                "",
            ]

    # ── RTL Schematic (optional — only present when SCHEMATICS=1) ────────────
    if include_schematic:
        schematic_svg = f"{module_name}_schematic.svg"
        lines += [
            "",
            "RTL Schematic", "-------------", "",
            "Gate-level netlist generated by ``yosys`` and rendered with ``netlistsvg``.", "",
            f".. image:: {schematic_svg}",
            "   :align: center", "",
        ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit("Usage: extract_block.py <file.vhd|file.sv> <module_name> <output_dir>")

    src_path    = Path(sys.argv[1])
    module_name = sys.argv[2]
    output_dir  = Path(sys.argv[3])
    output_dir.mkdir(parents=True, exist_ok=True)

    text = src_path.read_text()
    ext  = src_path.suffix.lower()

    if ext in (".vhd", ".vhdl"):
        ports    = extract_ports_vhdl(text)
        generics = extract_generics_vhdl(text)
        signals  = extract_signals_vhdl(text)
    elif ext in (".sv", ".svh"):
        ports    = extract_ports_sv(text)
        generics = extract_params_sv(text)
        signals  = extract_signals_sv(text)
    else:
        sys.exit(f"ERROR: Unsupported file type '{ext}'")

    dot_path = output_dir / f"{module_name}_block.dot"
    rst_path = output_dir / f"{module_name}_block.rst"

    # Include RTL schematic section if generate_schematic.py already wrote the SVG.
    schematic_svg = output_dir / f"{module_name}_schematic.svg"
    include_schematic = schematic_svg.exists()

    dot_path.write_text(write_dot_block(module_name, ports, generics))
    print(f"  → {dot_path}")

    rst_path.write_text(write_rst_block(module_name, src_path.name, ports, generics, signals,
                                        include_schematic))
    print(f"  → {rst_path}")
