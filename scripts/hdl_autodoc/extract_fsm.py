#!/usr/bin/env python3
"""
extract_fsm.py
--------------
Parses VHDL or SystemVerilog source, extracts the FSM next-state block,
and writes <module>.dot and <module>.rst into the output directory.

Usage:
    python scripts/extract_fsm.py <file.vhd|file.sv> <module_name> <output_dir>
"""

import re
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# State colour palette
# ─────────────────────────────────────────────────────────────────────────────

STATE_COLOURS = {
    "red":       "salmon",
    "red_amber": "lightyellow",
    "green":     "lightgreen",
    "amber":     "orange",
    "idle":      "lightblue",
    "counting":  "lightyellow",
    "done":      "lightgreen",
    "on_state":  "lightgreen",
    "fade_state":"lightyellow",
    "off_state": "lightgray",
}
DEFAULT_COLOUR = "white"


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def strip_vhdl_comments(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)

def strip_sv_comments(text: str) -> str:
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text

def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


# ─────────────────────────────────────────────────────────────────────────────
# VHDL extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_transitions_vhdl(vhd_text: str) -> list[tuple[str,str,str]]:
    text = normalise(strip_vhdl_comments(vhd_text))
    case_match = re.search(
        r"case\s+\w+\s+is\s+(.*?)\s+end\s+case", text, re.DOTALL
    )
    if not case_match:
        return []  # No FSM in this file

    transitions = []
    for clause in re.split(r"\bwhen\b", case_match.group(1)):
        clause = clause.strip()
        if not clause or clause.startswith("others"):
            continue
        state_m = re.match(r"(\w+)\s*=>", clause)
        if not state_m:
            continue
        from_state = state_m.group(1).upper()
        for m in re.finditer(
            r"if\s+([\w\s=/']+?)\s+then\s+next_state\s*<=\s*(\w+)", clause
        ):
            transitions.append((from_state, m.group(2).upper(), m.group(1).strip()))
        body = re.sub(r"if\b.*?end\s+if", "", clause, flags=re.DOTALL)
        for m in re.finditer(r"next_state\s*<=\s*(\w+)", body):
            to = m.group(1).upper()
            if to != from_state:
                transitions.append((from_state, to, ""))
    return transitions


def extract_outputs_vhdl(vhd_text: str) -> dict:
    ASSIGN_RE = re.compile(r"(\w+)\s*<=\s*'([01])'")
    WHEN_RE   = re.compile(r"^\s*when\s+(\w+)\s*=>", re.IGNORECASE)
    processes = re.findall(
        r":\s*process\b.*?end\s+process", vhd_text, re.IGNORECASE | re.DOTALL
    )
    for proc in processes:
        if "next_state" in proc.lower():
            continue
        defaults = {}
        case_start = re.search(r"\bcase\b", proc, re.IGNORECASE)
        if case_start:
            for m in ASSIGN_RE.finditer(proc[:case_start.start()]):
                defaults[m.group(1)] = m.group(2)
        if not defaults:
            continue
        state_outputs = {}
        current = None
        for line in proc.splitlines():
            wm = WHEN_RE.match(line)
            if wm:
                current = wm.group(1).upper()
                state_outputs[current] = dict(defaults)
                for m in ASSIGN_RE.finditer(line[wm.end():]):
                    state_outputs[current][m.group(1)] = m.group(2)
                continue
            if current:
                for m in ASSIGN_RE.finditer(line):
                    state_outputs[current][m.group(1)] = m.group(2)
        if state_outputs:
            return state_outputs
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# SystemVerilog extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_transitions_sv(sv_text: str) -> list[tuple[str,str,str]]:
    # Work on comment-stripped text only — do NOT normalise (normalise lowercases
    # state names which breaks the label splitter)
    text = strip_sv_comments(sv_text)

    # Find the always block that contains next_state assignment
    # Pattern: always_comb/always_ff ... begin [: label] ... endcase ... end
    block_re = re.compile(
        r"always_(?:comb|ff)\b[^;]*?begin\b(?:\s*:\s*\w+)?\s*(.*?)\bend\b",
        re.DOTALL | re.IGNORECASE
    )
    case_body = None
    for bm in block_re.finditer(text):
        block = bm.group(1)
        if "next_state" not in block.lower():
            continue
        cm = re.search(r"\bcase\s*\([^)]+\)(.*?)\bendcase\b", block,
                       re.DOTALL | re.IGNORECASE)
        if cm:
            case_body = cm.group(1)
            break

    if case_body is None:
        # Fallback: find any case block containing next_state
        for cm in re.finditer(r"\bcase\s*\([^)]+\)(.*?)\bendcase\b",
                              text, re.DOTALL | re.IGNORECASE):
            if "next_state" in cm.group(1).lower():
                case_body = cm.group(1)
                break

    if case_body is None:
        return []  # No FSM in this file

    transitions = []
    # Split on state labels: "WORD:" where WORD is not a keyword
    SV_KEYWORDS = {"begin","end","if","else","case","endcase","default",
                   "assign","always","module","endmodule","logic","input","output"}
    clauses = re.split(r"\b(\w+)\s*:", case_body)

    i = 1
    while i < len(clauses) - 1:
        label = clauses[i].strip()
        body  = clauses[i+1] if i+1 < len(clauses) else ""
        i += 2

        if label.lower() in SV_KEYWORDS:
            continue
        from_state = label.upper()

        # if (cond) next_state = TARGET
        for m in re.finditer(
            r"if\s*\(([^)]+)\)\s*(?:begin\s*)?next_state\s*(?:<=|=)\s*(\w+)",
            body, re.IGNORECASE
        ):
            transitions.append((from_state, m.group(2).upper(), m.group(1).strip()))

        # unconditional: strip if blocks then find bare next_state assignments
        body_no_if = re.sub(r"\bif\s*\([^)]*\)\s*(?:begin.*?end|[^;]+;)",
                            "", body, flags=re.DOTALL | re.IGNORECASE)
        for m in re.finditer(r"next_state\s*(?:<=|=)\s*(\w+)", body_no_if, re.IGNORECASE):
            to = m.group(1).upper()
            if to != from_state:
                transitions.append((from_state, to, ""))

    return transitions


def extract_outputs_sv(sv_text: str) -> dict:
    """Extract Moore outputs from always_comb output decode block."""
    ASSIGN_RE = re.compile(r"(\w+)\s*=\s*1'b([01])")
    CASE_RE   = re.compile(r"case\s*\(\s*\w+\s*\)(.*?)endcase", re.DOTALL | re.IGNORECASE)
    WHEN_RE   = re.compile(r"([A-Z_][A-Z0-9_]*)\s*:", re.IGNORECASE)

    blocks = re.findall(
        r"always_comb\b.*?(?=always_|endmodule)", sv_text, re.DOTALL | re.IGNORECASE
    )
    for block in blocks:
        if "next_state" in block.lower():
            continue
        case_m = CASE_RE.search(block)
        if not case_m:
            continue

        # Collect defaults before case
        defaults = {}
        pre = block[:case_m.start()]
        for m in ASSIGN_RE.finditer(pre):
            defaults[m.group(1)] = m.group(2)
        if not defaults:
            continue

        state_outputs = {}
        current = None
        for line in case_m.group(1).splitlines():
            wm = WHEN_RE.match(line.strip())
            if wm:
                current = wm.group(1).upper()
                state_outputs[current] = dict(defaults)
                for m in ASSIGN_RE.finditer(line[wm.end():]):
                    state_outputs[current][m.group(1)] = m.group(2)
                continue
            if current:
                for m in ASSIGN_RE.finditer(line):
                    state_outputs[current][m.group(1)] = m.group(2)

        if state_outputs:
            return state_outputs
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Shared dot + RST writers
# ─────────────────────────────────────────────────────────────────────────────

def collect_states(transitions):
    states = []
    for frm, to, _ in transitions:
        for s in (frm, to):
            if s not in states:
                states.append(s)
    return states


def write_dot(transitions, states, module_name):
    lines = [
        f"digraph {module_name} {{",
        "    rankdir=LR;",
        "    node [shape=circle, style=filled, fontname=Helvetica, fontsize=12];",
        "    edge [fontname=Helvetica, fontsize=10];",
        "",
        "    __start [shape=point, width=0.2, fillcolor=black];",
        "",
    ]
    for s in states:
        colour = STATE_COLOURS.get(s.lower(), DEFAULT_COLOUR)
        lines.append(f"    {s} [fillcolor={colour}];")
    lines.append("")
    if states:
        lines.append(f"    __start -> {states[0]} [label=\"reset\"];")
    lines.append("")
    for frm, to, cond in transitions:
        label = cond if cond else "always"
        lines.append(f"    {frm} -> {to} [label=\"{label}\"];")
    lines.append("}")
    return "\n".join(lines)


def write_rst(dot_filename, states, outputs, transitions, module_name, src_filename):
    title = f"{module_name} State Machine"
    out = [title, "=" * len(title), "",
           f"Auto-extracted from ``{src_filename}``.", "",
           "State Transition Diagram", "------------------------", "",
           f".. graphviz:: {dot_filename}", ""]

    if outputs:
        all_sigs = []
        for sig_map in outputs.values():
            for sig in sig_map:
                if sig not in all_sigs:
                    all_sigs.append(sig)
        out += ["State Output Table", "------------------", "",
                ".. list-table::", "   :header-rows: 1", "",
                "   * - State"]
        for sig in all_sigs:
            out.append(f"     - ``{sig}``")
        out.append("")
        for state in states:
            sig_map = outputs.get(state, {})
            out.append(f"   * - ``{state}``")
            for sig in all_sigs:
                out.append(f"     - {sig_map.get(sig, '—')}")
            out.append("")
        out.append("")

    out += ["Transitions", "-----------", "",
            ".. list-table::", "   :header-rows: 1", "",
            "   * - From", "     - To", "     - Condition", ""]
    for frm, to, cond in transitions:
        out.append(f"   * - ``{frm}``")
        out.append(f"     - ``{to}``")
        out.append(f"     - ``{cond}``" if cond else "     - (always)")
        out.append("")

    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit("Usage: extract_fsm.py <file.vhd|file.sv> <module_name> <output_dir>")

    src_path    = Path(sys.argv[1])
    module_name = sys.argv[2]
    output_dir  = Path(sys.argv[3])
    output_dir.mkdir(parents=True, exist_ok=True)

    src_text = src_path.read_text()
    ext      = src_path.suffix.lower()

    if ext in (".vhd", ".vhdl"):
        transitions = extract_transitions_vhdl(src_text)
        outputs     = extract_outputs_vhdl(src_text)
    elif ext in (".sv", ".svh"):
        transitions = extract_transitions_sv(src_text)
        outputs     = extract_outputs_sv(src_text)
    else:
        sys.exit(f"ERROR: Unsupported file type '{ext}'. Use .vhd or .sv")

    if not transitions:
        print(f"  (no FSM found in {src_path.name} — skipping)")
        sys.exit(0)

    states       = collect_states(transitions)
    dot_filename = f"{module_name}.dot"

    (output_dir / dot_filename).write_text(
        write_dot(transitions, states, module_name)
    )
    print(f"  → {output_dir / dot_filename}")

    (output_dir / f"{module_name}.rst").write_text(
        write_rst(dot_filename, states, outputs, transitions, module_name, src_path.name)
    )
    print(f"  → {output_dir / f'{module_name}.rst'}")
