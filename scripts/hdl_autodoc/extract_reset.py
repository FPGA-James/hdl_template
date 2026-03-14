#!/usr/bin/env python3
"""
extract_reset.py
----------------
Analyzes VHDL or SystemVerilog source for reset domain information.

For each source file:
  - Identifies the reset signal and reset style (synchronous / asynchronous)
    for every labeled clocked process.
  - Flags clocked processes that have no reset.
  - Groups processes into reset domains keyed by reset signal.
  - Detects signals that cross between different reset domains (driven under
    one reset, read under another) — useful for identifying logic that may
    not be in a consistent state during partial or staggered reset release.
  - Writes <module_name>_reset.dot and <module_name>_reset.rst.

Reset style detection:
  VHDL async  — reset signal appears in process sensitivity list AND the
                first 'if X = ...' check precedes rising_edge/falling_edge.
  VHDL sync   — only the clock in sensitivity; reset check is inside the
                rising_edge/falling_edge block.
  SV async    — reset signal in @(...) sensitivity (e.g. posedge rst).
  SV sync     — only clock in @(...); reset check inside always_ff body.

Usage:
    python scripts/hdl_autodoc/extract_reset.py <file.vhd|sv> <module_name> <output_dir>
"""

import re
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Comment stripping
# ─────────────────────────────────────────────────────────────────────────────

def strip_vhdl_comments(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)

def strip_sv_comments(text: str) -> str:
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


# ─────────────────────────────────────────────────────────────────────────────
# Process reset info extraction
# ─────────────────────────────────────────────────────────────────────────────

_VHDL_PROC_RE   = re.compile(r"(\w+)\s*:\s*process\s*\((.*?)\)", re.IGNORECASE)
_VHDL_END_RE    = re.compile(r"\bend\s+process\b",                re.IGNORECASE)
_VHDL_EDGE_RE   = re.compile(r"(?:rising_edge|falling_edge)\s*\(\s*(\w+)\s*\)", re.IGNORECASE)
_VHDL_RESET_RE  = re.compile(r"\bif\s+(\w+)\s*=\s*'[01]'", re.IGNORECASE)

_SV_ALWAYS_RE   = re.compile(
    r"always_ff\s*@\s*\(([^)]*)\)[^:]*:\s*(\w+)",
    re.IGNORECASE | re.DOTALL,
)
_SV_EDGE_RE     = re.compile(r"(?:posedge|negedge)\s+(\w+)", re.IGNORECASE)
_SV_RESET_RE    = re.compile(r"\bif\s*\(\s*(\w+)\s*(?:[!=]=\s*\d+)?\s*\)", re.IGNORECASE)


def _reset_from_vhdl_body(body: str, sensitivity: list[str]) -> tuple[str | None, str]:
    """
    Infer reset signal and style from a VHDL process body.
    Returns (reset_signal | None, 'async' | 'sync' | 'none').
    """
    edge_m = _VHDL_EDGE_RE.search(body)
    if not edge_m:
        return None, "none"

    clock     = edge_m.group(1).lower()
    edge_pos  = edge_m.start()

    for m in _VHDL_RESET_RE.finditer(body):
        sig = m.group(1).lower()
        if sig == clock:
            continue
        if m.start() < edge_pos:
            return sig, "async"   # condition precedes rising_edge
        else:
            return sig, "sync"    # condition is inside rising_edge block

    return None, "none"


def _reset_from_sv_body(body: str, sens_str: str) -> tuple[str | None, str]:
    """
    Infer reset signal and style from an SV always_ff block.
    Returns (reset_signal | None, 'async' | 'sync' | 'none').
    """
    signals = [m.group(1).lower() for m in _SV_EDGE_RE.finditer(sens_str)]
    if not signals:
        return None, "none"

    clock = signals[0]

    if len(signals) >= 2:
        # Second edge-triggered signal is the async reset
        return signals[1], "async"

    # Only clock in sensitivity — look for sync reset inside body
    for m in _SV_RESET_RE.finditer(body):
        sig = m.group(1).lower()
        if sig != clock:
            return sig, "sync"

    return None, "none"


def extract_process_info_vhdl(text: str) -> list[dict]:
    """
    Return one dict per labeled clocked VHDL process:
    {label, clock, reset, style, sensitivity}
    style: 'async' | 'sync' | 'none'
    """
    stripped = strip_vhdl_comments(text)
    results  = []

    for m in _VHDL_PROC_RE.finditer(stripped):
        label       = m.group(1)
        sensitivity = [s.strip().lower() for s in m.group(2).split(",")]
        end_m = _VHDL_END_RE.search(stripped, m.end())
        if not end_m:
            continue
        body = stripped[m.start():end_m.end()]

        edge_m = _VHDL_EDGE_RE.search(body)
        if not edge_m:
            continue   # not a clocked process

        clock              = edge_m.group(1).lower()
        reset, reset_style = _reset_from_vhdl_body(body, sensitivity)
        results.append({
            "label":       label,
            "clock":       clock,
            "reset":       reset,
            "style":       reset_style,
            "sensitivity": sensitivity,
        })

    return results


def extract_process_info_sv(text: str) -> list[dict]:
    """
    Return one dict per labeled always_ff block:
    {label, clock, reset, style}
    style: 'async' | 'sync' | 'none'
    """
    stripped = strip_sv_comments(text)
    results  = []

    for m in _SV_ALWAYS_RE.finditer(stripped):
        sens_str = m.group(1)
        label    = m.group(2)

        edges = [e.group(1).lower() for e in _SV_EDGE_RE.finditer(sens_str)]
        if not edges:
            continue
        clock = edges[0]

        # Get process body
        pos   = m.end()
        depth = 1
        while pos < len(stripped) and depth > 0:
            bm = re.search(r"\bbegin\b|\bend\b", stripped[pos:], re.IGNORECASE)
            if not bm:
                break
            pos += bm.end()
            depth += 1 if bm.group(0).lower() == "begin" else -1
        body = stripped[m.start():pos]

        reset, reset_style = _reset_from_sv_body(body, sens_str)
        results.append({
            "label": label,
            "clock": clock,
            "reset": reset,
            "style": reset_style,
        })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Reset domain grouping
# ─────────────────────────────────────────────────────────────────────────────

def group_by_reset(processes: list[dict]) -> dict[str, list[dict]]:
    """
    Group process info dicts by their reset signal.
    Processes with no reset are grouped under the key '__none__'.
    """
    domains: dict[str, list[dict]] = {}
    for proc in processes:
        key = proc["reset"] or "__none__"
        domains.setdefault(key, []).append(proc)
    return domains


# ─────────────────────────────────────────────────────────────────────────────
# Signal crossing detection across reset domains
# ─────────────────────────────────────────────────────────────────────────────

_VHDL_KW = {
    "if", "then", "else", "elsif", "end", "begin", "process", "is", "when",
    "case", "and", "or", "not", "in", "out", "inout", "std_logic",
    "std_logic_vector", "rising_edge", "falling_edge", "others", "downto",
    "to", "signal", "variable", "constant", "library", "use", "entity",
    "architecture", "port", "generic", "map", "work", "ieee", "all",
}
_SV_KW = {
    "module", "endmodule", "input", "output", "inout", "logic", "wire",
    "reg", "always", "begin", "end", "if", "else", "case", "endcase",
    "assign", "parameter", "localparam", "always_ff", "always_comb",
    "posedge", "negedge", "initial", "default", "integer", "int",
}


def _get_process_body_vhdl(stripped: str, label: str) -> str:
    proc_re = re.compile(rf"\b{re.escape(label)}\s*:\s*process\b", re.IGNORECASE)
    end_re  = re.compile(r"\bend\s+process\b", re.IGNORECASE)
    m = proc_re.search(stripped)
    if not m:
        return ""
    end_m = end_re.search(stripped, m.end())
    return stripped[m.start():end_m.end()] if end_m else ""


def _get_process_body_sv(stripped: str, label: str) -> str:
    always_re = re.compile(
        rf"always_ff\s*@[^;]*?begin\s*:\s*{re.escape(label)}\b",
        re.IGNORECASE | re.DOTALL,
    )
    m = always_re.search(stripped)
    if not m:
        return ""
    pos, depth = m.end(), 1
    while pos < len(stripped) and depth > 0:
        bm = re.search(r"\bbegin\b|\bend\b", stripped[pos:], re.IGNORECASE)
        if not bm:
            break
        pos += bm.end()
        depth += 1 if bm.group(0).lower() == "begin" else -1
    return stripped[m.start():pos]


def _lhs(body: str, kw: set[str]) -> set[str]:
    return {
        m.group(1).lower()
        for m in re.finditer(r"\b([a-zA-Z_]\w*)\s*<=", body)
        if m.group(1).lower() not in kw
    }


def _rhs(body: str, own_lhs: set[str], kw: set[str]) -> set[str]:
    return {
        m.group(0).lower()
        for m in re.finditer(r"\b([a-zA-Z_]\w*)\b", body)
    } - kw - own_lhs


def find_reset_crossings(
    stripped: str,
    domains: dict[str, list[dict]],
    is_vhdl: bool,
) -> list[dict]:
    """
    Find signals driven in one reset domain and read in another.
    Returns list of {signal, src_reset, dst_reset}.
    """
    kw       = _VHDL_KW if is_vhdl else _SV_KW
    get_body = _get_process_body_vhdl if is_vhdl else _get_process_body_sv

    # Build per-domain LHS and RHS sets (aggregate across all processes in the domain)
    domain_lhs: dict[str, set[str]] = {}
    domain_rhs: dict[str, set[str]] = {}

    for reset_key, procs in domains.items():
        lhs: set[str] = set()
        rhs: set[str] = set()
        for proc in procs:
            body  = get_body(stripped, proc["label"])
            plhs  = _lhs(body, kw)
            prhs  = _rhs(body, plhs, kw)
            lhs  |= plhs
            rhs  |= prhs
        domain_lhs[reset_key] = lhs
        domain_rhs[reset_key] = rhs

    reset_names = set(domains.keys())
    crossings: list[dict] = []
    keys = list(domains.keys())

    for src in keys:
        for dst in keys:
            if src == dst:
                continue
            for sig in sorted(domain_lhs[src] & domain_rhs[dst] - reset_names):
                crossings.append({"signal": sig, "src_reset": src, "dst_reset": dst})

    return crossings


# ─────────────────────────────────────────────────────────────────────────────
# Graphviz dot writer
# ─────────────────────────────────────────────────────────────────────────────

_DOMAIN_COLORS = [
    ("#fce7f3", "#9d174d"),  # rose
    ("#fed7aa", "#c2410c"),  # orange
    ("#ede9fe", "#6d28d9"),  # purple
    ("#d1fae5", "#065f46"),  # green
    ("#e0f2fe", "#075985"),  # sky
]
_NO_RESET_COLOR = ("#fee2e2", "#dc2626")


def _safe(name: str) -> str:
    return re.sub(r"\W", "_", name)


def write_dot_reset(
    module_name: str,
    domains: dict[str, list[dict]],
    crossings: list[dict],
) -> str:
    """
    Graphviz diagram with one cluster per reset domain and edges for crossings.
    The '__none__' domain is rendered in red as a warning.
    """
    lines = [
        f"digraph {_safe(module_name)}_reset {{",
        "    compound=true;",
        "    rankdir=LR;",
        '    node [fontname="Helvetica", fontsize=11, shape=box, style=filled, fillcolor=white];',
        '    edge [fontname="Helvetica", fontsize=10];',
        "",
    ]

    # Assign colors — __none__ always gets the warning color
    domain_anchor: dict[str, str] = {}
    named_domains = {k: v for k, v in domains.items() if k != "__none__"}
    color_iter    = iter(_DOMAIN_COLORS)

    for reset_key, procs in named_domains.items():
        fill, border = next(color_iter, _DOMAIN_COLORS[-1])
        safe_key     = _safe(reset_key)
        style_tags   = list({p["style"] for p in procs} - {"none"})
        style_label  = f" ({', '.join(style_tags)})" if style_tags else ""
        lines += [
            f"    subgraph cluster_{safe_key} {{",
            f'        label="{reset_key}{style_label}";',
            f'        style=filled; fillcolor="{fill}"; color="{border}";',
            '        fontname="Helvetica Bold"; fontsize=13;',
            "",
        ]
        for proc in procs:
            nid = f"{safe_key}__{_safe(proc['label'])}"
            lines.append(f'        {nid} [label="{proc["label"]}\\n({proc["clock"]})"];')
            if safe_key not in domain_anchor:
                domain_anchor[safe_key] = nid
        lines += ["    }", ""]

    if "__none__" in domains:
        fill, border = _NO_RESET_COLOR
        lines += [
            "    subgraph cluster___none__ {",
            '        label="No Reset";',
            f'        style=filled; fillcolor="{fill}"; color="{border}";',
            '        fontname="Helvetica Bold"; fontsize=13;',
            "",
        ]
        for proc in domains["__none__"]:
            nid = f"__none____{_safe(proc['label'])}"
            lines.append(f'        {nid} [label="{proc["label"]}\\n({proc["clock"]})"];')
            if "__none__" not in domain_anchor:
                domain_anchor["__none__"] = nid
        lines += ["    }", ""]

    # Crossing edges
    if crossings:
        lines.append("    // Reset domain crossings")
        for c in crossings:
            src_key  = _safe(c["src_reset"])
            dst_key  = _safe(c["dst_reset"])
            src_node = domain_anchor.get(src_key, f"{src_key}__unknown")
            dst_node = domain_anchor.get(dst_key, f"{dst_key}__unknown")
            lines.append(
                f'    {src_node} -> {dst_node} ['
                f'label="{c["signal"]}", color="#dc2626", fontcolor="#dc2626", '
                f'style="dashed", '
                f'ltail="cluster_{src_key}", lhead="cluster_{dst_key}"];'
            )
        lines.append("")

    lines.append("}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# RST writers
# ─────────────────────────────────────────────────────────────────────────────

def _title(text: str) -> list[str]:
    return [text, "=" * len(text), ""]


def write_rst_no_clocks(module_name: str, src_filename: str) -> str:
    lines = _title(f"{module_name} — Reset Domain Analysis")
    lines += [
        f"Auto-extracted from ``{src_filename}``.", "",
        ".. note::", "",
        "   No clocked processes detected. "
        "This module appears to be purely combinational.", "",
    ]
    return "\n".join(lines)


def write_rst_single_domain(
    module_name: str,
    src_filename: str,
    reset_key: str,
    procs: list[dict],
) -> str:
    lines = _title(f"{module_name} — Reset Domain Analysis")
    lines += [f"Auto-extracted from ``{src_filename}``.", ""]

    if reset_key == "__none__":
        lines += [
            ".. warning::", "",
            "   All clocked processes in this module have **no reset**. "
            "Ensure initial state is handled by the synthesis tool or "
            "test infrastructure.", "",
        ]
    else:
        style_tags = list({p["style"] for p in procs} - {"none"})
        style_str  = " / ".join(style_tags) if style_tags else "unknown"
        lines += [
            ".. note::", "",
            f"   All clocked processes use a single reset domain "
            f"(``{reset_key}``, {style_str}). "
            "No reset domain crossings detected.", "",
        ]

    lines += [
        "Reset Domain", "------------", "",
        ".. list-table::", "   :header-rows: 1", "",
        "   * - Process", "     - Clock", "     - Reset", "     - Style", "",
    ]
    for p in procs:
        rst_str   = f"``{p['reset']}``" if p["reset"] else "—"
        style_str = p["style"].capitalize() if p["style"] != "none" else "—"
        lines += [
            f"   * - ``{p['label']}``",
            f"     - ``{p['clock']}``",
            f"     - {rst_str}",
            f"     - {style_str}",
            "",
        ]
    return "\n".join(lines)


def write_rst_multi_domain(
    module_name: str,
    src_filename: str,
    dot_filename: str,
    domains: dict[str, list[dict]],
    crossings: list[dict],
) -> str:
    lines = _title(f"{module_name} — Reset Domain Analysis")
    lines += [
        f"Auto-extracted from ``{src_filename}``.", "",
        f".. graphviz:: {dot_filename}", "",
    ]

    # ── Process table ─────────────────────────────────────────────────────────
    lines += [
        "Reset Domains", "-------------", "",
        ".. list-table::", "   :header-rows: 1", "",
        "   * - Process", "     - Clock", "     - Reset", "     - Style", "",
    ]
    for reset_key, procs in sorted(domains.items()):
        for p in procs:
            rst_str   = f"``{p['reset']}``" if p["reset"] else "—"
            style_str = p["style"].capitalize() if p["style"] != "none" else "—"
            lines += [
                f"   * - ``{p['label']}``",
                f"     - ``{p['clock']}``",
                f"     - {rst_str}",
                f"     - {style_str}",
                "",
            ]

    # ── No-reset warning ─────────────────────────────────────────────────────
    if "__none__" in domains:
        no_rst = [p["label"] for p in domains["__none__"]]
        sig_list = ", ".join(f"``{p}``" for p in no_rst)
        lines += [
            "",
            ".. warning::", "",
            f"   The following clocked process(es) have **no reset**: {sig_list}.", "",
        ]

    # ── Crossing table ────────────────────────────────────────────────────────
    if crossings:
        lines += [
            "",
            ".. warning::", "",
            "   The following signals cross between different reset domains. "
            "Logic driven under one reset may not be in a consistent state "
            "when the other reset releases.", "",
            "",
            "Signal Crossings", "----------------", "",
            ".. list-table::", "   :header-rows: 1", "",
            "   * - Signal", "     - Source Reset", "     - Destination Reset", "",
        ]
        for c in sorted(crossings, key=lambda x: x["signal"]):
            src = c["src_reset"] if c["src_reset"] != "__none__" else "*(none)*"
            dst = c["dst_reset"] if c["dst_reset"] != "__none__" else "*(none)*"
            lines += [
                f"   * - ``{c['signal']}``",
                f"     - ``{src}``",
                f"     - ``{dst}``",
                "",
            ]
    else:
        lines += [
            "",
            ".. note::", "",
            "   No direct signal crossings detected between reset domains.", "",
        ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit("Usage: extract_reset.py <file.vhd|sv> <module_name> <output_dir>")

    src_path    = Path(sys.argv[1])
    module_name = sys.argv[2]
    output_dir  = Path(sys.argv[3])
    output_dir.mkdir(parents=True, exist_ok=True)

    text = src_path.read_text()
    ext  = src_path.suffix.lower()

    if ext in (".vhd", ".vhdl"):
        is_vhdl  = True
        stripped = strip_vhdl_comments(text)
        procs    = extract_process_info_vhdl(text)
    elif ext in (".sv", ".svh"):
        is_vhdl  = False
        stripped = strip_sv_comments(text)
        procs    = extract_process_info_sv(text)
    else:
        sys.exit(f"ERROR: Unsupported file type '{ext}'")

    rst_path = output_dir / f"{module_name}_reset.rst"
    dot_path = output_dir / f"{module_name}_reset.dot"

    if not procs:
        rst_path.write_text(write_rst_no_clocks(module_name, src_path.name))
        print(f"  (no clocked processes in {src_path.name})")
        print(f"  → {rst_path}")
        sys.exit(0)

    domains = group_by_reset(procs)

    if len(domains) == 1:
        reset_key, domain_procs = next(iter(domains.items()))
        rst_path.write_text(
            write_rst_single_domain(module_name, src_path.name, reset_key, domain_procs)
        )
        label = reset_key if reset_key != "__none__" else "none"
        print(f"  (single reset domain '{label}') → {rst_path}")
        sys.exit(0)

    # Multiple reset domains
    crossings = find_reset_crossings(stripped, domains, is_vhdl)
    dot_filename = f"{module_name}_reset.dot"

    dot_path.write_text(write_dot_reset(module_name, domains, crossings))
    print(f"  → {dot_path}")

    rst_path.write_text(
        write_rst_multi_domain(
            module_name, src_path.name, dot_filename, domains, crossings
        )
    )
    print(f"  → {rst_path}")
