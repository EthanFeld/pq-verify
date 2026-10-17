module shake256 #(
    parameter integer RPC = 1
) (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          in_valid,
    output logic          in_ready,
    input  logic [63:0]   in_data,
    input  logic [3:0]    in_bytes,
    input  logic          in_last,
    output logic          out_valid,
    output logic [255:0]  out,
    output logic          permutation_start
);
    localparam logic [4:0] LAST_LANE = 5'd16;
    localparam integer RATE_BYTES = 136;

    typedef enum logic [1:0] {
        ST_ABSORB,
        ST_WAIT_NONFINAL,
        ST_WAIT_FINAL
    } state_t;

    state_t state;
    logic [1599:0] sponge_state;
    logic [1599:0] absorb_result;
    logic [1599:0] perm_state_out;
    logic [1599:0] perm_state_in;
    logic perm_state_load;
    logic [1599:0] empty_pad_state;
    logic [4:0] lane_index;
    logic pending_final_pad;
    logic perm_start;
    logic perm_done;
    logic perm_busy;
    logic [63:0] lane_mask;
    logic [63:0] lane_xor;
    logic [63:0] suffix_mask;
    logic final_partial_block;
    integer byte_index;

    always_comb begin
        lane_mask = '0;
        for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1) begin
            if (byte_index < in_bytes)
                lane_mask[byte_index * 8 +: 8] = 8'hff;
        end
        lane_xor = in_data & lane_mask;
        suffix_mask = 64'h1f << {in_bytes[2:0], 3'b000};
        final_partial_block = in_last
            && !(lane_index == LAST_LANE && in_bytes == 4'd8);

        // Decode the lane once and update fixed slices. A variable write to
        // the complete 1600-bit vector creates large shift/mux networks.
        absorb_result = sponge_state;
        for (integer lane = 0; lane < 17; lane = lane + 1) begin
            if (lane_index == 5'(lane)) begin
                absorb_result[lane * 64 +: 64] =
                    sponge_state[lane * 64 +: 64] ^ lane_xor;
                if (final_partial_block && in_bytes < 4'd8)
                    absorb_result[lane * 64 +: 64] =
                        absorb_result[lane * 64 +: 64] ^ suffix_mask;
            end
            if (lane > 0 && lane_index == 5'(lane - 1)
                    && final_partial_block && in_bytes == 4'd8)
                absorb_result[lane * 64 +: 8] =
                    absorb_result[lane * 64 +: 8] ^ 8'h1f;
        end
        // Padding is XORed into the existing sponge, including after a full
        // block. OR would lose the padding bit when the old state bit is one.
        if (final_partial_block)
            absorb_result[(RATE_BYTES - 1) * 8 + 7] =
                absorb_result[(RATE_BYTES - 1) * 8 + 7] ^ 1'b1;

        empty_pad_state = '0;
        empty_pad_state[7:0] = 8'h1f;
        empty_pad_state[(RATE_BYTES - 1) * 8 +: 8] = 8'h80;

        perm_state_in = sponge_state;
        perm_state_load = 1'b0;
        case (state)
            ST_ABSORB: begin
                if (in_valid && in_ready) begin
                    perm_state_in = absorb_result;
                    perm_state_load = 1'b1;
                end
            end
            ST_WAIT_NONFINAL: begin
                if (perm_done && pending_final_pad) begin
                    perm_state_in = perm_state_out ^ empty_pad_state;
                    perm_state_load = 1'b1;
                end
            end
            ST_WAIT_FINAL: begin
                if (perm_done) begin
                    perm_state_in = '0;
                    perm_state_load = 1'b1;
                end
            end
            default: begin
                perm_state_in = '0;
                perm_state_load = 1'b1;
            end
        endcase
    end

    assign in_ready = (state == ST_ABSORB) && !perm_busy;
    assign sponge_state = perm_state_out;
    assign permutation_start = perm_start;

    keccak_f1600 #(.RPC(RPC), .IN_PLACE(1)) u_keccak (
        .clk       (clk),
        .rst_n     (rst_n),
        .start     (perm_start),
        .state_load(perm_state_load),
        .state_in  (perm_state_in),
        .state_out (perm_state_out),
        .busy      (perm_busy),
        .done      (perm_done)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_ABSORB;
            lane_index <= '0;
            pending_final_pad <= 1'b0;
            perm_start <= 1'b0;
            out <= '0;
            out_valid <= 1'b0;
        end else begin
            perm_start <= 1'b0;
            out_valid <= 1'b0;

            case (state)
                ST_ABSORB: begin
                    if (in_valid && in_ready) begin
                        if (in_last) begin
                            perm_start <= 1'b1;
                            if (lane_index == LAST_LANE && in_bytes == 4'd8) begin
                                pending_final_pad <= 1'b1;
                                state <= ST_WAIT_NONFINAL;
                            end else begin
                                pending_final_pad <= 1'b0;
                                state <= ST_WAIT_FINAL;
                            end
                        end else if (lane_index == LAST_LANE) begin
                            perm_start <= 1'b1;
                            pending_final_pad <= 1'b0;
                            state <= ST_WAIT_NONFINAL;
                        end else begin
                            lane_index <= lane_index + 1'b1;
                        end
                    end
                end

                ST_WAIT_NONFINAL: begin
                    if (perm_done) begin
                        if (pending_final_pad) begin
                            perm_start <= 1'b1;
                            pending_final_pad <= 1'b0;
                            state <= ST_WAIT_FINAL;
                        end else begin
                            lane_index <= '0;
                            state <= ST_ABSORB;
                        end
                    end
                end

                ST_WAIT_FINAL: begin
                    if (perm_done) begin
                        out <= perm_state_out[255:0];
                        out_valid <= 1'b1;
                        lane_index <= '0;
                        pending_final_pad <= 1'b0;
                        state <= ST_ABSORB;
                    end
                end

                default: begin
                    state <= ST_ABSORB;
                    lane_index <= '0;
                    pending_final_pad <= 1'b0;
                end
            endcase
        end
    end
endmodule
