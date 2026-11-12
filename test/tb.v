`default_nettype none
`timescale 1ns / 1ps

/* This testbench just instantiates the module and makes some convenient wires
   that can be driven / tested by the cocotb test.py.
*/
module tb ();

  // Dump the signals to a FST file. You can view it with gtkwave or surfer.
  initial begin
    $dumpfile("tb.fst");
    $dumpvars(0, tb);
    #1;
  end

  // Wire up the inputs and outputs:
  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  reg [7:0] uio_in;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;
`ifdef GL_TEST
  wire VPWR = 1'b1;
  wire VGND = 1'b0;
`endif

  // Replace tt_um_example with your module name:
  tt_um_filter_top user_project (

      // Include power ports for the Gate Level test:
`ifdef GL_TEST
      .VPWR(VPWR),
      .VGND(VGND),
`endif

      .ui_in  (ui_in),    // Dedicated inputs
      .uo_out (uo_out),   // Dedicated outputs
      .uio_in (uio_in),   // IOs: Input path
      .uio_out(uio_out),  // IOs: Output path
      .uio_oe (uio_oe),   // IOs: Enable path (active high: 0=input, 1=output)
      .ena    (ena),      // enable - goes high when design is selected
      .clk    (clk),      // clock
      .rst_n  (rst_n)     // not reset
  );

`ifndef GL_TEST
  // ===========================================================================
  // Unit-test instances for src/spi.v (used by test_spi_unit.py).
  // RTL only: the gate-level netlist no longer contains these modules.
  // They share `clk` with the top-level design and are otherwise independent.
  // ===========================================================================

  // ------------------------------------------------ spi_transmit on its own
  reg        tx_rst_n;
  reg        tx_load;
  reg  [7:0] tx_d_a;
  reg  [7:0] tx_d_b;
  reg  [7:0] tx_d_c;
  wire       tx_sclk;
  wire       tx_fs;
  wire [2:0] tx_sdo;

  spi_transmit u_tx (
      .clk   (clk),
      .rst_n (tx_rst_n),
      .load  (tx_load),
      .d_a   (tx_d_a),
      .d_b   (tx_d_b),
      .d_c   (tx_d_c),
      .sclk_o(tx_sclk),
      .fs_o  (tx_fs),
      .sdo   (tx_sdo)
  );

  // -------------------------------- spi_receive on its own (sclk/cs_n by test)
  reg        rx_sclk;
  reg        rx_cs_n;
  reg        rx_rst_n;
  reg        rx_mosi_u;
  reg        rx_mosi_r;
  wire       rx_d_tog;
  wire [7:0] rx_d_hold_u;
  wire [7:0] rx_d_hold_r;

  spi_receive u_rx (
      .sclk    (rx_sclk),
      .cs_n    (rx_cs_n),
      .rst_n   (rx_rst_n),
      .mosi_u  (rx_mosi_u),
      .mosi_r  (rx_mosi_r),
      .d_tog   (rx_d_tog),
      .d_hold_u(rx_d_hold_u),
      .d_hold_r(rx_d_hold_r)
  );

  // ------------------------------------------------ spi_transmit -> spi_receive
  // sdo[0] (d_a) -> mosi_u, sdo[1] (d_b) -> mosi_r, sclk_o -> sclk, fs_o -> cs_n
  // sdo[2] (d_c) is left unconnected since spi_receive only has two lanes
  reg        lb_rst_n;
  reg        lb_load;
  reg  [7:0] lb_d_a;
  reg  [7:0] lb_d_b;
  reg  [7:0] lb_d_c;
  wire       lb_sclk;
  wire       lb_fs;
  wire [2:0] lb_sdo;
  wire       lb_d_tog;
  wire [7:0] lb_d_hold_u;
  wire [7:0] lb_d_hold_r;

  spi_transmit u_lb_tx (
      .clk   (clk),
      .rst_n (lb_rst_n),
      .load  (lb_load),
      .d_a   (lb_d_a),
      .d_b   (lb_d_b),
      .d_c   (lb_d_c),
      .sclk_o(lb_sclk),
      .fs_o  (lb_fs),
      .sdo   (lb_sdo)
  );

  spi_receive u_lb_rx (
      .sclk    (lb_sclk),
      .cs_n    (lb_fs),
      .rst_n   (lb_rst_n),
      .mosi_u  (lb_sdo[0]),
      .mosi_r  (lb_sdo[1]),
      .d_tog   (lb_d_tog),
      .d_hold_u(lb_d_hold_u),
      .d_hold_r(lb_d_hold_r)
  );
`endif

endmodule
