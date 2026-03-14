"""
test_extract_processes.py
-------------------------
Tests for extract_processes.py.

Covers:
  - Labeled VHDL process blocks are found with the correct label, sensitivity
    list, and source line number.
  - Labeled SystemVerilog always_ff / always_comb blocks are found.
  - Comment tokens (plain text and wavedrom blocks) are extracted correctly.
  - RST page rendering includes the expected metadata fields.
  - The processes index RST lists all found processes.
"""

import pytest

from extract_processes import (
    extract_comment_tokens,
    find_processes_sv,
    find_processes_vhdl,
    render_index_page,
    render_process_page,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — minimal HDL snippets (as line lists)
# ─────────────────────────────────────────────────────────────────────────────

VHDL_SOURCE = """\
-- p_clk_reg: Clocked register process.
--
-- Captures next_state on rising edge of clk.
p_clk_reg : process(clk) is
begin
    if rising_edge(clk) then
        state <= next_state;
    end if;
end process p_clk_reg;

-- p_comb: Combinational next-state logic.
p_comb : process(state, en) is
begin
    next_state <= state;
end process p_comb;
""".splitlines()

SV_SOURCE = """\
// p_state_reg: Clocked state register.
always_ff @(posedge clk) begin : p_state_reg
    if (rst) state <= IDLE;
    else     state <= next_state;
end

// p_next: Combinational next-state.
always_comb begin : p_next
    next_state = state;
end
""".splitlines()

VHDL_WITH_WAVEDROM = """\
-- p_wave: Process with a wavedrom diagram.
--
-- .. wavedrom::
--
--    { "signal": [{ "name": "clk", "wave": "P...." }]}
p_wave : process(clk) is
begin
    if rising_edge(clk) then out <= inp; end if;
end process p_wave;
""".splitlines()


# ─────────────────────────────────────────────────────────────────────────────
# VHDL process discovery
# ─────────────────────────────────────────────────────────────────────────────

def test_vhdl_finds_all_processes():
    """All labeled processes in the source are discovered."""
    procs = find_processes_vhdl(VHDL_SOURCE)
    labels = [p["label"] for p in procs]
    assert "p_clk_reg" in labels
    assert "p_comb" in labels


def test_vhdl_process_sensitivity_list():
    """The sensitivity list tokens are parsed correctly."""
    procs = find_processes_vhdl(VHDL_SOURCE)
    p = next(p for p in procs if p["label"] == "p_clk_reg")
    assert "clk" in p["sensitivity"]


def test_vhdl_process_sensitivity_multiple():
    """A multi-signal sensitivity list is split into individual items."""
    procs = find_processes_vhdl(VHDL_SOURCE)
    p = next(p for p in procs if p["label"] == "p_comb")
    assert "state" in p["sensitivity"]
    assert "en" in p["sensitivity"]


def test_vhdl_process_line_number():
    """The reported line number points to the process declaration line (1-based)."""
    procs = find_processes_vhdl(VHDL_SOURCE)
    p = next(p for p in procs if p["label"] == "p_clk_reg")
    # Line 4 in VHDL_SOURCE (1-based)
    assert p["line"] == 4


def test_vhdl_process_kind():
    """VHDL processes are tagged with kind='process'."""
    procs = find_processes_vhdl(VHDL_SOURCE)
    assert all(p["kind"] == "process" for p in procs)


# ─────────────────────────────────────────────────────────────────────────────
# SystemVerilog process discovery
# ─────────────────────────────────────────────────────────────────────────────

def test_sv_finds_all_always_blocks():
    """All labeled always_ff / always_comb blocks are discovered."""
    procs = find_processes_sv(SV_SOURCE)
    labels = [p["label"] for p in procs]
    assert "p_state_reg" in labels
    assert "p_next" in labels


def test_sv_always_ff_kind():
    """always_ff blocks are tagged with kind='always_ff'."""
    procs = find_processes_sv(SV_SOURCE)
    p = next(p for p in procs if p["label"] == "p_state_reg")
    assert p["kind"] == "always_ff"


def test_sv_always_comb_kind():
    """always_comb blocks are tagged with kind='always_comb'."""
    procs = find_processes_sv(SV_SOURCE)
    p = next(p for p in procs if p["label"] == "p_next")
    assert p["kind"] == "always_comb"


def test_sv_always_ff_sensitivity():
    """The sensitivity list entry includes the edge qualifier, e.g. 'posedge clk'."""
    procs = find_processes_sv(SV_SOURCE)
    p = next(p for p in procs if p["label"] == "p_state_reg")
    # The raw token from @(posedge clk) is kept as-is including the edge keyword
    assert any("clk" in s for s in p["sensitivity"])


# ─────────────────────────────────────────────────────────────────────────────
# Comment token extraction
# ─────────────────────────────────────────────────────────────────────────────

def test_comment_tokens_text_extracted():
    """Plain comment text above a process is returned as a 'text' token."""
    procs = find_processes_vhdl(VHDL_SOURCE)
    p = next(p for p in procs if p["label"] == "p_clk_reg")
    text_tokens = [t for t in p["tokens"] if t["type"] == "text"]
    assert len(text_tokens) > 0
    combined = " ".join(" ".join(t["lines"]) for t in text_tokens)
    assert "Clocked register process" in combined


def test_comment_tokens_wavedrom_extracted():
    """A '.. wavedrom::' block in comments is returned as a 'wavedrom' token."""
    procs = find_processes_vhdl(VHDL_WITH_WAVEDROM)
    p = procs[0]
    wave_tokens = [t for t in p["tokens"] if t["type"] == "wavedrom"]
    assert len(wave_tokens) == 1
    assert any("signal" in line for line in wave_tokens[0]["lines"])


# ─────────────────────────────────────────────────────────────────────────────
# RST rendering
# ─────────────────────────────────────────────────────────────────────────────

def test_render_process_page_contains_metadata():
    """The rendered RST page contains source file name, line number, and block type."""
    procs = find_processes_vhdl(VHDL_SOURCE)
    p = next(p for p in procs if p["label"] == "p_clk_reg")
    rst = render_process_page(p, "test.vhd", lambda body: {})
    assert "test.vhd" in rst
    assert str(p["line"]) in rst
    assert "process" in rst


def test_render_process_page_contains_source_block():
    """The rendered RST page includes a code-block with the process source."""
    procs = find_processes_vhdl(VHDL_SOURCE)
    p = next(p for p in procs if p["label"] == "p_clk_reg")
    rst = render_process_page(p, "test.vhd", lambda body: {})
    assert ".. code-block::" in rst
    assert "p_clk_reg" in rst


def test_render_index_page_lists_all_processes():
    """The index RST page includes an entry for every discovered process."""
    procs = find_processes_vhdl(VHDL_SOURCE)
    rst = render_index_page(procs, "test.vhd")
    assert "p_clk_reg" in rst
    assert "p_comb" in rst
