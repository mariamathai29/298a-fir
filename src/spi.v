
/*
 * Copyright (c) 2026 Maria Mathai, Aaron Snider
 * 8 bit SPI modules
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

        bit_counter <= 3'h0;
      end
    else
      begin
        shift_u <= {mosi_u, shift_u[6:1]};
        shift_r <= {mosi_r, shift_r[6:1]};

        bit_counter <= bit_counter + 3'h1;
      end
  end

  always @(posedge sclk or negedge rst_n)
  begin
    if (!rst_n)
      begin
        d_hold_u <= 8'h00;
        d_hold_r <= 8'h00;

        d_tog <= 1'h0;
      end
    else if (bit_counter == 3'h7)
      begin
        d_hold_u <= {mosi_u, shift_u};
        d_hold_r <= {mosi_r, shift_r};

        d_tog <= ~d_tog;
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