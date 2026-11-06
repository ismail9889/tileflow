// SPDX-License-Identifier: MIT
// Signed output-stationary processing element. All transfers advance one hop/clock.
module pe #(
    parameter int W = 8,
    parameter int ACC_W = 32,
    parameter bit ZERO_GATE = 1'b0
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    clear,
    input  logic signed [W-1:0]     a_in,
    input  logic signed [W-1:0]     b_in,
    input  logic                    a_valid_in,
    input  logic                    b_valid_in,
    output logic signed [W-1:0]     a_out,
    output logic signed [W-1:0]     b_out,
    output logic                    a_valid_out,
    output logic                    b_valid_out,
    output logic signed [ACC_W-1:0] accum,
    output logic                    mac_pulse,
    output logic                    gated_pulse,
    output logic signed [W-1:0]     mul_a_tap,
    output logic signed [W-1:0]     mul_b_tap
);
    wire valid_mac = a_valid_in && b_valid_in;
    wire zero_product = (a_in == '0) || (b_in == '0);
    // Operand isolation affects only the multiplier. Forwarding always continues.
    assign mul_a_tap = (!ZERO_GATE || (valid_mac && !zero_product)) ? a_in : '0;
    assign mul_b_tap = (!ZERO_GATE || (valid_mac && !zero_product)) ? b_in : '0;

    logic signed [2*W-1:0] product;
    assign product = mul_a_tap * mul_b_tap;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_out <= '0;
            b_out <= '0;
            a_valid_out <= 1'b0;
            b_valid_out <= 1'b0;
            accum <= '0;
            mac_pulse <= 1'b0;
            gated_pulse <= 1'b0;
        end else if (clear) begin
            a_out <= '0;
            b_out <= '0;
            a_valid_out <= 1'b0;
            b_valid_out <= 1'b0;
            accum <= '0;
            mac_pulse <= 1'b0;
            gated_pulse <= 1'b0;
        end else begin
            a_out <= a_in;
            b_out <= b_in;
            a_valid_out <= a_valid_in;
            b_valid_out <= b_valid_in;
            mac_pulse <= valid_mac;
            gated_pulse <= ZERO_GATE && valid_mac && zero_product;
            if (valid_mac && (!ZERO_GATE || !zero_product))
                accum <= accum + ACC_W'(product);
        end
    end
endmodule
