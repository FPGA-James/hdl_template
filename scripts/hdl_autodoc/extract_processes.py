#!/usr/bin/env python3
"""
extract_processes.py
--------------------
Parses VHDL or SystemVerilog source and writes one RST file per
labeled process/always block plus a processes/index.rst.

VHDL:  labeled process(sensitivity) blocks, -- comments, -- wavedrom::
SV:    labeled always_ff/always_comb blocks, // comments, // wavedrom::

Usage:
    python scripts/extract_processes.py <file.vhd|file.sv> <output_dir>
"""

import re
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Shared comment helpers
# ─────────────────────────────────────────────────────────────────────────────

def is_separator(text: str) -> bool:
    return bool(re.match(r"^[-=*#/\s]*$", text))

def is_rst_directive(text: str) -> bool:
    return bool(re.match(r"^\s*\.\.\s+\w+", text))


# ─────────────────────────────────────────────────────────────────────────────
# Comment token extraction (shared between VHDL and SV)
# ─────────────────────────────────────────────────────────────────────────────

def extract_comment_tokens(lines: list[str], end_idx: int,
                           prefix: str = "--") -> list[dict]:
    """
    Walk backwards from end_idx collecting comment lines with the given prefix.
    Returns structured tokens: {"type": "text"|"wavedrom", "lines": [...]}
    Supports both -- (VHDL) and // (SV) comment styles.
    """
    raw = []
    i   = end_idx - 1
    while i >= 0:
        stripped = lines[i].strip()
        if stripped.startswith(prefix):
            text = re.sub(rf"^{re.escape(prefix)}\s?", "", stripped)
            raw.insert(0, text)
        elif stripped == "":
            i -= 1
            continue
        else:
            break
        i -= 1

    # Parse raw lines into text/wavedrom tokens
    tokens    = []
    text_buf  = []
    wave_buf  = None

    def flush_text():
        cleaned = [l for l in text_buf if not is_separator(l)]
        while cleaned and cleaned[0].strip() == "":
            cleaned.pop(0)
        while cleaned and cleaned[-1].strip() == "":
            cleaned.pop()
        if cleaned:
            tokens.append({"type": "text", "lines": cleaned})
        text_buf.clear()

    for line in raw:
        if re.match(r"^\s*(?:\.\.|//|#)\s+wavedrom\s*::\s*$", line):
            flush_text()
            wave_buf = []
            continue
        if wave_buf is not None:
            if line.strip() == "":
                wave_buf.append("")
                continue
            if line != line.lstrip():
                wave_buf.append(line.strip())
                continue
            tokens.append({"type": "wavedrom", "lines": wave_buf})
            wave_buf = None
            text_buf.append(line)
            continue
        text_buf.append(line)

    if wave_buf is not None:
        tokens.append({"type": "wavedrom", "lines": wave_buf})
    else:
        flush_text()

    return tokens


# ─────────────────────────────────────────────────────────────────────────────
# VHDL process extraction
# ─────────────────────────────────────────────────────────────────────────────

VHDL_PROCESS_RE = re.compile(
    r"^\s*(\w+)\s*:\s*process\s*\((.*?)\)", re.IGNORECASE
)
VHDL_ASSIGN_RE  = re.compile(r"(\w+)\s*<=\s*([^;]+);")
VHDL_WHEN_RE    = re.compile(r"^\s*when\s+(\w+)\s*=>", re.IGNORECASE)


def find_processes_vhdl(lines: list[str]) -> list[dict]:
    processes = []
    i = 0
    while i < len(lines):
        m = VHDL_PROCESS_RE.match(lines[i])
        if m:
            label       = m.group(1).strip()
            sensitivity = [s.strip() for s in m.group(2).split(",")]
            tokens      = extract_comment_tokens(lines, i, prefix="--")
            body        = [lines[i]]   # include the process label line itself
            j           = i + 1
            while j < len(lines):
                body.append(lines[j])
                if re.search(r"\bend\s+process\b", lines[j], re.IGNORECASE):
                    break
                j += 1
            processes.append({
                "label": label, "sensitivity": sensitivity,
                "tokens": tokens, "body": body, "line": i + 1,
                "kind": "process",
            })
            i = j + 1
        else:
            i += 1
    return processes


def extract_assignments_vhdl(body: list[str]) -> dict:
    result, current = {}, None
    WHEN_RE = re.compile(r"^\s*when\s+(\w+)\s*=>", re.IGNORECASE)
    for line in body:
        wm = WHEN_RE.match(line)
        if wm:
            current = wm.group(1).upper()
            result.setdefault(current, [])
            continue
        if current:
            for m in VHDL_ASSIGN_RE.finditer(line):
                result[current].append((m.group(1).strip(), m.group(2).strip().strip("'\"")))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# SystemVerilog always block extraction
# ─────────────────────────────────────────────────────────────────────────────

SV_ALWAYS_RE = re.compile(
    r"^\s*(always_ff|always_comb|always_latch|always)\s*"
    r"(?:@\s*\([^)]*\)\s*)?"
    r"(?:begin\s*)?:\s*(\w+)",
    re.IGNORECASE
)
SV_ALWAYS_SENS_RE = re.compile(
    r"always_(?:ff|latch)\s*@\s*\(([^)]*)\)", re.IGNORECASE
)
SV_ASSIGN_RE = re.compile(r"(\w+)\s*(?:<=|=)\s*1'b([01])\s*;")
SV_WHEN_RE   = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*:", re.IGNORECASE)


def find_processes_sv(lines: list[str]) -> list[dict]:
    processes = []
    i = 0
    while i < len(lines):
        m = SV_ALWAYS_RE.match(lines[i])
        if m:
            block_type = m.group(1).lower()
            label      = m.group(2).strip()

            # Extract sensitivity list if present (handles "always_ff @(posedge clk)")
            sens_m = re.search(r"@\s*\(([^)]+)\)", lines[i], re.IGNORECASE)
            if sens_m:
                sensitivity = [s.strip() for s in
                               re.split(r",|\bor\b", sens_m.group(1), flags=re.IGNORECASE)]
            elif "comb" in block_type:
                sensitivity = ["*"]
            elif "ff" in block_type or "latch" in block_type:
                sensitivity = ["clk"]  # fallback
            else:
                sensitivity = []

            tokens = extract_comment_tokens(lines, i, prefix="//")

            # Collect body until matching 'end'
            body      = [lines[i]]   # include the always block header line itself
            depth     = 1 if "begin" in lines[i].lower() else 0
            j         = i + 1
            while j < len(lines):
                body.append(lines[j])
                depth += len(re.findall(r"\bbegin\b", lines[j], re.IGNORECASE))
                depth -= len(re.findall(r"\bend\b",   lines[j], re.IGNORECASE))
                if depth <= 0:
                    break
                j += 1

            processes.append({
                "label": label, "sensitivity": sensitivity,
                "tokens": tokens, "body": body, "line": i + 1,
                "kind": block_type,
            })
            i = j + 1
        else:
            i += 1
    return processes


def extract_assignments_sv(body: list[str]) -> dict:
    result, current = {}, None
    for line in body:
        wm = SV_WHEN_RE.match(line)
        if wm:
            current = wm.group(1).upper()
            result.setdefault(current, [])
            continue
        if current:
            for m in SV_ASSIGN_RE.finditer(line):
                result[current].append((m.group(1).strip(), m.group(2)))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# RST rendering (shared)
# ─────────────────────────────────────────────────────────────────────────────

def render_text_block(comment_lines: list[str]) -> list[str]:
    out, code_buf, first = [], [], True

    def flush_code():
        if not code_buf:
            return
        out.extend([".. code-block:: none", ""])
        for cl in code_buf:
            out.append("   " + cl)
        out.append("")
        code_buf.clear()

    for raw in comment_lines:
        if raw == "":
            flush_code(); out.append(""); continue
        if raw != raw.lstrip():
            code_buf.append(raw); continue
        flush_code()
        line = raw
        if first and re.match(r"^\w[\w\s]*:", line):
            line = re.sub(r":", r"\:", line, count=1)
        first = False
        out.append(line)
    flush_code()
    return out


def render_wavedrom_block(json_lines: list[str]) -> list[str]:
    out = [".. wavedrom::", ""]
    for line in json_lines:
        out.append("   " + line if line.strip() else "")
    out.append("")
    return out


def render_process_page(proc: dict, src_filename: str,
                        extract_fn) -> str:
    label = proc["label"]
    sens  = ", ".join(f"``{s}``" for s in proc["sensitivity"]) if proc["sensitivity"] else "``*``"
    kind  = proc["kind"]
    title = label
    under = "=" * len(title)

    out = [title, under, "",
           f"| **Source file:** ``{src_filename}``",
           f"| **Source line:** {proc['line']}",
           f"| **Block type:** ``{kind}``",
           f"| **Sensitivity list:** {sens}",
           ""]

    has_content = any(t["type"] in ("text", "wavedrom") for t in proc["tokens"])
    if has_content:
        out += ["Description", "-----------", ""]
        for token in proc["tokens"]:
            if token["type"] == "text":
                out.extend(render_text_block(token["lines"]))
                out.append("")
            elif token["type"] == "wavedrom":
                out.extend(render_wavedrom_block(token["lines"]))

    assignments = extract_fn(proc["body"])
    if assignments:
        all_sigs = []
        for assigns in assignments.values():
            for sig, _ in assigns:
                if sig not in all_sigs:
                    all_sigs.append(sig)
        if all_sigs:
            out += ["Signal Assignments", "------------------", "",
                    ".. list-table::", "   :header-rows: 1", "",
                    "   * - State"]
            for sig in all_sigs:
                out.append(f"     - ``{sig}``")
            out.append("")
            for state, assigns in assignments.items():
                assign_map = dict(assigns)
                out.append(f"   * - ``{state}``")
                for sig in all_sigs:
                    out.append(f"     - {assign_map.get(sig, '—')}")
                out.append("")
            out.append("")

    # Language tag for source block
    lang = "vhdl" if proc["kind"] == "process" else "systemverilog"
    out += ["Source", "------", "",
            f".. code-block:: {lang}", ""]
    for line in proc["body"]:
        out.append("   " + line.rstrip())
    out.append("")

    return "\n".join(out)


def render_index_page(processes: list[dict], src_filename: str) -> str:
    out = ["Processes", "=========", "",
           f"Auto-extracted from ``{src_filename}``.", "",
           ".. toctree::", "   :maxdepth: 2", ""]
    for proc in processes:
        out.append(f"   {proc['label']}")
    out += ["", "Summary", "-------", "",
            ".. list-table::", "   :header-rows: 1", "",
            "   * - Block", "     - Type", "     - Sensitivity",
            "     - Source Line", "     - WaveDrom", ""]
    for proc in processes:
        label    = proc["label"]
        sens     = ", ".join(f"``{s}``" for s in proc["sensitivity"]) or "``*``"
        ptype    = proc["kind"]
        has_wave = "✔" if any(t["type"] == "wavedrom" for t in proc["tokens"]) else "—"
        out.append(f"   * - :doc:`{label}`")
        out.append(f"     - ``{ptype}``")
        out.append(f"     - {sens}")
        out.append(f"     - {proc['line']}")
        out.append(f"     - {has_wave}")
        out.append("")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Usage: extract_processes.py <file.vhd|file.sv> <output_dir>")

    src_path   = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    lines = src_path.read_text().splitlines()
    ext   = src_path.suffix.lower()

    if ext in (".vhd", ".vhdl"):
        processes   = find_processes_vhdl(lines)
        extract_fn  = extract_assignments_vhdl
    elif ext in (".sv", ".svh"):
        processes   = find_processes_sv(lines)
        extract_fn  = extract_assignments_sv
    else:
        sys.exit(f"ERROR: Unsupported file type '{ext}'")

    if not processes:
        print(f"  (no labeled processes found in {src_path.name} — skipping)")
        sys.exit(0)

    for proc in processes:
        page    = render_process_page(proc, src_path.name, extract_fn)
        outfile = output_dir / f"{proc['label']}.rst"
        outfile.write_text(page)
        print(f"  → {outfile}")

    index_page = render_index_page(processes, src_path.name)
    (output_dir / "index.rst").write_text(index_page)
    print(f"  → {output_dir / 'index.rst'}")