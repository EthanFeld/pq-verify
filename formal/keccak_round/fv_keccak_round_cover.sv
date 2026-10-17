module fv_keccak_round_cover #(
    parameter integer RPC = 1
);
    (* gclk *) reg formal_timestep;
    (* anyconst *) reg [4:0] round_base;

    always @(posedge formal_timestep) begin
        assume (round_base <= 5'(24 - RPC));
        cover (round_base == 5'(24 - RPC));
    end
endmodule
