"""
test_extract_cdc.py
-------------------
Tests for extract_cdc.py.

Covers:
  - Clock domain identification for VHDL and SystemVerilog.
  - Single clock domain produces no crossings.
  - Multi-domain analysis detects crossing signals.
  - Two-flop synchronizer chains are recognised and marked synchronized=True.
  - Unsynchronized crossings are marked synchronized=False.
  - Dual-clock instance detection for VHDL port maps and SV named ports.
  - Graphviz dot output contains the expected clusters and edge styling.
"""

import pytest

from extract_cdc import (
    detect_dual_clock_instances_sv,
    detect_dual_clock_instances_vhdl,
    detect_synchronizers,
    extract_domains_sv,
    extract_domains_vhdl,
    strip_sv_comments,
    strip_vhdl_comments,
    write_dot_cdc,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

VHDL_SINGLE_CLOCK = """\
p_reg : process(clk) is
begin
    if rising_edge(clk) then
        q <= d;
    end if;
end process p_reg;
"""

VHDL_DUAL_CLOCK = """\
p_cfg : process(cfg_clk) is
begin
    if rising_edge(cfg_clk) then
        data_r <= data_in;
    end if;
end process p_cfg;

p_sys : process(sys_clk) is
begin
    if rising_edge(sys_clk) then
        data_out <= data_r;
    end if;
end process p_sys;
"""

VHDL_TWO_FLOP = """\
p_src : process(clk_a) is
begin
    if rising_edge(clk_a) then
        sig_r <= sig_in;
    end if;
end process p_src;

p_sync : process(clk_b) is
begin
    if rising_edge(clk_b) then
        sig_meta <= sig_r;
        sig_sync <= sig_meta;
    end if;
end process p_sync;
"""

SV_DUAL_CLOCK = """\
always_ff @(posedge clk_a) begin : p_src
    data_r <= data_in;
end

always_ff @(posedge clk_b) begin : p_dst
    data_out <= data_r;
end
"""

VHDL_FIFO_INST = """\
u_fifo : entity work.async_fifo
    port map (
        wr_clk => clk_a,
        rd_clk => clk_b,
        wr_data => data_in,
        rd_data => data_out
    );
"""

SV_FIFO_INST = """\
async_fifo u_fifo (
    .wr_clk (clk_a),
    .rd_clk (clk_b),
    .wr_data(data_in)
);
"""


# ─────────────────────────────────────────────────────────────────────────────
# Clock domain identification — VHDL
# ─────────────────────────────────────────────────────────────────────────────

def test_vhdl_single_clock_domain_identified():
    """A VHDL file with one rising_edge clock produces one domain entry."""
    domains = extract_domains_vhdl(VHDL_SINGLE_CLOCK)
    assert len(domains) == 1
    assert "clk" in domains


def test_vhdl_process_mapped_to_clock():
    """The process label is correctly associated with its clock."""
    domains = extract_domains_vhdl(VHDL_SINGLE_CLOCK)
    assert "p_reg" in domains["clk"]


def test_vhdl_dual_clock_domains_identified():
    """Two different rising_edge clocks produce two separate domain entries."""
    domains = extract_domains_vhdl(VHDL_DUAL_CLOCK)
    assert "cfg_clk" in domains
    assert "sys_clk" in domains


def test_vhdl_processes_assigned_to_correct_domains():
    """Each process is assigned to the domain matching its rising_edge call."""
    domains = extract_domains_vhdl(VHDL_DUAL_CLOCK)
    assert "p_cfg" in domains["cfg_clk"]
    assert "p_sys" in domains["sys_clk"]


# ─────────────────────────────────────────────────────────────────────────────
# Clock domain identification — SystemVerilog
# ─────────────────────────────────────────────────────────────────────────────

def test_sv_dual_clock_domains_identified():
    """Two always_ff blocks with different posedge clocks produce two domains."""
    domains = extract_domains_sv(SV_DUAL_CLOCK)
    assert "clk_a" in domains
    assert "clk_b" in domains


def test_sv_process_labels_captured():
    """The begin : label names are captured for each always_ff block."""
    domains = extract_domains_sv(SV_DUAL_CLOCK)
    assert "p_src" in domains["clk_a"]
    assert "p_dst" in domains["clk_b"]


# ─────────────────────────────────────────────────────────────────────────────
# Synchronizer detection
# ─────────────────────────────────────────────────────────────────────────────

def test_two_flop_synchronizer_detected():
    """sig_r that feeds sig_meta which feeds sig_sync is detected as synchronized."""
    stripped = strip_vhdl_comments(VHDL_TWO_FLOP)
    synced = detect_synchronizers(stripped, {"sig_r"})
    assert "sig_r" in synced


def test_unsynchronized_signal_not_in_synced_set():
    """A signal passed directly without a two-flop chain is NOT marked synchronized."""
    vhdl = """\
p_src : process(clk_a) is
begin
    if rising_edge(clk_a) then data_r <= data_in; end if;
end process p_src;
p_dst : process(clk_b) is
begin
    if rising_edge(clk_b) then output <= data_r; end if;
end process p_dst;
"""
    stripped = strip_vhdl_comments(vhdl)
    synced = detect_synchronizers(stripped, {"data_r"})
    assert "data_r" not in synced


# ─────────────────────────────────────────────────────────────────────────────
# Dual-clock instance detection
# ─────────────────────────────────────────────────────────────────────────────

def test_vhdl_dual_clock_instance_detected():
    """A VHDL port map with wr_clk and rd_clk mapped to different signals is detected."""
    stripped = strip_vhdl_comments(VHDL_FIFO_INST)
    instances = detect_dual_clock_instances_vhdl(stripped)
    assert len(instances) == 1
    assert instances[0]["instance"] == "u_fifo"
    assert instances[0]["component"] == "async_fifo"


def test_vhdl_dual_clock_clock_ports_captured():
    """The clock port-to-signal mapping is preserved in the result."""
    stripped = strip_vhdl_comments(VHDL_FIFO_INST)
    instances = detect_dual_clock_instances_vhdl(stripped)
    clocks = instances[0]["clocks"]
    assert clocks["wr_clk"] == "clk_a"
    assert clocks["rd_clk"] == "clk_b"


def test_sv_dual_clock_instance_detected():
    """An SV named port connection with two different clock signals is detected."""
    stripped = strip_sv_comments(SV_FIFO_INST)
    instances = detect_dual_clock_instances_sv(stripped)
    assert len(instances) == 1
    assert instances[0]["component"] == "async_fifo"


def test_single_clock_instance_not_detected():
    """An instance where all clock ports connect to the same signal is not reported."""
    vhdl = """\
u_reg : entity work.dff
    port map (clk => sys_clk, d => d_in, q => q_out);
"""
    stripped = strip_vhdl_comments(vhdl)
    instances = detect_dual_clock_instances_vhdl(stripped)
    assert instances == []


# ─────────────────────────────────────────────────────────────────────────────
# Graphviz dot output
# ─────────────────────────────────────────────────────────────────────────────

def test_dot_cdc_contains_domain_clusters():
    """Each clock domain appears as a named subgraph cluster in the dot output."""
    domains = {"clk_a": ["p_src"], "clk_b": ["p_dst"]}
    crossings = [{"signal": "data_r", "src_clock": "clk_a",
                  "dst_clock": "clk_b", "synchronized": False}]
    dot = write_dot_cdc("my_mod", domains, crossings, [])
    assert "cluster_clk_a" in dot
    assert "cluster_clk_b" in dot


def test_dot_cdc_unsynchronized_edge_is_dashed():
    """An unsynchronized crossing uses a dashed edge style."""
    domains = {"clk_a": ["p_src"], "clk_b": ["p_dst"]}
    crossings = [{"signal": "data_r", "src_clock": "clk_a",
                  "dst_clock": "clk_b", "synchronized": False}]
    dot = write_dot_cdc("my_mod", domains, crossings, [])
    assert 'style="dashed"' in dot


def test_dot_cdc_synchronized_edge_is_solid():
    """A synchronized crossing uses a solid edge style."""
    domains = {"clk_a": ["p_src"], "clk_b": ["p_dst"]}
    crossings = [{"signal": "sig_r", "src_clock": "clk_a",
                  "dst_clock": "clk_b", "synchronized": True}]
    dot = write_dot_cdc("my_mod", domains, crossings, [])
    assert 'style="solid"' in dot


def test_dot_cdc_signal_name_in_edge_label():
    """The crossing signal name appears in the edge label."""
    domains = {"clk_a": ["p_src"], "clk_b": ["p_dst"]}
    crossings = [{"signal": "my_signal", "src_clock": "clk_a",
                  "dst_clock": "clk_b", "synchronized": False}]
    dot = write_dot_cdc("my_mod", domains, crossings, [])
    assert "my_signal" in dot


def test_dot_cdc_fifo_cluster_present():
    """Dual-clock instances appear in a dedicated cluster in the dot output."""
    domains = {"clk_a": ["p_src"]}
    dual = [{"instance": "u_fifo", "component": "async_fifo",
             "clocks": {"wr_clk": "clk_a", "rd_clk": "clk_b"}}]
    dot = write_dot_cdc("my_mod", domains, [], dual)
    assert "cluster_dual_clk" in dot
    assert "u_fifo" in dot
