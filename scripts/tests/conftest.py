"""Shared fixtures for scripts/tests/."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def vhdl_core_file(tmp_path: Path) -> Path:
    content = """\
library ieee;
use ieee.std_logic_1164.all;

entity demo_core is
    port (
        clk           : in  std_logic;
        rst_n         : in  std_logic;
        enable_i      : in  std_logic;
        increment_i   : in  integer range 1 to 255;
        reset_count_i : in  std_logic;
        enabled_o     : out std_logic;
        pulse_count_o : out std_logic_vector(15 downto 0)
    );
end entity demo_core;

architecture rtl of demo_core is
begin
end architecture rtl;
"""
    path = tmp_path / "demo_core.vhd"
    path.write_text(content)
    return path


@pytest.fixture
def sv_core_file(tmp_path: Path) -> Path:
    content = """\
module demo_core
#(
    parameter int unsigned COUNT_W = demo_pkg::C_COUNT_W
) (
    input  logic              clk,
    input  logic              rst_n,
    input  logic              enable_i,
    input  int unsigned       increment_i,
    input  logic              reset_count_i,
    output logic              enabled_o,
    output logic [COUNT_W-1:0] pulse_count_o
);
endmodule : demo_core
"""
    path = tmp_path / "demo_core.sv"
    path.write_text(content)
    return path
