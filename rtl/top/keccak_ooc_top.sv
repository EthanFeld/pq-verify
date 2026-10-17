module keccak_ooc_top #(
    parameter integer RPC = 1
) (
    input  logic clk,
    input  logic rst_n,
    input  logic start,
    output logic busy,
    output logic done,
    output logic pin_out
);
    logic [63:0] lfsr;
    logic [1599:0] state_in;
    logic [1599:0] state_out;
    logic core_busy;
    logic pending;
    logic accept;

    // Seed the live bank like a sponge lane, retaining the remaining state.
    // This keeps every round/state bit while avoiding a 1,600-bit input mux
    // and the artificial fanout of repeating one LFSR across all 25 lanes.
    assign state_in = {state_out[1599:64], state_out[63:0] ^ lfsr};
    assign busy = core_busy | pending;
    assign accept = start & ~busy;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lfsr <= 64'hd1b54a32d192ed03;
            pending <= 1'b0;
        end else begin
            // The bank accepts the seed one clock before permutation start.
            pending <= accept;
            if (accept)
                lfsr <= {lfsr[62:0], lfsr[63] ^ lfsr[62] ^ lfsr[60] ^ lfsr[59]};
        end
    end

    keccak_f1600 #(.RPC(RPC), .IN_PLACE(1)) u_keccak (
        .clk       (clk),
        .rst_n     (rst_n),
        .start     (pending),
        .state_load(accept),
        .state_in  (state_in),
        .state_out (state_out),
        .busy      (core_busy),
        .done      (done)
    );

    // SHAKE exposes only the 256-bit digest prefix; do not impose an artificial
    // 1,600-bit output parity tree on the isolated core routing experiment.
    assign pin_out = ^state_out[255:0];
endmodule
