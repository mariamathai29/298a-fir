/*
 * Copyright (c) 2026 Maria Mathai, Aaron Snider
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_example (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  // All output pins must be assigned. If not used, assign to 0.
  assign uo_out  = ui_in + uio_in;  // Example: ou_out is the sum of ui_in and uio_in
  assign uio_out = 0;
  assign uio_oe  = 0;

  // List all unused inputs to prevent warnings
  wire _unused = &{ena, clk, rst_n, 1'b0};

endmodule

/*
8 bit SPI modules
*/

module spi_receive(
    input  wire       sclk,
    input  wire       cs_n,
    input  wire       rst_n,
    input  wire       mosi_u,
    input  wire       mosi_r,
    output reg        d_tog,
    output reg  [7:0] d_hold_u,
    output reg  [7:0] d_hold_r
);

  reg [6:0] shift_u;
  reg [6:0] shift_r;
  reg [2:0] bit_counter;

  wire frame_rst = rst_n & ~cs_n;

  always @(posedge sclk or negedge frame_rst)
  begin
    if (!frame_rst)
      begin 
        shift_u <= 7'h00;
        shift_r <= 7'h00;

        d_tog <= 1'h0;
        bit_counter <= 3'h0;
      end
    else
      begin
        shift_u <= {mosi_u, shift_u[6:1]};
        shift_r <= {mosi_r, shift_r[6:1]};

        bit_counter <= bit_counter + 3'h1;

        d_tog <= (bit_counter == 3'h7);
      end
  end

  always @(posedge sclk or negedge rst_n)
  begin
    if (!rst_n)
      begin
        d_hold_u <= 8'h00;
        d_hold_r <= 8'h00;
      end
    else if (bit_counter == 3'h7)
      begin
        d_hold_u <= {mosi_u, shift_u};
        d_hold_r <= {mosi_r, shift_r};
      end
  end
  
endmodule

module spi_transmit (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        load,
    input  wire [7:0] d_a,
    input  wire [7:0] d_b,
    output reg         sclk_o,
    output reg         fs_o,
    output wire [1:0]  sdo          // {b, a}
);

  reg [7:0] d_a_hold;
  reg [7:0] d_b_hold;
  reg [2:0] bit_counter;
  reg transmitting;

  // Continuous assignments for serial outputs
  assign sdo[0] = d_a_hold[0];
  assign sdo[1] = d_b_hold[0];

  always @(posedge clk or negedge rst_n) 
  begin
    if (!rst_n) 
    begin
      fs_o          <= 1'h1;
      d_b_hold      <= 8'h00;
      d_a_hold      <= 8'h00;
      transmitting  <= 1'h0;
      bit_counter   <= 3'h0;
      sclk_o        <= 1'h0;
    end
    else 
    begin
      if (!transmitting) 
      begin
        sclk_o <= 1'h0;
        if (load) 
        begin
          d_a_hold     <= d_a;
          d_b_hold     <= d_b;
          transmitting <= 1'h1;
          fs_o         <= 1'h0;
          bit_counter  <= 3'h0;
        end
      end
      else 
      begin
        sclk_o <= ~sclk_o;
      
        if (sclk_o == 1'h1) 
        begin
          if (bit_counter == 3'h7) 
          begin
            transmitting <= 1'h0;
            fs_o         <= 1'h1;
            bit_counter  <= 3'h0;
          end 
          else 
          begin
            d_a_hold    <= {1'h0, d_a_hold[7:1]};
            d_b_hold    <= {1'h0, d_b_hold[7:1]};
            bit_counter <= bit_counter + 3'h1;
          end
        end
      end
    end
  end

endmodule