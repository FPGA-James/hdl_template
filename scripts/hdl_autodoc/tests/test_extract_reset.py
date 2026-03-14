"""
test_extract_reset.py
---------------------
Tests for extract_reset.py.

Covers:
  - VHDL synchronous reset detection (reset inside rising_edge block).
  - VHDL asynchronous reset detection (reset before rising_edge, in sensitivity).
  - VHDL process with no reset.
  - SV synchronous reset detection (only clock in @(...) sensitivity).
  - SV asynchronous reset detection (reset in @(...) sensitivity).
  - Grouping processes by reset domain.
  - Signal crossing detection between reset domains.
  - Graphviz dot output structure (clusters, crossing edges).
  - RST output: single domain note, multi-domain warning and table.
"""

import pytest

from extract_reset import (
    extract_process_info_sv,
    extract_process_info_vhdl,
    find_reset_crossings,
    group_by_reset,
    strip_sv_comments,
    strip_vhdl_comments,
    write_dot_reset,
    write_rst_multi_domain,
    write_rst_single_domain,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

VHDL_SYNC_RESET = """\
p_reg : process(clk) is
begin
    if rising_edge(clk) then
        if rst = '1' then
            q <= '0';
        else
            q <= d;
        end if;
    end if;
end process p_reg;
"""

VHDL_ASYNC_RESET = """\
p_reg : process(clk, rst) is
begin
    if rst = '1' then
        q <= '0';
    elsif rising_edge(clk) then
        q <= d;
    end if;
end process p_reg;
"""

VHDL_NO_RESET = """\
p_reg : process(clk) is
begin
    if rising_edge(clk) then
        q <= d;
    end if;
end process p_reg;
"""

VHDL_TWO_DOMAINS = """\
p_a : process(clk_a) is
begin
    if rising_edge(clk_a) then
        if rst_a = '1' then
            sig_r <= '0';
        else
            sig_r <= sig_in;
        end if;
    end if;
end process p_a;

p_b : process(clk_b) is
begin
    if rising_edge(clk_b) then
        if rst_b = '1' then
            out_r <= '0';
        else
            out_r <= sig_r;
        end if;
    end if;
end process p_b;
"""

SV_SYNC_RESET = """\
always_ff @(posedge clk) begin : p_reg
    if (rst) begin
        q <= 1'b0;
    end else begin
        q <= d;
    end
end
"""

SV_ASYNC_RESET = """\
always_ff @(posedge clk or posedge rst) begin : p_reg
    if (rst) begin
        q <= 1'b0;
    end else begin
        q <= d;
    end
end
"""

SV_NO_RESET = """\
always_ff @(posedge clk) begin : p_reg
    q <= d;
end
"""


# ─────────────────────────────────────────────────────────────────────────────
# VHDL process info extraction
# ─────────────────────────────────────────────────────────────────────────────

def test_vhdl_sync_reset_detected():
    """A reset inside rising_edge is classified as synchronous."""
    procs = extract_process_info_vhdl(VHDL_SYNC_RESET)
    assert len(procs) == 1
    assert procs[0]["reset"] == "rst"
    assert procs[0]["style"] == "sync"


def test_vhdl_async_reset_detected():
    """A reset before rising_edge with the signal in the sensitivity list is async."""
    procs = extract_process_info_vhdl(VHDL_ASYNC_RESET)
    assert len(procs) == 1
    assert procs[0]["reset"] == "rst"
    assert procs[0]["style"] == "async"


def test_vhdl_no_reset_detected():
    """A clocked process with no reset condition returns style='none'."""
    procs = extract_process_info_vhdl(VHDL_NO_RESET)
    assert len(procs) == 1
    assert procs[0]["reset"] is None
    assert procs[0]["style"] == "none"


def test_vhdl_clock_extracted():
    """The clock signal name is extracted from rising_edge(X)."""
    procs = extract_process_info_vhdl(VHDL_SYNC_RESET)
    assert procs[0]["clock"] == "clk"


def test_vhdl_label_extracted():
    """The process label is extracted correctly."""
    procs = extract_process_info_vhdl(VHDL_SYNC_RESET)
    assert procs[0]["label"] == "p_reg"


def test_vhdl_two_domain_processes():
    """Two processes with different resets are both extracted."""
    procs = extract_process_info_vhdl(VHDL_TWO_DOMAINS)
    labels = {p["label"] for p in procs}
    resets = {p["reset"] for p in procs}
    assert "p_a" in labels
    assert "p_b" in labels
    assert "rst_a" in resets
    assert "rst_b" in resets


# ─────────────────────────────────────────────────────────────────────────────
# SV process info extraction
# ─────────────────────────────────────────────────────────────────────────────

def test_sv_sync_reset_detected():
    """Only clock in @(...) with if(rst) inside is classified as synchronous."""
    procs = extract_process_info_sv(SV_SYNC_RESET)
    assert len(procs) == 1
    assert procs[0]["reset"] == "rst"
    assert procs[0]["style"] == "sync"


def test_sv_async_reset_detected():
    """posedge rst in @(...) sensitivity is classified as asynchronous."""
    procs = extract_process_info_sv(SV_ASYNC_RESET)
    assert len(procs) == 1
    assert procs[0]["reset"] == "rst"
    assert procs[0]["style"] == "async"


def test_sv_no_reset_detected():
    """An always_ff with no reset check returns style='none'."""
    procs = extract_process_info_sv(SV_NO_RESET)
    assert len(procs) == 1
    assert procs[0]["reset"] is None
    assert procs[0]["style"] == "none"


def test_sv_clock_extracted():
    """The first posedge signal in @(...) is extracted as the clock."""
    procs = extract_process_info_sv(SV_SYNC_RESET)
    assert procs[0]["clock"] == "clk"


def test_sv_label_extracted():
    """The begin : label name is extracted correctly."""
    procs = extract_process_info_sv(SV_SYNC_RESET)
    assert procs[0]["label"] == "p_reg"


# ─────────────────────────────────────────────────────────────────────────────
# Reset domain grouping
# ─────────────────────────────────────────────────────────────────────────────

def test_group_by_reset_single_domain():
    """Processes with the same reset are in one group."""
    procs   = extract_process_info_vhdl(VHDL_SYNC_RESET)
    domains = group_by_reset(procs)
    assert "rst" in domains
    assert len(domains) == 1


def test_group_by_reset_two_domains():
    """Processes with different resets produce separate groups."""
    procs   = extract_process_info_vhdl(VHDL_TWO_DOMAINS)
    domains = group_by_reset(procs)
    assert "rst_a" in domains
    assert "rst_b" in domains


def test_group_by_reset_no_reset_key():
    """Processes without a reset are grouped under '__none__'."""
    procs   = extract_process_info_vhdl(VHDL_NO_RESET)
    domains = group_by_reset(procs)
    assert "__none__" in domains


# ─────────────────────────────────────────────────────────────────────────────
# Signal crossing detection
# ─────────────────────────────────────────────────────────────────────────────

def test_crossing_detected_between_domains():
    """sig_r driven under rst_a and read under rst_b is reported as a crossing."""
    procs    = extract_process_info_vhdl(VHDL_TWO_DOMAINS)
    domains  = group_by_reset(procs)
    stripped = strip_vhdl_comments(VHDL_TWO_DOMAINS)
    crossings = find_reset_crossings(stripped, domains, is_vhdl=True)
    signals  = {c["signal"] for c in crossings}
    assert "sig_r" in signals


def test_crossing_src_dst_correct():
    """The source and destination reset domains are correctly identified."""
    procs    = extract_process_info_vhdl(VHDL_TWO_DOMAINS)
    domains  = group_by_reset(procs)
    stripped = strip_vhdl_comments(VHDL_TWO_DOMAINS)
    crossings = find_reset_crossings(stripped, domains, is_vhdl=True)
    sig_r_crossing = next(c for c in crossings if c["signal"] == "sig_r")
    assert sig_r_crossing["src_reset"] == "rst_a"
    assert sig_r_crossing["dst_reset"] == "rst_b"


def test_no_crossing_in_single_domain():
    """No crossings are reported when all processes share the same reset."""
    procs    = extract_process_info_vhdl(VHDL_SYNC_RESET)
    domains  = group_by_reset(procs)
    stripped = strip_vhdl_comments(VHDL_SYNC_RESET)
    crossings = find_reset_crossings(stripped, domains, is_vhdl=True)
    assert crossings == []


# ─────────────────────────────────────────────────────────────────────────────
# Graphviz dot output
# ─────────────────────────────────────────────────────────────────────────────

def test_dot_reset_clusters_present():
    """Each reset domain appears as a named subgraph cluster."""
    procs   = extract_process_info_vhdl(VHDL_TWO_DOMAINS)
    domains = group_by_reset(procs)
    dot     = write_dot_reset("my_mod", domains, [])
    assert "cluster_rst_a" in dot
    assert "cluster_rst_b" in dot


def test_dot_reset_crossing_edge_present():
    """A crossing between domains produces a dashed red edge."""
    procs    = extract_process_info_vhdl(VHDL_TWO_DOMAINS)
    domains  = group_by_reset(procs)
    stripped = strip_vhdl_comments(VHDL_TWO_DOMAINS)
    crossings = find_reset_crossings(stripped, domains, is_vhdl=True)
    dot = write_dot_reset("my_mod", domains, crossings)
    assert 'style="dashed"' in dot
    assert "sig_r" in dot


def test_dot_no_reset_cluster_uses_warning_color():
    """The no-reset cluster uses the red warning color."""
    procs   = extract_process_info_vhdl(VHDL_NO_RESET)
    domains = group_by_reset(procs)
    dot     = write_dot_reset("my_mod", domains, [])
    assert "fee2e2" in dot   # red warning fill


# ─────────────────────────────────────────────────────────────────────────────
# RST output
# ─────────────────────────────────────────────────────────────────────────────

def test_rst_single_domain_note():
    """Single reset domain produces a 'no crossings' note."""
    procs   = extract_process_info_vhdl(VHDL_SYNC_RESET)
    domains = group_by_reset(procs)
    rst     = write_rst_single_domain("my_mod", "my_mod.vhd", "rst",
                                       domains["rst"])
    assert "single reset domain" in rst
    assert "No reset domain crossings" in rst


def test_rst_single_domain_table_populated():
    """The process table shows the correct reset signal and style."""
    procs   = extract_process_info_vhdl(VHDL_SYNC_RESET)
    domains = group_by_reset(procs)
    rst     = write_rst_single_domain("my_mod", "my_mod.vhd", "rst",
                                       domains["rst"])
    assert "``rst``" in rst
    assert "Sync" in rst


def test_rst_multi_domain_warning():
    """Multiple reset domains with crossings produce a warning admonition."""
    procs    = extract_process_info_vhdl(VHDL_TWO_DOMAINS)
    domains  = group_by_reset(procs)
    stripped = strip_vhdl_comments(VHDL_TWO_DOMAINS)
    crossings = find_reset_crossings(stripped, domains, is_vhdl=True)
    rst = write_rst_multi_domain("my_mod", "my_mod.vhd",
                                  "my_mod_reset.dot", domains, crossings)
    assert ".. warning::" in rst
    assert "sig_r" in rst


def test_rst_multi_domain_graphviz_directive():
    """Multi-domain RST includes a graphviz directive."""
    procs   = extract_process_info_vhdl(VHDL_TWO_DOMAINS)
    domains = group_by_reset(procs)
    rst     = write_rst_multi_domain("my_mod", "my_mod.vhd",
                                      "my_mod_reset.dot", domains, [])
    assert ".. graphviz::" in rst
    assert "my_mod_reset.dot" in rst


def test_rst_no_reset_warning():
    """'__none__' domain in multi-domain RST produces a no-reset warning."""
    # Combine a process with reset and one without
    vhdl = VHDL_SYNC_RESET + "\n" + VHDL_NO_RESET.replace("p_reg", "p_norst")
    procs   = extract_process_info_vhdl(vhdl)
    domains = group_by_reset(procs)
    rst     = write_rst_multi_domain("my_mod", "my_mod.vhd",
                                      "my_mod_reset.dot", domains, [])
    assert "no reset" in rst.lower()
    assert "p_norst" in rst
