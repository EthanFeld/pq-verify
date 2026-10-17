module keccak_f1600 #(
    parameter integer RPC = 1,
    parameter integer IN_PLACE = 0,
    parameter integer LUT4_MAP = (RPC > 1) ? 1 : 0
`ifdef FORMAL
    , parameter integer FORMAL_CONTROL_ONLY = 0
`endif
) (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          start,
    input  logic          state_load,
    input  logic [1599:0] state_in,
    output logic [1599:0] state_out,
    output logic          busy,
    output logic          done
`ifdef FORMAL
    , output logic [5:0]   formal_round_base
`endif
);
    logic [1599:0] state_reg;
    localparam logic [5:0] RPC_COUNT = 6'(RPC);
    logic [5:0] round_base;
    logic [1599:0] round_chain [0:RPC];
`ifdef FORMAL
    localparam integer CONTROL_ONLY = FORMAL_CONTROL_ONLY;
`else
    localparam integer CONTROL_ONLY = 0;
`endif

    assign round_chain[0] = state_reg;
    // The result is valid with done. In-place clients also use this register
    // bank for absorption, so no separate 1600-bit result bank is needed.
    assign state_out = state_reg;
`ifdef FORMAL
    assign formal_round_base = round_base;
`endif

    generate
        if (CONTROL_ONLY != 0) begin : G_FORMAL_CONTROL_ONLY
            // Abstract state data to keep this control proof independent of
            // the 1600-bit Keccak datapath; separate targets prove its data.
            for (genvar round = 0; round < RPC; round = round + 1) begin : G_PASS
                assign round_chain[round + 1] = round_chain[round];
            end
        end else begin : G_ROUND
            for (genvar round = 0; round < RPC; round = round + 1) begin : G_INSTANCE
                localparam logic [4:0] ROUND_OFFSET = 5'(round);
                logic [4:0] round_index;
                assign round_index = round_base[4:0] + ROUND_OFFSET;
                keccak_round #(.LUT4_MAP(LUT4_MAP)) u_round (
                    .state_in  (round_chain[round]),
                    .round_idx (round_index),
                    .state_out (round_chain[round + 1])
                );
            end
        end
    endgenerate

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_reg <= '0;
            round_base <= '0;
            busy <= 1'b0;
            done <= 1'b0;
        end else begin
            done <= 1'b0;
            if (busy) begin
                state_reg <= round_chain[RPC];
                if (round_base + RPC_COUNT >= 6'd24) begin
                    busy <= 1'b0;
                    done <= 1'b1;
                end else begin
                    round_base <= round_base + RPC_COUNT;
                end
            end else if (start) begin
                if (IN_PLACE == 0)
                    state_reg <= state_in;
                round_base <= '0;
                busy <= 1'b1;
            end else if (IN_PLACE != 0 && state_load) begin
                state_reg <= state_in;
            end
        end
    end

`ifdef FORMAL
    always @(posedge clk) begin
        if (rst_n)
            assert (round_base < 6'd24);
    end
`endif
endmodule
