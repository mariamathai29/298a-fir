`default_nettype none

module filter_core (
    input wire clk,
    input wire rst,

    input wire adapt_en,
    input wire [2:0] mu_sel,

    input wire d_pre,
    input wire d_stb,

    input wire [7:0] d_u,
    input wire [7:0] d_r,

    output wire t_load,
    output wire [7:0] t_y,
    output wire [7:0] t_e,
    output wire [7:0] t_w,

    output reg sat_flag,
    output reg ovf_flag
);

    /////////////////
    // CONTROL FSM	
    /////////////////
    localparam S_IDLE = 2'd0, S_MAC = 2'd1, S_FIN = 2'd2, S_UPD = 2'd3;

    reg [1:0] cur, next, digit_q; // current state, next state, digit group
    reg [4:0] cnt, cnt_n; // mac and update count (next)

    reg go, rot;

    // next state logic
    always @(*) begin
        next = cur;
        cnt_n = cnt;

        case (cur)
            S_IDLE:
                if (go) begin
                    next = S_MAC;
                    cnt_n = 5'd0;
                end 
            S_MAC:
                begin
                    cnt_n = cnt + 5'd1;
                    if (cnt == 5'd16) begin
                        next = S_FIN;
                    end
                end
            S_FIN:
                begin
                    next = S_UPD;
                    cnt_n = 5'd0;
                end
            S_UPD:
                begin
                    cnt_n = cnt + 5'd1;
                    if (cnt == 5'd3) begin
                        next = S_IDLE;
                    end
                end
        endcase

    end

    // output logic
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            cur <= S_IDLE;
            cnt <= 5'd0;
            digit_q <= 2'd3;
        end else begin
            cur <= next;
            cnt <= cnt_n;
            digit_q <= ~(cnt_n[3:2]);
        end
    end

    /////////////////
    // RING CONTROLS
    /////////////////
    wire go_n = d_pre && (next == S_IDLE);
    wire rot_n = ((next == S_MAC) && (!(cnt_n[4]))) || (next == S_UPD); 
    wire load_n = (next == S_UPD) && (cnt_n == 5'd0);

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            go <= 1'b0;
            rot <= 1'b0;
        end else begin
            go <= go_n;
            rot <= rot_n;
        end
    end

    reg transmit_q;
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            transmit_q <= 1'b0;
        end else begin
            transmit_q <= load_n;
        end
    end


    /////////////////
    // RING REGS
    /////////////////
    reg signed [7:0] x [0:3]; // Q1.7; x[0] = newest between steps
    reg signed [13:0] w [0:3]; // Q2.12

    wire signed [13:0] w_new;
    wire w_write;

    // rotate or update half tap rings
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            x[0] <= 8'sd0;
            x[1] <= 8'sd0;
        end else if (go) begin
            x[0] <= d_u;
            x[1] <= x[0];
        end else if (rot) begin
            x[0] <= x[1];
            x[1] <= x[2];
        end
    end

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            x[2] <= 8'sd0;
            x[3] <= 8'sd0;
        end else if (go) begin
            x[2] <= x[1];
            x[3] <= x[2];
        end else if (rot) begin
            x[2] <= x[3];
            x[3] <= x[0];
        end
    end

    // rotate weight rings
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            w[0] <= 14'sd0;
            w[1] <= 14'sd0;
            w[2] <= 14'sd0;
            w[3] <= 14'sd0;
        end else begin
            w[0] <= rot ? w[1] : w[0];
            w[1] <= rot ? w[2] : w[1];
            w[2] <= rot ? w[3] : w[2];
            w[3] <= rot ? (w_write ? w_new : w[0]) : w[3];
        end
    end

    /////////////////
    // COMPUTE MAC
    /////////////////
    reg signed [23:0] acc; // 5.15 accumulate
    reg signed [15:0] pp_q; // registered partial prod result
    reg horner;

    wire mac_go = (cur == S_MAC) && !cnt[4];
    wire [8:0] x0_ext = {x[0], 1'b0}; // extend multiplicand
    wire [2:0] booth_groups = x0_ext[{1'b0, digit_q, 1'b0} +: 3]; // booth grouping per pp

    wire signed [13:0] w0_mul = w[0];
    reg signed [15:0] pp; // partial prod result (comb)

    always @(*) begin
        case(booth_groups)
            3'b001, 3'b010: pp = {{2{w0_mul[13]}}, w0_mul};       // X
            3'b011: pp = {w0_mul[13], w0_mul, 1'b0};              // 2X
            3'b100: pp = -{w0_mul[13], w0_mul, 1'b0};             // -2X
            3'b101, 3'b110: pp = -{{2{w0_mul[13]}}, w0_mul};      // -X
            default: pp = 16'sd0;                                //  0
        endcase
    end

    wire signed [23:0] acc_sum = acc + {{8{pp_q[15]}}, pp_q}; // sign extend for pp sum
    wire signed [23:0] acc_n = horner ? (acc_sum << 2) : acc_sum; // (((PP3)*4+PP2)*4+PP1)*4+PP0

    always @(posedge clk) begin
        acc <= go ? 24'sd32 : acc_n;    // 32 * 4^3 = 2^11: round half up
        pp_q <= go ? 16'sd0 : pp;
        horner <= mac_go && (cnt[1:0] == 2'd3) && (cnt[3:2] != 2'd3);
    end


    /////////////////
    // COMPUTE ERROR
    /////////////////
    reg signed [7:0] r_q, y_q, e_q; // interfered signal, fir transfer, error regs
    reg e_pos_q, e_neg_q; // error sign

    wire signed [11:0] acc_y = acc[23:12];

    // check y saturation
    wire y_sat_hi = !acc_y[11] && (|acc_y[10:7]);
    wire y_sat_lo = acc_y[11] && !(&acc_y[10:7]);
    wire signed [7:0] y_plain = acc_y[7:0]; // if no saturation, extract as true y value

    wire signed [7:0] y = y_sat_hi ? 8'sd127 : y_sat_lo ? -8'sd128 : y_plain;

    wire signed [8:0] r9 = {r_q[7], r_q}; // sign extend r
    wire signed [8:0] e_plain = r9 - {acc_y[7], acc_y[7:0]}; // compute e with no saturation
    wire signed [8:0] e_if_y_hi = r9 - 9'sd127; // compute e with hi saturation
    wire signed [8:0] e_if_y_lo = r9 + 9'sd128; // compute e with lo saturation
    wire signed [8:0] e_wide = y_sat_hi ? e_if_y_hi : y_sat_lo ? e_if_y_lo : e_plain; // Q2.7
    // check e saturation
    wire e_sat_hi = !e_wide[8] && e_wide[7];
    wire e_sat_lo = e_wide[8] && !e_wide[7];

    wire signed [7:0] e = e_sat_hi ? 8'sd127 : e_sat_lo ? -8'sd128 : e_wide[7:0];

    // y high saturation: e = r - 127
    // y low saturation: e = r + 128
    // else check r-y via inequality
    wire e_pos = y_sat_hi ? 1'b0 : y_sat_lo ? (r_q != -8'sd128) : (r_q > y_plain);
    wire e_neg = y_sat_hi ? (r_q != 8'sd127) : y_sat_lo ? 1'b0 : (r_q < y_plain);

    always @(posedge clk) begin
        if (go)
            r_q <= d_r;
        if (cur == S_FIN) begin
            y_q <= y;
            e_q <= e;
            e_pos_q <= e_pos;
            e_neg_q <= e_neg;
        end
    end


    /////////////////
    // WEIGHT UPDATE
    /////////////////
    reg [7:0] mu_q; // LR
    reg adapt_q; // adapt enable reg
    reg x_pos_q, x_neg_q; // x sign

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            mu_q <= 8'd1;
            adapt_q <= 1'b0;
        end else begin
            mu_q <= 8'd1 << mu_sel; // modify eff LR
            if (cur == S_FIN) begin
                adapt_q <= adapt_en;
            end
        end
    end

    // sign extraction
    always @(posedge clk) begin
        x_pos_q <= (cur == S_UPD) ? (!x[1][7] && |x[1][6:0]) : (!x[0][7] && |x[0][6:0]);
        x_neg_q <= (cur == S_UPD) ? x[1][7] : x[0][7];
    end

    wire [14:0] mu_ext = {7'd0, mu_q}; 
    wire w_inc = (e_pos_q && x_pos_q) || (e_neg_q && x_neg_q); // inc same sign
    wire w_dec = (e_pos_q && x_neg_q) || (e_neg_q && x_pos_q); // dec opp sign

    // speculative update computations
    wire [14:0] w_plus = {w[0][13], w[0]} + mu_ext;
    wire [14:0] w_minus = {w[0][13], w[0]} - mu_ext;

    // check for overflow
    wire w_plus_ovf = w_plus[14] ^ w_plus[13];
    wire w_minus_ovf = w_minus[14] ^ w_minus[13];

    // saturate extremes to prevent wraparound
    wire signed [13:0] w_plus_sat = w_plus_ovf ? {w_plus[14], {13{~w_plus[14]}}} : w_plus[13:0];
    wire signed [13:0] w_minus_sat = w_minus_ovf ? {w_minus[14], {13{~w_minus[14]}}} : w_minus[13:0];

    wire w_clipped = (w_inc && w_plus_ovf) || (w_dec && w_minus_ovf);
    assign w_new = w_inc ? w_plus_sat : w_dec ? w_minus_sat : w[0];
    assign w_write = (cur == S_UPD) && adapt_q;

    /////////////////
    // WEIGHT READOUT LANE
    /////////////////

    reg [1:0] mon_k; // weight carried by this step frame
    reg [7:0] mon_w; // top 8 bits (Q2.6)

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            mon_k <= 2'd0;
        end else if (transmit_q) begin
            mon_k <= mon_k + 2'd1;
        end
    end

    always @(posedge clk) begin
        if (cur == S_MAC && cnt == {3'd0, mon_k}) begin
            mon_w <= w[0][13:6];
        end
    end

    // flags
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            ovf_flag <= 1'b0; // a sample arrived while a step was running
            sat_flag <= 1'b0; // y, e or a weight saturated
        end else begin
            if (d_stb && !go) begin
                ovf_flag <= 1'b1;
            end
            if (cur == S_FIN && (y_sat_hi || y_sat_lo || e_sat_hi || e_sat_lo)) begin
                sat_flag <= 1'b1;
            end
            if (w_write && w_clipped) begin
                sat_flag <= 1'b1;
            end
        end
    end

    // output assignments
    assign t_load = transmit_q;
    assign t_y = y_q;
    assign t_e = e_q;
    assign t_w = mon_w;

    wire _unused = &{1'b0, acc[7:0]};

endmodule
