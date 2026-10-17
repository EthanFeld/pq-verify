module thash #(
    parameter integer RPC = 1,
    parameter integer SHARED_SHAKE = 0
) (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          req_valid,
    output logic          req_ready,
    input  logic [1:0]    req_kind,
    input  logic [255:0]  req_adrs,
    input  logic [1:0]    req_src_sel,
    input  logic [15:0]   req_src_addr,
    input  logic [15:0]   req_count,
    input  logic [127:0]  pk_seed,
    input  logic [255:0]  req_pair,
    output logic          src_rd_en,
    output logic [1:0]    src_rd_sel,
    output logic [15:0]   src_rd_addr,
    input  logic          src_valid,
    input  logic [7:0]    src_byte,
    input  logic [31:0]   src_word,
    output logic          shake_in_valid,
    input  logic          shake_in_ready,
    output logic [63:0]   shake_in_data,
    output logic [3:0]    shake_in_bytes,
    output logic          shake_in_last,
    output logic          shake_bulk_valid,
    input  logic          shake_bulk_ready,
    output logic [639:0]  shake_bulk_lanes,
    output logic [6:0]    shake_bulk_bytes,
    input  logic          shake_out_valid,
    input  logic [255:0]  shake_out,
    output logic          rsp_valid,
    output logic [127:0]  rsp_node
);
    localparam logic [15:0] PREFIX_BYTES = 16'd48;

    typedef enum logic [2:0] {
        ST_IDLE,
        ST_FEED,
        ST_READ_SOURCE,
        ST_SEND_LANE,
        ST_SEND_BULK,
        ST_WAIT_HASH
    } state_t;

    state_t state;
    logic [383:0] prefix_shift_reg;
    logic [1:0] src_sel_reg;
    logic [15:0] src_addr_reg;
    logic [255:0] pair_reg;
    logic [15:0] total_bytes;
    logic [15:0] byte_pos;
    logic [15:0] src_issue_pos;
    logic word_source_mode;
    logic [63:0] lane_reg;
    logic [63:0] lane_with_byte;
    logic [63:0] lane_with_word;
    logic [3:0] lane_fill;
    logic [3:0] lane_bytes;
    logic lane_final;
    logic push_valid;
    logic [7:0] push_byte;
    logic engine_in_valid;
    logic engine_in_ready;
    logic [63:0] engine_in_data;
    logic [3:0] engine_in_bytes;
    logic engine_in_last;
    logic engine_bulk_valid;
    logic engine_bulk_ready;
    logic [639:0] engine_bulk_lanes;
    logic [6:0] engine_bulk_bytes;
    logic engine_out_valid;
    logic [255:0] engine_out;
    logic bulk_request;
    logic word_completes_lane;
    logic word_completes_message;

    function automatic logic [63:0] reverse_lane_bytes(input logic [63:0] value);
        begin
            for (integer index = 0; index < 8; index = index + 1)
                reverse_lane_bytes[index * 8 +: 8] = value[63 - index * 8 -: 8];
        end
    endfunction

    function automatic logic [31:0] reverse_word_bytes(input logic [31:0] value);
        begin
            for (integer index = 0; index < 4; index = index + 1)
                reverse_word_bytes[index * 8 +: 8] = value[31 - index * 8 -: 8];
        end
    endfunction

    function automatic logic [383:0] pack_prefix_lanes(input logic [383:0] value);
        begin
            for (integer lane_index = 0; lane_index < 6; lane_index = lane_index + 1)
                pack_prefix_lanes[lane_index * 64 +: 64] =
                    reverse_lane_bytes(value[383 - lane_index * 64 -: 64]);
        end
    endfunction

    function automatic logic [63:0] inline_pair_lane(
        input logic [255:0] value,
        input logic [15:0] byte_offset
    );
        case (byte_offset)
            16'd0:  inline_pair_lane = reverse_lane_bytes(value[255:192]);
            16'd8:  inline_pair_lane = reverse_lane_bytes(value[191:128]);
            16'd16: inline_pair_lane = reverse_lane_bytes(value[127:64]);
            16'd24: inline_pair_lane = reverse_lane_bytes(value[63:0]);
            default: inline_pair_lane = '0;
        endcase
    endfunction

    function automatic logic [15:0] default_message_bytes(
        input logic [1:0] kind
    );
        case (kind)
            2'd0: default_message_bytes = 16'd16;  // F
            2'd1: default_message_bytes = 16'd32;  // H
            2'd2: default_message_bytes = 16'd224; // T_k
            default: default_message_bytes = 16'd560; // T_len
        endcase
    endfunction

    always_comb begin
        // Accept the next WOTS chain step on the output cycle. The response
        // stays valid through the same edge, while its result is used as the
        // next request's inline node.
        req_ready = (state == ST_IDLE)
            || ((state == ST_WAIT_HASH) && engine_out_valid);
        rsp_valid = (state == ST_WAIT_HASH) && engine_out_valid;
        rsp_node = '0;
        for (integer response_byte = 0; response_byte < 16; response_byte = response_byte + 1)
            rsp_node[127 - response_byte * 8 -: 8] = engine_out[response_byte * 8 +: 8];
        word_completes_lane = (lane_fill == 4'd4)
            || (byte_pos + 16'd4 >= total_bytes);
        word_completes_message = (byte_pos + 16'd4 >= total_bytes);
        src_rd_sel = src_sel_reg;
        src_rd_addr = word_source_mode
            ? (src_addr_reg + src_issue_pos)
            : (src_addr_reg + (byte_pos - PREFIX_BYTES));

        src_rd_en = 1'b0;
        if ((state == ST_READ_SOURCE) && (src_sel_reg != 2'd3)) begin
            if (word_source_mode) begin
                if (src_issue_pos < (total_bytes - PREFIX_BYTES)) begin
                    if (!src_valid || !word_completes_lane || engine_in_ready)
                        src_rd_en = 1'b1;
                end
            end else if (!src_valid) begin
                src_rd_en = 1'b1;
            end
        end else if ((state == ST_SEND_LANE) && word_source_mode
                && (byte_pos >= PREFIX_BYTES)
                && engine_in_ready && !lane_final
                && (src_issue_pos < (total_bytes - PREFIX_BYTES))) begin
            // Start the next source word while the just-built sponge lane is
            // accepted, hiding the synchronous RAM's one-cycle read latency.
            src_rd_en = 1'b1;
        end

        push_valid = 1'b0;
        push_byte = 8'h00;
        if (state == ST_READ_SOURCE) begin
            if (src_sel_reg == 2'd3) begin
                push_valid = 1'b1;
                push_byte = pair_reg[255 - (byte_pos - PREFIX_BYTES) * 8 -: 8];
            end else if (src_valid && !word_source_mode) begin
                push_valid = 1'b1;
                push_byte = src_byte;
            end
        end

        lane_with_byte = lane_reg;
        if (push_valid)
            lane_with_byte[lane_fill * 8 +: 8] = push_byte;

        lane_with_word = lane_reg;
        if (src_valid && word_source_mode)
            lane_with_word[lane_fill * 8 +: 32] = reverse_word_bytes(src_word);

        engine_in_valid = (state == ST_SEND_LANE)
            || ((state == ST_READ_SOURCE) && word_source_mode && src_valid
                && word_completes_lane);
        engine_in_data = ((state == ST_READ_SOURCE) && word_source_mode
                && src_valid && word_completes_lane) ? lane_with_word : lane_reg;
        engine_in_bytes = ((state == ST_READ_SOURCE) && word_source_mode
                && src_valid && word_completes_lane) ? (lane_fill + 4'd4) : lane_bytes;
        engine_in_last = ((state == ST_READ_SOURCE) && word_source_mode
                && src_valid && word_completes_lane) ? word_completes_message : lane_final;

        bulk_request = (req_src_sel == 2'd3)
            && (((req_kind == 2'd0) && (req_count == 0 || req_count == 16))
                || ((req_kind == 2'd1) && (req_count == 0 || req_count == 32)));
        engine_bulk_valid = (state == ST_SEND_BULK);
        engine_bulk_lanes = '0;
        engine_bulk_bytes = total_bytes[6:0];
        for (integer bulk_lane = 0; bulk_lane < 6; bulk_lane = bulk_lane + 1)
            engine_bulk_lanes[bulk_lane * 64 +: 64] =
                prefix_shift_reg[bulk_lane * 64 +: 64];
        for (integer bulk_lane = 6; bulk_lane < 10; bulk_lane = bulk_lane + 1) begin
            if (bulk_lane * 8 < total_bytes)
                engine_bulk_lanes[bulk_lane * 64 +: 64] =
                    inline_pair_lane(pair_reg, 16'((bulk_lane - 6) * 8));
        end
    end

    assign shake_in_valid = engine_in_valid;
    assign shake_in_data = engine_in_data;
    assign shake_in_bytes = engine_in_bytes;
    assign shake_in_last = engine_in_last;
    assign shake_bulk_valid = engine_bulk_valid;
    assign shake_bulk_lanes = engine_bulk_lanes;
    assign shake_bulk_bytes = engine_bulk_bytes;

    generate
        if (SHARED_SHAKE == 0) begin : G_LOCAL_SHAKE
            logic unused_permutation_start;
            shake256 #(.RPC(RPC)) u_shake256 (
                .clk       (clk),
                .rst_n     (rst_n),
                .in_valid  (engine_in_valid),
                .in_ready  (engine_in_ready),
                .in_data   (engine_in_data),
                .in_bytes  (engine_in_bytes),
                .in_last   (engine_in_last),
                .bulk_valid(engine_bulk_valid),
                .bulk_ready(engine_bulk_ready),
                .bulk_lanes(engine_bulk_lanes),
                .bulk_bytes(engine_bulk_bytes),
                .out_valid (engine_out_valid),
                .out       (engine_out),
                .permutation_start(unused_permutation_start)
            );
        end else begin : G_SHARED_SHAKE
            assign engine_in_ready = shake_in_ready;
            assign engine_bulk_ready = shake_bulk_ready;
            assign engine_out_valid = shake_out_valid;
            assign engine_out = shake_out;
        end
    endgenerate

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            prefix_shift_reg <= '0;
            src_sel_reg <= '0;
            src_addr_reg <= '0;
            pair_reg <= '0;
            total_bytes <= '0;
            byte_pos <= '0;
            src_issue_pos <= '0;
            word_source_mode <= 1'b0;
            lane_reg <= '0;
            lane_fill <= '0;
            lane_bytes <= '0;
            lane_final <= 1'b0;
        end else begin
            if (word_source_mode && src_rd_en)
                src_issue_pos <= src_issue_pos + 16'd4;

            case (state)
                ST_IDLE: begin
                    if (req_valid && req_ready) begin
                        prefix_shift_reg <= pack_prefix_lanes({pk_seed, req_adrs});
                        src_sel_reg <= req_src_sel;
                        src_addr_reg <= req_src_addr;
                        pair_reg <= req_pair;
                        src_issue_pos <= '0;
                        word_source_mode <= (req_src_sel != 2'd3)
                            && (req_src_addr[1:0] == 2'b00)
                            && (req_count[2:0] == 3'b000);
                        total_bytes <= PREFIX_BYTES + ((req_count == 0)
                            ? default_message_bytes(req_kind) : req_count);
                        byte_pos <= '0;
                        lane_reg <= '0;
                        lane_fill <= '0;
                        lane_bytes <= '0;
                        lane_final <= 1'b0;
                        if (bulk_request)
                            state <= ST_SEND_BULK;
                        else
                            state <= ST_FEED;
                    end
                end

                ST_FEED: begin
                    if (byte_pos < PREFIX_BYTES) begin
                        lane_reg <= prefix_shift_reg[63:0];
                        prefix_shift_reg <= prefix_shift_reg >> 64;
                        byte_pos <= byte_pos + 16'd8;
                        lane_bytes <= 4'd8;
                        lane_final <= (byte_pos + 16'd8 == total_bytes);
                        lane_fill <= '0;
                        state <= ST_SEND_LANE;
                    end else if (src_sel_reg == 2'd3
                            && byte_pos[2:0] == 3'd0
                            && (byte_pos - PREFIX_BYTES) < 16'd32
                            && (total_bytes - byte_pos) >= 16'd8) begin
                        // Inline F/H inputs already reside in pair_reg. Pack
                        // each full source lane instead of serializing bytes
                        // through ST_READ_SOURCE and ST_FEED.
                        lane_reg <= inline_pair_lane(pair_reg, byte_pos - PREFIX_BYTES);
                        byte_pos <= byte_pos + 16'd8;
                        lane_bytes <= 4'd8;
                        lane_final <= (byte_pos + 16'd8 == total_bytes);
                        lane_fill <= '0;
                        state <= ST_SEND_LANE;
                    end else if (byte_pos < total_bytes) begin
                        state <= ST_READ_SOURCE;
                    end
                end

                ST_READ_SOURCE: begin
                    if (word_source_mode && src_valid) begin
                        lane_reg <= lane_with_word;
                        byte_pos <= byte_pos + 16'd4;
                        if (word_completes_lane) begin
                            lane_bytes <= lane_fill + 4'd4;
                            lane_final <= word_completes_message;
                            lane_fill <= '0;
                            if (engine_in_ready) begin
                                lane_reg <= '0;
                                lane_bytes <= '0;
                                lane_final <= 1'b0;
                                if (word_completes_message)
                                    state <= ST_WAIT_HASH;
                            end else begin
                                state <= ST_SEND_LANE;
                            end
                        end else begin
                            lane_fill <= lane_fill + 4'd4;
                        end
                    end else if (push_valid) begin
                        lane_reg <= lane_with_byte;
                        byte_pos <= byte_pos + 1'b1;
                        if (lane_fill == 4'd7 || byte_pos + 1'b1 == total_bytes) begin
                            lane_bytes <= lane_fill + 1'b1;
                            lane_final <= (byte_pos + 1'b1 == total_bytes);
                            lane_fill <= '0;
                            state <= ST_SEND_LANE;
                        end else begin
                            lane_fill <= lane_fill + 1'b1;
                            state <= ST_FEED;
                        end
                    end
                end

                ST_SEND_LANE: begin
                    if (engine_in_valid && engine_in_ready) begin
                        lane_reg <= '0;
                        lane_bytes <= '0;
                        if (lane_final) begin
                            state <= ST_WAIT_HASH;
                        end else if (word_source_mode && (byte_pos >= PREFIX_BYTES)) begin
                            state <= ST_READ_SOURCE;
                        end else begin
                            lane_final <= 1'b0;
                            state <= ST_FEED;
                        end
                    end
                end

                ST_SEND_BULK: begin
                    if (engine_bulk_valid && engine_bulk_ready)
                        state <= ST_WAIT_HASH;
                end

                ST_WAIT_HASH: begin
                    if (engine_out_valid) begin
                        if (req_valid && req_ready) begin
                            prefix_shift_reg <= pack_prefix_lanes({pk_seed, req_adrs});
                            src_sel_reg <= req_src_sel;
                            src_addr_reg <= req_src_addr;
                            pair_reg <= req_pair;
                            total_bytes <= PREFIX_BYTES + ((req_count == 0)
                                ? default_message_bytes(req_kind) : req_count);
                            byte_pos <= '0;
                            lane_reg <= '0;
                            lane_fill <= '0;
                            lane_bytes <= '0;
                            lane_final <= 1'b0;
                            if (bulk_request)
                                state <= ST_SEND_BULK;
                            else
                                state <= ST_FEED;
                        end else begin
                            state <= ST_IDLE;
                        end
                    end
                end

                default: begin
                    state <= ST_IDLE;
                    lane_reg <= '0;
                    lane_fill <= '0;
                    lane_bytes <= '0;
                    lane_final <= 1'b0;
                end
            endcase
        end
    end
endmodule
