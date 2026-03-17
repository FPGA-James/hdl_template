"""cocotb testbench for uart_core.

Tests the UART TX and RX paths directly without the AXI4-Lite register block.
Runs against both VHDL (via GHDL) and SystemVerilog (via Verilator/Icarus)
implementations — port names are identical across both languages.

Run via the top-level Makefile:
    make sim FRAMEWORK=cocotb SIM=ghdl       TOPLEVEL_HDL=vhdl
    make sim FRAMEWORK=cocotb SIM=verilator  TOPLEVEL_HDL=sv
    make sim FRAMEWORK=cocotb SIM=icarus     TOPLEVEL_HDL=sv

Test cases:
    test_tx_loopback     — send a byte via AXI-Stream TX, receive via AXI-Stream RX
                           using the internal loopback path
    test_rx_byte         — drive uart_rx_i manually, verify AXI-Stream RX output
    test_tx_busy         — tx_busy_o tracks the frame duration
    test_rx_frame_error  — bad stop bit asserts rx_frame_err_o for one cycle
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# Small baud divisor for fast simulation: 100 MHz / 32 ≈ 3.125 Mbaud
BAUD_DIV = 32
CLK_NS = 10     # 10 ns clock (100 MHz)
BAUD_NS = CLK_NS * BAUD_DIV


async def reset_dut(dut, cycles: int = 5) -> None:
    """Assert rst_n low for *cycles* clock edges then release."""
    dut.rst_n.value = 0
    dut.tx_enable_i.value = 0
    dut.rx_enable_i.value = 0
    dut.loopback_i.value = 0
    dut.baud_div_i.value = BAUD_DIV
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 1  # always last for UART (one byte = one packet)
    dut.uart_rx_i.value = 1     # idle high
    dut.m_axis_tready.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def uart_rx_send(dut, byte: int) -> None:
    """Drive dut.uart_rx_i with a single 8N1 UART frame (LSB first).

    Each bit period is BAUD_DIV clock cycles.
    """
    dut.uart_rx_i.value = 0                             # start bit
    await Timer(BAUD_NS, unit="ns")
    for bit_idx in range(8):
        dut.uart_rx_i.value = (byte >> bit_idx) & 1    # D0 first (LSB first)
        await Timer(BAUD_NS, unit="ns")
    dut.uart_rx_i.value = 1                             # stop bit
    await Timer(BAUD_NS, unit="ns")


async def wait_for_signal(signal, value=1, timeout_ns: int = 10_000) -> bool:
    """Poll *signal* each clock cycle until it equals *value* or timeout expires."""
    for _ in range(timeout_ns // CLK_NS):
        if signal.value == value:
            return True
        await Timer(CLK_NS, unit="ns")
    return False


@cocotb.test()
async def test_tx_loopback(dut):
    """Send 0xA5 via AXI-Stream TX; receive it via AXI-Stream RX in loopback mode."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    await reset_dut(dut)

    dut.tx_enable_i.value = 1
    dut.rx_enable_i.value = 1
    dut.loopback_i.value = 1
    dut.m_axis_tready.value = 1

    dut.s_axis_tdata.value = 0xA5
    dut.s_axis_tvalid.value = 1

    # Wait for TX to accept the byte
    accepted = await wait_for_signal(dut.s_axis_tready, value=1, timeout_ns=BAUD_NS * 3)
    assert accepted, "s_axis_tready never asserted — TX did not accept the byte"

    await RisingEdge(dut.clk)
    dut.s_axis_tvalid.value = 0

    # Wait for RX to deliver the byte (full frame = 10 baud periods)
    received = await wait_for_signal(dut.m_axis_tvalid, value=1,
                                     timeout_ns=BAUD_NS * 15)
    assert received, "m_axis_tvalid never asserted — RX did not deliver the byte"
    assert dut.m_axis_tdata.value == 0xA5, (
        f"Loopback byte mismatch: expected 0xA5, got {int(dut.m_axis_tdata.value):#04x}"
    )
    assert dut.m_axis_tlast.value == 1, \
        "m_axis_tlast must be '1' alongside tvalid — every UART byte is its own packet"


@cocotb.test()
async def test_rx_byte(dut):
    """Drive a frame on uart_rx_i and verify the decoded byte on the AXI-Stream output."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    await reset_dut(dut)

    dut.rx_enable_i.value = 1
    # Keep tready low during the frame so tvalid holds until we observe it;
    # setting tready=1 early causes tvalid to pulse for a single cycle, which
    # the polling loop can miss due to timing misalignment.

    await uart_rx_send(dut, 0xC3)

    received = await wait_for_signal(dut.m_axis_tvalid, value=1,
                                     timeout_ns=BAUD_NS * 5)
    assert received, "m_axis_tvalid never asserted after RX frame"
    assert dut.m_axis_tdata.value == 0xC3, (
        f"RX byte mismatch: expected 0xC3, got {int(dut.m_axis_tdata.value):#04x}"
    )
    dut.m_axis_tready.value = 1
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_tx_busy(dut):
    """tx_busy_o should be low when idle, high during a frame, low after stop bit."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    await reset_dut(dut)

    dut.tx_enable_i.value = 1

    assert dut.tx_busy_o.value == 0, "tx_busy should be low before any transmission"

    dut.s_axis_tdata.value = 0xFF
    dut.s_axis_tvalid.value = 1

    busy_high = await wait_for_signal(dut.tx_busy_o, value=1, timeout_ns=BAUD_NS * 3)
    assert busy_high, "tx_busy never went high after TX started"
    dut.s_axis_tvalid.value = 0

    # Full frame: start + 8 data + stop = 10 baud periods
    busy_low = await wait_for_signal(dut.tx_busy_o, value=0,
                                     timeout_ns=BAUD_NS * 13)
    assert busy_low, "tx_busy never returned low after stop bit"


@cocotb.test()
async def test_rx_frame_error(dut):
    """A bad stop bit (0 instead of 1) should assert rx_frame_err_o for one cycle."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    await reset_dut(dut)

    dut.rx_enable_i.value = 1

    # Send start + 8 data bits + bad stop bit (0 instead of 1)
    dut.uart_rx_i.value = 0                             # start bit
    await Timer(BAUD_NS, unit="ns")
    for bit_idx in range(8):
        dut.uart_rx_i.value = (0x55 >> bit_idx) & 1
        await Timer(BAUD_NS, unit="ns")
    dut.uart_rx_i.value = 0                             # bad stop bit — hold low
    # The RX samples at the bit midpoint (BAUD_DIV/2 cycles in) and fires the
    # error pulse there; do NOT wait the full bit period before polling or we
    # will have already passed the one-cycle pulse.
    frame_err = await wait_for_signal(dut.rx_frame_err_o, value=1,
                                      timeout_ns=BAUD_NS * 3)
    dut.uart_rx_i.value = 1                             # restore idle
    assert frame_err, "rx_frame_err_o never asserted on bad stop bit"
