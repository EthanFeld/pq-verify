module keccak_round_chain #(
    parameter integer RPC = 1,
    parameter integer LUT4_MAP = 0,
    parameter integer NATIVE_LUT4 = 0
) (
    input logic [1599:0] state_in,
    input logic [4:0] round_base,
    output logic [1599:0] state_out
);
    logic [1599:0] states [0:RPC];
    assign states[0] = state_in;

    for (genvar round = 0; round < RPC; round = round + 1) begin : G_ROUND
        logic [4:0] round_idx;
        assign round_idx = round_base + 5'(round);
        keccak_round #(
            .LUT4_MAP(LUT4_MAP),
            .NATIVE_LUT4(NATIVE_LUT4)
        ) u_round (
            .state_in(states[round]),
            .round_idx(round_idx),
            .state_out(states[round + 1])
        );
    end

    assign state_out = states[RPC];
endmodule

module fv_keccak_round_equiv #(
    parameter integer RPC = 1,
    parameter integer NATIVE_CHECK = 0
);
    (* gclk *) reg formal_timestep;
    (* anyconst *) reg [1599:0] state_in;
    (* anyconst *) reg [4:0] round_base;
    wire [1599:0] state_a;
    wire [1599:0] state_b;

    generate
        if (NATIVE_CHECK == 0) begin : G_MAP_EQUIV
            keccak_round_chain #(.RPC(RPC), .LUT4_MAP(0)) generic_map (
                .state_in(state_in), .round_base(round_base), .state_out(state_a)
            );
            keccak_round_chain #(.RPC(RPC), .LUT4_MAP(1), .NATIVE_LUT4(0)) lut4_map (
                .state_in(state_in), .round_base(round_base), .state_out(state_b)
            );
        end else begin : G_NATIVE_EQUIV
            keccak_round_chain #(.RPC(RPC), .LUT4_MAP(1), .NATIVE_LUT4(0)) portable (
                .state_in(state_in), .round_base(round_base), .state_out(state_a)
            );
            keccak_round_chain #(.RPC(RPC), .LUT4_MAP(1), .NATIVE_LUT4(1)) native (
                .state_in(state_in), .round_base(round_base), .state_out(state_b)
            );
        end
    endgenerate

    always @(posedge formal_timestep) begin
        assume (round_base <= 5'(24 - RPC));
        assert (state_a == state_b);
        cover (round_base == 5'(24 - RPC));
    end
endmodule
