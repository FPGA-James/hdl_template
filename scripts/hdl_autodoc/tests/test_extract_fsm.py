"""
test_extract_fsm.py
-------------------
Tests for extract_fsm.py.

Covers:
  - FSM transition extraction from VHDL case blocks.
  - FSM transition extraction from SystemVerilog case blocks.
  - Files with no FSM return an empty transition list.
  - Graphviz dot output contains the expected state nodes and edges.
  - RST output contains the expected sections and transition data.
"""

import pytest

from extract_fsm import (
    collect_states,
    extract_transitions_sv,
    extract_transitions_vhdl,
    write_dot,
    write_rst,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — minimal HDL snippets
# ─────────────────────────────────────────────────────────────────────────────

VHDL_FSM = """\
architecture rtl of traffic_light is
  type t_state is (RED, GREEN, AMBER);
  signal state, next_state : t_state;
begin
  p_next_state : process(state, timer_exp) is
  begin
    next_state <= state;
    case state is
      when RED =>
        if timer_exp = '1' then next_state <= GREEN; end if;
      when GREEN =>
        if timer_exp = '1' then next_state <= AMBER; end if;
      when AMBER =>
        next_state <= RED;
    end case;
  end process p_next_state;
end architecture rtl;
"""

SV_FSM = """\
module pwm_ctrl (input logic clk);
  typedef enum logic [1:0] { IDLE, COUNTING, DONE } t_state;
  t_state state, next_state;

  always_comb begin : p_next_state
    next_state = state;
    case (state)
      IDLE:     if (en)           next_state = COUNTING;
      COUNTING: if (count == 8'hFF) next_state = DONE;
      DONE:                       next_state = IDLE;
    endcase
  end
endmodule
"""


# ─────────────────────────────────────────────────────────────────────────────
# VHDL transition extraction
# ─────────────────────────────────────────────────────────────────────────────

def test_vhdl_extracts_conditional_transitions():
    """Conditional transitions (if timer_exp = '1' then next_state <= X) are detected."""
    transitions = extract_transitions_vhdl(VHDL_FSM)
    pairs = {(frm, to) for frm, to, _ in transitions}
    assert ("RED", "GREEN") in pairs
    assert ("GREEN", "AMBER") in pairs


def test_vhdl_extracts_unconditional_transition():
    """Unconditional assignments (next_state <= X without an if) are detected."""
    transitions = extract_transitions_vhdl(VHDL_FSM)
    pairs = {(frm, to) for frm, to, _ in transitions}
    assert ("AMBER", "RED") in pairs


def test_vhdl_no_fsm_returns_empty():
    """Source with no case/next_state block returns an empty list."""
    text = "entity foo is port (); end entity foo;\n"
    assert extract_transitions_vhdl(text) == []


def test_vhdl_transition_condition_captured():
    """The condition string is preserved in the transition tuple."""
    transitions = extract_transitions_vhdl(VHDL_FSM)
    cond_transitions = [(frm, to, cond) for frm, to, cond in transitions if cond]
    assert len(cond_transitions) > 0


# ─────────────────────────────────────────────────────────────────────────────
# SystemVerilog transition extraction
# ─────────────────────────────────────────────────────────────────────────────

def test_sv_extracts_conditional_transitions():
    """Conditional SV transitions inside always_comb are detected."""
    transitions = extract_transitions_sv(SV_FSM)
    pairs = {(frm, to) for frm, to, _ in transitions}
    assert ("IDLE", "COUNTING") in pairs
    assert ("COUNTING", "DONE") in pairs


def test_sv_extracts_unconditional_transition():
    """Unconditional SV transition (DONE -> IDLE) is detected."""
    transitions = extract_transitions_sv(SV_FSM)
    pairs = {(frm, to) for frm, to, _ in transitions}
    assert ("DONE", "IDLE") in pairs


def test_sv_no_fsm_returns_empty():
    """SV source with no FSM case block returns an empty list."""
    text = "module foo (input logic clk); assign out = in; endmodule\n"
    assert extract_transitions_sv(text) == []


# ─────────────────────────────────────────────────────────────────────────────
# Dot writer
# ─────────────────────────────────────────────────────────────────────────────

def test_write_dot_contains_states():
    """Dot output includes a node declaration for each state."""
    transitions = [("RED", "GREEN", "timer_exp"), ("GREEN", "AMBER", "")]
    states = collect_states(transitions)
    dot = write_dot(transitions, states, "traffic_light")
    assert "RED" in dot
    assert "GREEN" in dot
    assert "AMBER" in dot


def test_write_dot_contains_edges():
    """Dot output includes directed edges for each transition."""
    transitions = [("RED", "GREEN", "timer_exp")]
    states = collect_states(transitions)
    dot = write_dot(transitions, states, "my_fsm")
    assert "RED -> GREEN" in dot


def test_write_dot_has_start_node():
    """Dot output includes the invisible start node pointing to the first state."""
    transitions = [("IDLE", "ACTIVE", "")]
    states = collect_states(transitions)
    dot = write_dot(transitions, states, "my_fsm")
    assert "__start" in dot


# ─────────────────────────────────────────────────────────────────────────────
# RST writer
# ─────────────────────────────────────────────────────────────────────────────

def test_write_rst_contains_graphviz_directive():
    """RST output contains a '.. graphviz::' directive referencing the dot file."""
    transitions = [("RED", "GREEN", "timer_exp")]
    states = collect_states(transitions)
    rst = write_rst("fsm.dot", states, {}, transitions, "traffic_light", "traffic_light.vhd")
    assert ".. graphviz::" in rst
    assert "fsm.dot" in rst


def test_write_rst_contains_transitions_table():
    """RST output includes a transitions list-table with From/To/Condition columns."""
    transitions = [("RED", "GREEN", "timer_exp = '1'")]
    states = collect_states(transitions)
    rst = write_rst("fsm.dot", states, {}, transitions, "traffic_light", "traffic_light.vhd")
    assert "Transitions" in rst
    assert "RED" in rst
    assert "GREEN" in rst
