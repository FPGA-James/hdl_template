library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- axi_lite library provided by hdl-modules (fetched via Bender).
library axi_lite;
use axi_lite.axi_lite_pkg.all;

-- <<NAME>> cocotb-only AXI-Lite flattening wrapper around <<NAME>>_top.
--
-- Why this file exists: <<NAME>>_top's s_axi_m2s/s_axi_s2m ports are of
-- hdl-modules' axi_lite_m2s_t/axi_lite_s2m_t *record* types. GHDL's VPI
-- backend (the only interface cocotb's GHDL integration uses) cannot expose
-- VHDL record-typed ports as simulator objects at all -- verified empirically
-- with a minimal reproduction: a record-typed top-level port is completely
-- absent from cocotb's `dir(dut)`, and direct attribute access raises
-- "<entity> contains no child object named <port>". A flattening wrapper
-- entity with scalar/vector ports one level down does not have this problem
-- (its ports show up normally), so this wrapper exists purely to give
-- cocotb something it can see.
--
-- This wrapper is NOT part of the project's synthesizable RTL and is not
-- referenced by Bender.yml/synth/impl -- it is used only as the GHDL
-- TOPLEVEL for `make sim FRAMEWORK=cocotb SIM=ghdl TOPLEVEL_HDL=vhdl`
-- (see tb/cocotb/Makefile). Its flat s_axi_* port names and widths are
-- identical to <<NAME>>_top.sv's native flat AXI-Lite ports, so the same
-- tb/cocotb/test_NAME.py drives both language implementations unchanged.
entity <<NAME>>_cocotb_top is
    port (
        clk           : in  std_logic;
        rst_n         : in  std_logic;

        pulse_i       : in  std_logic;

        s_axi_awvalid : in  std_logic;
        s_axi_awready : out std_logic;
        s_axi_awaddr  : in  std_logic_vector(7 downto 0);
        s_axi_wvalid  : in  std_logic;
        s_axi_wready  : out std_logic;
        s_axi_wdata   : in  std_logic_vector(31 downto 0);
        s_axi_wstrb   : in  std_logic_vector(3 downto 0);
        s_axi_bvalid  : out std_logic;
        s_axi_bready  : in  std_logic;
        s_axi_bresp   : out std_logic_vector(1 downto 0);
        s_axi_arvalid : in  std_logic;
        s_axi_arready : out std_logic;
        s_axi_araddr  : in  std_logic_vector(7 downto 0);
        s_axi_rvalid  : out std_logic;
        s_axi_rready  : in  std_logic;
        s_axi_rdata   : out std_logic_vector(31 downto 0);
        s_axi_rresp   : out std_logic_vector(1 downto 0)
    );
end entity <<NAME>>_cocotb_top;

architecture sim of <<NAME>>_cocotb_top is

    signal s_axi_m2s : axi_lite_m2s_t := axi_lite_m2s_init;
    signal s_axi_s2m : axi_lite_s2m_t := axi_lite_s2m_init;

begin

    -- Pack the flat master-to-slave signals into the axi_lite_m2s_t record.
    -- Fields not driven here (upper, unused address/data bits) keep the
    -- package's own init values (zero for address, don't-care for data).
    pack_m2s : process (all)
        variable m2s : axi_lite_m2s_t := axi_lite_m2s_init;
    begin
        m2s := axi_lite_m2s_init;

        m2s.write.aw.valid := s_axi_awvalid;
        m2s.write.aw.addr(s_axi_awaddr'range) := unsigned(s_axi_awaddr);

        m2s.write.w.valid := s_axi_wvalid;
        m2s.write.w.data(s_axi_wdata'range) := std_ulogic_vector(s_axi_wdata);
        m2s.write.w.strb(s_axi_wstrb'range) := std_ulogic_vector(s_axi_wstrb);

        m2s.write.b.ready := s_axi_bready;

        m2s.read.ar.valid := s_axi_arvalid;
        m2s.read.ar.addr(s_axi_araddr'range) := unsigned(s_axi_araddr);

        m2s.read.r.ready := s_axi_rready;

        s_axi_m2s <= m2s;
    end process;

    -- Unpack the axi_lite_s2m_t record into flat slave-to-master signals.
    s_axi_awready <= s_axi_s2m.write.aw.ready;
    s_axi_wready  <= s_axi_s2m.write.w.ready;
    s_axi_bvalid  <= s_axi_s2m.write.b.valid;
    s_axi_bresp   <= std_logic_vector(s_axi_s2m.write.b.resp);
    s_axi_arready <= s_axi_s2m.read.ar.ready;
    s_axi_rvalid  <= s_axi_s2m.read.r.valid;
    s_axi_rdata   <= std_logic_vector(s_axi_s2m.read.r.data(s_axi_rdata'range));
    s_axi_rresp   <= std_logic_vector(s_axi_s2m.read.r.resp);

    u_top : entity work.<<NAME>>_top
        port map (
            clk       => clk,
            rst_n     => rst_n,
            pulse_i   => pulse_i,
            s_axi_m2s => s_axi_m2s,
            s_axi_s2m => s_axi_s2m
        );

end architecture sim;
