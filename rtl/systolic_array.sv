// SPDX-License-Identifier: MIT
// N x N output-stationary systolic array for signed integer GEMM.
// Boundary operands MUST be skewed by their row/column index (see docs/design.md).
// No embedded memory, DMA, or start/done controller in this baseline.
module systolic_array #(
    parameter int N = 4,
    parameter int W = 8,
    parameter int ACC_W = 32,
    parameter bit ZERO_GATE = 1'b0
) (
    input  logic                       clk,
    input  logic                       rst_n,
    input  logic                       clear,
    input  logic [N*W-1:0]             a_edge,
    input  logic [N*W-1:0]             b_edge,
    input  logic [N-1:0]               a_valid_edge,
    input  logic [N-1:0]               b_valid_edge,
    output logic [N*N*ACC_W-1:0]       c_flat,
    output logic [N*N*W-1:0]           a_taps_flat,
    output logic [N*N*W-1:0]           b_taps_flat,
    output logic [N*N-1:0]             mac_pulses,
    output logic [N*N-1:0]             gated_pulses,
    output logic [N*N*W-1:0]           mul_a_taps_flat,
    output logic [N*N*W-1:0]           mul_b_taps_flat
);
    logic signed [W-1:0] a_pipe [0:N-1][0:N-1];
    logic signed [W-1:0] b_pipe [0:N-1][0:N-1];
    logic a_valid_pipe [0:N-1][0:N-1];
    logic b_valid_pipe [0:N-1][0:N-1];
    logic signed [ACC_W-1:0] acc_pipe [0:N-1][0:N-1];

    for (genvar r = 0; r < N; r++) begin : rows
        for (genvar c = 0; c < N; c++) begin : columns
            wire signed [W-1:0] a_sel;
            wire signed [W-1:0] b_sel;
            wire a_sel_valid;
            wire b_sel_valid;
            if (c == 0) begin : left_boundary
                assign a_sel = $signed(a_edge[r*W +: W]);
                assign a_sel_valid = a_valid_edge[r];
            end else begin : left_neighbor
                assign a_sel = a_pipe[r][c-1];
                assign a_sel_valid = a_valid_pipe[r][c-1];
            end
            if (r == 0) begin : top_boundary
                assign b_sel = $signed(b_edge[c*W +: W]);
                assign b_sel_valid = b_valid_edge[c];
            end else begin : upper_neighbor
                assign b_sel = b_pipe[r-1][c];
                assign b_sel_valid = b_valid_pipe[r-1][c];
            end

            pe #(.W(W), .ACC_W(ACC_W), .ZERO_GATE(ZERO_GATE)) u_pe (
                .clk(clk), .rst_n(rst_n), .clear(clear),
                .a_in(a_sel), .b_in(b_sel),
                .a_valid_in(a_sel_valid), .b_valid_in(b_sel_valid),
                .a_out(a_pipe[r][c]), .b_out(b_pipe[r][c]),
                .a_valid_out(a_valid_pipe[r][c]),
                .b_valid_out(b_valid_pipe[r][c]),
                .accum(acc_pipe[r][c]),
                .mac_pulse(mac_pulses[r*N+c]),
                .gated_pulse(gated_pulses[r*N+c]),
                .mul_a_tap(mul_a_taps_flat[(r*N+c)*W +: W]),
                .mul_b_tap(mul_b_taps_flat[(r*N+c)*W +: W])
            );
            assign c_flat[(r*N+c)*ACC_W +: ACC_W] = acc_pipe[r][c];
            assign a_taps_flat[(r*N+c)*W +: W] = a_pipe[r][c];
            assign b_taps_flat[(r*N+c)*W +: W] = b_pipe[r][c];
        end
    end
endmodule
