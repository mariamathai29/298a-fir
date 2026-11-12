`default_nettype none

// Pin assignments:
// ui_in : [0] SCLK_IN  
//         [1] CS_IN  
//         [2] MOSI_u_in  
//         [3] MOSI_r_in

// uo_out: [0] SCLK_OUT 
//         [1] FS_OUT 
//         [2] MOSI_y_out 
//         [3] MOSI_e_out
//         [4] MOSI_w_out
//         [5] debug_o1 (dropped sample) 
//         [6] debug_o2 (saturation)

// uio   : [0] adapt_en (in)
//         [3:1] mu_sel (in)

module filter_top (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
    assign uio_out = 8'h00;
    assign uio_oe  = 8'h00;

    // clk-domain reset (async assert, sync deassert)
    reg [1:0] rst_sync;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rst_sync <= 2'b00;
        end else begin
            rst_sync <= {rst_sync[0], 1'b1};
        end
    end

    wire rst_n_s = rst_sync[1];

    // Input port (SCLK_IN domain)
    wire       d_tog;
    wire [7:0] d_u, d_r;

    spi_receive reciever (
        .sclk     (ui_in[0]),
        .cs_n     (ui_in[1]),
        .rst_n    (rst_n),
        .mosi_u   (ui_in[2]),
        .mosi_r   (ui_in[3]),
        .d_tog    (d_tog),
        .d_hold_u (d_u),
        .d_hold_r (d_r)
    );

    // 2 FF synchronizer into clk
    // ctl = {mu_sel[2:0], adapt_en}
    wire [3:0] ctl_in = uio_in[3:0];
    reg  [3:0] ctl_s1, ctl_s2;
    reg  [2:0] d_s;

    always @(posedge clk or negedge rst_n_s) begin
        if (!rst_n_s) begin
            ctl_s1 <= 4'd0;
            ctl_s2 <= 4'd0;
            d_s    <= 3'd0;
        end else begin
            ctl_s1 <= ctl_in;
            ctl_s2 <= ctl_s1;
            d_s    <= {d_s[1:0], d_tog};
        end
    end
    wire d_stb = d_s[2] ^ d_s[1];
    wire d_pre = d_s[1] ^ d_s[0];        // d_stb one cycle early

    // core 
    wire       tx_load, sat_flag, ovf_flag;
    wire [7:0] tx_a, tx_b, tx_c;

    filter_core u_core (
        .clk      (clk),
        .rst      (~rst_n_s),
        .adapt_en (ctl_s2[0]),
        .mu_sel   (ctl_s2[3:1]),
        .d_pre    (d_pre),
        .d_stb    (d_stb),
        .d_u      (d_u),
        .d_r      (d_r),
        .t_load   (tx_load),
        .t_y      (tx_a),
        .t_e      (tx_b),
        .t_w      (tx_c),
        .sat_flag (sat_flag),
        .ovf_flag (ovf_flag)
    );

    // output
    wire       sclk_o, fs_o;
    wire [2:0] sdo;

    spi_transmit u_tx (
        .clk    (clk),
        .rst_n  (rst_n_s),
        .load   (tx_load),
        .d_a    (tx_a),
        .d_b    (tx_b),
        .d_c    (tx_c),
        .sclk_o (sclk_o),
        .fs_o   (fs_o),
        .sdo    (sdo)
    );

    assign uo_out = {1'b0, sat_flag, ovf_flag, sdo, fs_o, sclk_o};

    wire _unused = &{ena, ui_in[7:5], ui_in[3], uio_in[7:4], 1'b0};

endmodule
