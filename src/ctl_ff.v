`default_nettype none

module ctl_ff (
    input  wire clk,
    input  wire rst_n,
    input  wire d,
    output wire q
);

// copy ring controls to avoid large fanout

`ifdef AF_BEHAVIORAL_FF
    reg r;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) r <= 1'b0;
        else        r <= d;
    assign q = r;
`else
    (* keep *) gf180mcu_fd_sc_mcu7t5v0__dffrnq_2 u_ff (
        .CLK (clk),
        .RN  (rst_n),
        .D   (d),
        .Q   (q)
    );
`endif
endmodule
