#!/usr/bin/env python3
"""
extract_cdc.py
--------------
Analyzes VHDL or SystemVerilog source for clock domain crossings.

For each source file:
  - Identifies clock domains from clocked process / always_ff blocks.
  - Finds signals driven in one domain and read in another.
  - Detects two-flop synchronizer patterns and marks crossings as synchronized.
  - Detects dual-clock instances (async FIFOs etc.) by inspecting port maps for
    clock-named ports connected to different signals.
  - Writes <module_name>_cdc.rst into the output directory.

If only one clock domain is found the page states "No CDC — single clock domain."
If no clocked blocks are found the page notes the module appears combinational.

Usage:
    python scripts/hdl_autodoc/extract_cdc.py <file.vhd|file.sv> <module_name> <output_dir>
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
# Clock domain identification
# ─────────────────────────────────────────────────────────────────────────────

def extract_domains_vhdl(text: str) -> dict[str, list[str]]:
    """
    Returns { clock_name: [process_label, ...] }.
    Detects labeled processes that contain rising_edge(X) or falling_edge(X).
    """
    stripped = strip_vhdl_comments(text)
    domains  = {}
    proc_re  = re.compile(r"(\w+)\s*:\s*process\b", re.IGNORECASE)
    end_re   = re.compile(r"\bend\s+process\b",      re.IGNORECASE)
    edge_re  = re.compile(r"(?:rising_edge|falling_edge)\s*\(\s*(\w+)\s*\)", re.IGNORECASE)

    for m in proc_re.finditer(stripped):
        label = m.group(1)
        end_m = end_re.search(stripped, m.end())
        if not end_m:
            continue
        body    = stripped[m.start():end_m.end()]
        edge_m  = edge_re.search(body)
        if edge_m:
            clock = edge_m.group(1).lower()
            domains.setdefault(clock, []).append(label)

    return domains


def extract_domains_sv(text: str) -> dict[str, list[str]]:
    """
    Returns { clock_name: [process_label, ...] }.
    Detects always_ff @(posedge/negedge X) begin : label patterns.
    """
    stripped  = strip_sv_comments(text)
    domains   = {}
    always_re = re.compile(
        r"always_ff\s*@\s*\(\s*(?:posedge|negedge)\s+(\w+)[^)]*\)"
        r"[^:]*begin\s*:\s*(\w+)",
        re.IGNORECASE | re.DOTALL,
    )
    for m in always_re.finditer(stripped):
        clock = m.group(1).lower()
        label = m.group(2)
        domains.setdefault(clock, []).append(label)

    return domains


# ─────────────────────────────────────────────────────────────────────────────
# Process body extraction
# ─────────────────────────────────────────────────────────────────────────────

def get_process_body_vhdl(stripped: str, label: str) -> str:
    proc_re = re.compile(rf"\b{re.escape(label)}\s*:\s*process\b", re.IGNORECASE)
    end_re  = re.compile(r"\bend\s+process\b", re.IGNORECASE)
    m = proc_re.search(stripped)
    if not m:
        return ""
    end_m = end_re.search(stripped, m.end())
    if not end_m:
        return ""
    return stripped[m.start():end_m.end()]


def get_process_body_sv(stripped: str, label: str) -> str:
    # Match always_ff ... begin : label, then scan to matching end
    always_re = re.compile(
        rf"always_ff\s*@[^;]*?begin\s*:\s*{re.escape(label)}\b",
        re.IGNORECASE | re.DOTALL,
    )
    m = always_re.search(stripped)
    if not m:
        return ""
    pos   = m.end()
    depth = 1
    while pos < len(stripped) and depth > 0:
        bm = re.search(r"\bbegin\b|\bend\b", stripped[pos:], re.IGNORECASE)
        if not bm:
            break
        pos += bm.end()
        depth += 1 if bm.group(0).lower() == "begin" else -1
    return stripped[m.start():pos]


# ─────────────────────────────────────────────────────────────────────────────
# Signal collection
# ─────────────────────────────────────────────────────────────────────────────

_VHDL_KW = {
    "if", "then", "else", "elsif", "end", "begin", "process", "is", "when",
    "case", "and", "or", "not", "in", "out", "inout", "std_logic",
    "std_logic_vector", "rising_edge", "falling_edge", "others", "downto",
    "to", "signal", "variable", "constant", "library", "use", "entity",
    "architecture", "port", "generic", "map", "work", "ieee", "all",
    "std_logic_1164", "numeric_std", "unsigned", "signed",
}

_SV_KW = {
    "module", "endmodule", "input", "output", "inout", "logic", "wire",
    "reg", "always", "begin", "end", "if", "else", "case", "endcase",
    "assign", "parameter", "localparam", "typedef", "enum", "struct",
    "import", "always_ff", "always_comb", "always_latch", "posedge",
    "negedge", "initial", "generate", "endgenerate", "for", "while",
    "function", "endfunction", "task", "endtask", "default", "integer",
    "int", "bit",
}


def lhs_signals(body: str, keywords: set[str]) -> set[str]:
    """Identifiers on the left-hand side of <= assignments."""
    return {
        m.group(1).lower()
        for m in re.finditer(r"\b([a-zA-Z_]\w*)\s*<=", body)
        if m.group(1).lower() not in keywords
    }


def rhs_identifiers(body: str, own_lhs: set[str], keywords: set[str]) -> set[str]:
    """All identifiers in body that are not LHS-assigned here (i.e. signals being read)."""
    all_ids = {
        m.group(0).lower()
        for m in re.finditer(r"\b([a-zA-Z_]\w*)\b", body)
    }
    return all_ids - keywords - own_lhs


def collect_domain_signals(
    stripped: str, domains: dict[str, list[str]],
    is_vhdl: bool
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """
    Returns (domain_lhs, domain_rhs) dicts keyed by clock name.
    domain_lhs[clk] = signals driven in that domain.
    domain_rhs[clk] = signals read in that domain.
    """
    kw       = _VHDL_KW if is_vhdl else _SV_KW
    get_body = get_process_body_vhdl if is_vhdl else get_process_body_sv

    domain_lhs: dict[str, set[str]] = {}
    domain_rhs: dict[str, set[str]] = {}

    for clock, labels in domains.items():
        lhs: set[str] = set()
        rhs: set[str] = set()
        for label in labels:
            body = get_body(stripped, label)
            plhs = lhs_signals(body, kw)
            prhs = rhs_identifiers(body, plhs, kw)
            lhs |= plhs
            rhs |= prhs
        domain_lhs[clock] = lhs
        domain_rhs[clock] = rhs

    return domain_lhs, domain_rhs


# ─────────────────────────────────────────────────────────────────────────────
# Two-flop synchronizer detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_synchronizers(stripped: str, crossing_signals: set[str]) -> set[str]:
    """
    Detect two-flop synchronizer chains.

    Looks for:
        sync1 <= crossing_signal;
        sync2 <= sync1;

    anywhere in the file (both registers must be in the same domain, but we
    rely on structural pattern matching rather than domain membership here).
    Returns the subset of crossing_signals that appear to be synchronized.
    """
    # Build simple direct-assignment map: dest -> {source, ...}
    assign_re   = re.compile(r"\b(\w+)\s*<=\s*(\w+)\s*;")
    driven_from: dict[str, set[str]] = {}
    for m in assign_re.finditer(stripped):
        driven_from.setdefault(m.group(1).lower(), set()).add(m.group(2).lower())

    synchronized: set[str] = set()
    for sig in crossing_signals:
        # Find registers immediately driven by this signal
        intermediates = [d for d, srcs in driven_from.items() if sig in srcs]
        for inter in intermediates:
            # Is inter then further registered by something else?
            if any(inter in srcs for d, srcs in driven_from.items() if d != inter):
                synchronized.add(sig)
                break

    return synchronized


# ─────────────────────────────────────────────────────────────────────────────
# Dual-clock instance detection (async FIFO etc.)
# ─────────────────────────────────────────────────────────────────────────────

_CLK_PORT_RE = re.compile(r"^.*?\b(?:clk|clock|ck)\b.*?$", re.IGNORECASE)


def _is_clock_port(name: str) -> bool:
    return bool(re.search(r"(?:clk|clock|ck)", name, re.IGNORECASE))


def detect_dual_clock_instances_vhdl(stripped: str) -> list[dict]:
    """
    Find VHDL port map instances where 2+ clock-named ports connect to different signals.
    """
    results  = []
    # label : [entity work.]component [generic map (...)] port map (...)
    inst_re  = re.compile(
        r"(\w+)\s*:\s*(?:entity\s+\w+\s*\.\s*)?(\w+)\s*"
        r"(?:generic\s+map\s*\([^)]*\)\s*)?"
        r"port\s+map\s*\(([^;]*?)\)\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    assoc_re = re.compile(r"(\w+)\s*=>\s*(\w+)", re.IGNORECASE)

    for m in inst_re.finditer(stripped):
        inst_label = m.group(1)
        component  = m.group(2)
        port_map   = m.group(3)

        clock_ports: dict[str, str] = {}
        for am in assoc_re.finditer(port_map):
            port, signal = am.group(1), am.group(2)
            if _is_clock_port(port):
                clock_ports[port] = signal.lower()

        if len(set(clock_ports.values())) >= 2:
            results.append({
                "instance":  inst_label,
                "component": component,
                "clocks":    clock_ports,
            })

    return results


def detect_dual_clock_instances_sv(stripped: str) -> list[dict]:
    """
    Find SV instances where 2+ clock-named ports connect to different signals.
    """
    results  = []
    _kw      = {k.lower() for k in _SV_KW}
    # module_name [#(...)] inst_name (connections);
    inst_re  = re.compile(
        r"^\s*(\w+)\s*(?:#\s*\([^)]*\)\s*)?(\w+)\s*\(([^;]*)\)\s*;",
        re.MULTILINE | re.DOTALL,
    )
    named_re = re.compile(r"\.(\w+)\s*\(\s*(\w+)\s*\)")

    for m in inst_re.finditer(stripped):
        component, inst_label, port_body = m.group(1), m.group(2), m.group(3)
        if component.lower() in _kw:
            continue

        clock_ports: dict[str, str] = {}
        for pm in named_re.finditer(port_body):
            port, signal = pm.group(1), pm.group(2)
            if _is_clock_port(port):
                clock_ports[port] = signal.lower()

        if len(set(clock_ports.values())) >= 2:
            results.append({
                "instance":  inst_label,
                "component": component,
                "clocks":    clock_ports,
            })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Graphviz dot writer
# ─────────────────────────────────────────────────────────────────────────────

# Color pairs (fill, border) cycled across domains
_DOMAIN_COLORS = [
    ("#dbeafe", "#1d4ed8"),  # blue
    ("#fef9c3", "#b45309"),  # amber
    ("#dcfce7", "#15803d"),  # green
    ("#fce7f3", "#9d174d"),  # pink
    ("#ede9fe", "#6d28d9"),  # purple
]


def _safe(name: str) -> str:
    """Return a Graphviz-safe identifier."""
    return re.sub(r"\W", "_", name)


def write_dot_cdc(module_name: str, domains: dict[str, list[str]],
                  crossings: list[dict],
                  dual_clk_instances: list[dict]) -> str:
    lines = [
        f"digraph {_safe(module_name)}_cdc {{",
        "    compound=true;",
        "    rankdir=LR;",
        '    node [fontname="Helvetica", fontsize=11, shape=box,'
        ' style=filled, fillcolor=white];',
        '    edge [fontname="Helvetica", fontsize=10];',
        "",
    ]

    # One anchor node per domain (first process) used as edge attachment point
    domain_anchor: dict[str, str] = {}

    for i, (clock, procs) in enumerate(sorted(domains.items())):
        fill, border = _DOMAIN_COLORS[i % len(_DOMAIN_COLORS)]
        safe_clk = _safe(clock)
        lines += [
            f"    subgraph cluster_{safe_clk} {{",
            f'        label="{clock}";',
            f"        style=filled;",
            f'        fillcolor="{fill}";',
            f'        color="{border}";',
            f'        fontname="Helvetica Bold";',
            f"        fontsize=13;",
            "",
        ]
        for proc in procs:
            node_id = f"{safe_clk}__{_safe(proc)}"
            lines.append(f'        {node_id} [label="{proc}"];')
            if safe_clk not in domain_anchor:
                domain_anchor[safe_clk] = node_id
        lines += ["    }", ""]

    # CDC crossing edges
    if crossings:
        lines.append("    // CDC signal crossings")
        for c in crossings:
            src_safe  = _safe(c["src_clock"])
            dst_safe  = _safe(c["dst_clock"])
            src_node  = domain_anchor.get(src_safe, f"{src_safe}__unknown")
            dst_node  = domain_anchor.get(dst_safe, f"{dst_safe}__unknown")
            if c["synchronized"]:
                color, style, tag = "#16a34a", "solid",  "(synchronized)"
            else:
                color, style, tag = "#dc2626", "dashed", "(unsynchronized)"
            label = f'{c["signal"]}\\n{tag}'
            lines.append(
                f'    {src_node} -> {dst_node} ['
                f'label="{label}", color="{color}", fontcolor="{color}", '
                f'style="{style}", '
                f'ltail="cluster_{src_safe}", lhead="cluster_{dst_safe}"];'
            )
        lines.append("")

    # Dual-clock instances as a separate cluster
    if dual_clk_instances:
        lines += [
            "    // Dual-clock instances",
            "    subgraph cluster_dual_clk {",
            '        label="Dual-Clock Instances";',
            '        style=filled; fillcolor="#f3f4f6"; color="#6b7280";',
            '        fontname="Helvetica Bold"; fontsize=13;',
            "",
        ]
        for fi in dual_clk_instances:
            node_id     = f'fifo__{_safe(fi["instance"])}'
            port_labels = "\\n".join(
                f'{p} \u2192 {s}' for p, s in fi["clocks"].items()
            )
            lines.append(
                f'        {node_id} [label="{fi["instance"]}\\n'
                f'({fi["component"]})\\n{port_labels}", '
                f'shape=record, fillcolor="#e5e7eb"];'
            )
        lines += ["    }", ""]

    lines.append("}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# RST writers
# ─────────────────────────────────────────────────────────────────────────────

def _title(text: str) -> list[str]:
    return [text, "=" * len(text), ""]


def write_rst_no_clocks(module_name: str, src_filename: str) -> str:
    lines = _title(f"{module_name} — Clock Domain Analysis")
    lines += [
        f"Auto-extracted from ``{src_filename}``.", "",
        ".. note::", "",
        "   No clocked processes detected. "
        "This module appears to be purely combinational.", "",
    ]
    return "\n".join(lines)


def write_rst_single_domain(module_name: str, src_filename: str,
                            clock: str, processes: list[str]) -> str:
    proc_list = ", ".join(f"``{p}``" for p in processes)
    lines = _title(f"{module_name} — Clock Domain Analysis")
    lines += [
        f"Auto-extracted from ``{src_filename}``.", "",
        ".. note::", "",
        f"   No clock domain crossings detected. "
        f"All clocked logic uses a single clock domain (``{clock}``).", "",
        "Clock Domain", "------------", "",
        ".. list-table::", "   :header-rows: 1", "",
        "   * - Clock", "     - Clocked Processes", "",
        f"   * - ``{clock}``", f"     - {proc_list}", "",
    ]
    return "\n".join(lines)


def write_rst_cdc(module_name: str, src_filename: str,
                  domains: dict[str, list[str]],
                  crossings: list[dict],
                  dual_clk_instances: list[dict]) -> str:
    dot_filename = f"{module_name}_cdc.dot"
    lines = _title(f"{module_name} — Clock Domain Analysis")
    lines += [
        f"Auto-extracted from ``{src_filename}``.", "",
        ".. graphviz:: " + dot_filename, "",
    ]

    # ── Clock domains table ──────────────────────────────────────────────────
    lines += [
        "Clock Domains", "-------------", "",
        ".. list-table::", "   :header-rows: 1", "",
        "   * - Clock", "     - Clocked Processes", "",
    ]
    for clk, procs in sorted(domains.items()):
        lines.append(f"   * - ``{clk}``")
        lines.append("     - " + ", ".join(f"``{p}``" for p in procs))
        lines.append("")

    # ── Dual-clock instances ─────────────────────────────────────────────────
    if dual_clk_instances:
        lines += [
            "",
            "Dual-Clock Instances", "--------------------", "",
            "The following instances connect clock-named ports to different signals,",
            "indicating an asynchronous FIFO, dual-port RAM, or similar CDC structure.", "",
            ".. list-table::", "   :header-rows: 1", "",
            "   * - Instance", "     - Component", "     - Clock Port Connections", "",
        ]
        for fi in dual_clk_instances:
            conn = ", ".join(f"``{p}`` → ``{s}``" for p, s in fi["clocks"].items())
            lines.append(f"   * - ``{fi['instance']}``")
            lines.append(f"     - ``{fi['component']}``")
            lines.append(f"     - {conn}")
            lines.append("")

    # ── Signal crossings ─────────────────────────────────────────────────────
    if crossings:
        unsynced = [c for c in crossings if not c["synchronized"]]
        if unsynced:
            sig_list = ", ".join(f"``{c['signal']}``" for c in unsynced)
            lines += [
                "",
                ".. warning::", "",
                f"   The following signal(s) cross clock domains without a detected "
                f"synchronizer: {sig_list}.", "",
            ]

        lines += [
            "",
            "Signal Crossings", "----------------", "",
            ".. list-table::", "   :header-rows: 1", "",
            "   * - Signal", "     - Source Domain",
            "     - Destination Domain", "     - Synchronized", "",
        ]
        for c in sorted(crossings, key=lambda x: (x["synchronized"], x["signal"])):
            sync_str = "Yes *(two-flop)*" if c["synchronized"] else "**No**"
            lines.append(f"   * - ``{c['signal']}``")
            lines.append(f"     - ``{c['src_clock']}``")
            lines.append(f"     - ``{c['dst_clock']}``")
            lines.append(f"     - {sync_str}")
            lines.append("")
    else:
        lines += [
            "",
            ".. note::", "",
            "   No direct signal crossings detected between clock domains.",
        ]
        if dual_clk_instances:
            lines += [
                "   Any inter-domain data transfer appears to use the structural",
                "   dual-clock instances listed above.",
            ]
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit("Usage: extract_cdc.py <file.vhd|file.sv> <module_name> <output_dir>")

    src_path    = Path(sys.argv[1])
    module_name = sys.argv[2]
    output_dir  = Path(sys.argv[3])
    output_dir.mkdir(parents=True, exist_ok=True)

    text = src_path.read_text()
    ext  = src_path.suffix.lower()

    if ext in (".vhd", ".vhdl"):
        is_vhdl         = True
        stripped        = strip_vhdl_comments(text)
        domains         = extract_domains_vhdl(text)
        dual_clk_insts  = detect_dual_clock_instances_vhdl(stripped)
    elif ext in (".sv", ".svh"):
        is_vhdl         = False
        stripped        = strip_sv_comments(text)
        domains         = extract_domains_sv(text)
        dual_clk_insts  = detect_dual_clock_instances_sv(stripped)
    else:
        sys.exit(f"ERROR: Unsupported file type '{ext}'")

    out_path = output_dir / f"{module_name}_cdc.rst"

    if not domains:
        out_path.write_text(write_rst_no_clocks(module_name, src_path.name))
        print(f"  (no clocked processes in {src_path.name})")
        print(f"  → {out_path}")
        sys.exit(0)

    if len(domains) == 1:
        clock, procs = next(iter(domains.items()))
        out_path.write_text(
            write_rst_single_domain(module_name, src_path.name, clock, procs)
        )
        print(f"  (single clock domain '{clock}' — no CDC) → {out_path}")
        sys.exit(0)

    # ── Multiple clock domains: find crossings ───────────────────────────────
    domain_lhs, domain_rhs = collect_domain_signals(stripped, domains, is_vhdl)

    # Filter clock names themselves out of the signal sets
    clock_names = set(domains.keys())

    crossings: list[dict] = []
    clock_list = list(domains.keys())
    for src_clk in clock_list:
        for dst_clk in clock_list:
            if src_clk == dst_clk:
                continue
            crossing_sigs = (
                domain_lhs[src_clk] & domain_rhs[dst_clk] - clock_names
            )
            for sig in sorted(crossing_sigs):
                crossings.append({
                    "signal":       sig,
                    "src_clock":    src_clk,
                    "dst_clock":    dst_clk,
                    "synchronized": False,
                })

    if crossings:
        crossing_names = {c["signal"] for c in crossings}
        synced = detect_synchronizers(stripped, crossing_names)
        for c in crossings:
            if c["signal"] in synced:
                c["synchronized"] = True

    dot_path = output_dir / f"{module_name}_cdc.dot"
    dot_path.write_text(
        write_dot_cdc(module_name, domains, crossings, dual_clk_insts)
    )
    print(f"  → {dot_path}")

    out_path.write_text(
        write_rst_cdc(module_name, src_path.name, domains, crossings, dual_clk_insts)
    )
    print(f"  → {out_path}")
