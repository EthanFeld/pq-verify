module hmsg #(
    parameter integer RPC = 1,
    parameter integer SHARED_SHAKE = 0
) (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          start,
    output logic          start_ready,
    input  logic          pure_mode,
    input  logic [7:0]    ctx_len,
    input  logic [127:0]  randomizer,
    input  logic [127:0]  pk_seed,
    input  logic [127:0]  pk_root,
    input  logic          ctx_valid,
    output logic          ctx_ready,
    input  logic [7:0]    ctx_byte,
    input  logic          msg_valid,
    output logic          msg_ready,
    input  logic [7:0]    msg_byte,
    input  logic          msg_last,
    output logic          shake_in_valid,
    input  logic          shake_in_ready,
    output logic [63:0]   shake_in_data,
    output logic [3:0]    shake_in_bytes,
    output logic          shake_in_last,
    input  logic          shake_out_valid,
    input  logic [255:0]  shake_out,
    output logic          done,
    output logic [13:0][11:0] md_idx,
    output logic [53:0]   idx_tree,
    output logic [8:0]    idx_leaf
);
    typedef enum logic [2:0] {
        ST_IDLE,
        ST_PREFIX,
        ST_CONTEXT,
        ST_MESSAGE,
        ST_SEND_LANE,
        ST_WAIT_HASH
    } state_t;

    state_t state;
    state_t resume_state;
    logic pure_reg;
    logic [7:0] context_length;
    logic [7:0] context_count;
    logic [5:0] prefix_pos;
    logic [5:0] prefix_total;
    logic [383:0] header_reg;
    logic [63:0] lane_reg;
    logic [63:0] lane_with_byte;
    logic [3:0] lane_fill;
    logic [3:0] lane_bytes;
    logic lane_final;
    logic push_valid;
    logic [7:0] push_byte;
    logic push_last;
    logic message_end_event;
    state_t next_input_state;
    logic [255:0] digest;
    logic [167:0] md_bits;
    logic engine_in_valid;
    logic engine_in_ready;
    logic [63:0] engine_in_data;
    logic [3:0] engine_in_bytes;
    logic engine_in_last;
    logic engine_out_valid;
    logic [255:0] engine_out;

    function automatic logic [63:0] reverse_lane_bytes(input logic [63:0] value);
        begin
            for (integer index = 0; index < 8; index = index + 1)
                reverse_lane_bytes[index * 8 +: 8] = value[63 - index * 8 -: 8];
        end
    endfunction

    function automatic logic [383:0] pack_header_lanes(input logic [383:0] value);
        begin
            for (integer lane_index = 0; lane_index < 6; lane_index = lane_index + 1)
                pack_header_lanes[lane_index * 64 +: 64] =
                    reverse_lane_bytes(value[383 - lane_index * 64 -: 64]);
        end
    endfunction

    always_comb begin
        start_ready = (state == ST_IDLE);
        ctx_ready = (state == ST_CONTEXT);
        msg_ready = (state == ST_MESSAGE);

        push_valid = 1'b0;
        push_byte = 8'h00;
        push_last = 1'b0;
        next_input_state = state;
        if (state == ST_PREFIX) begin
            if (prefix_pos < 6'd48) begin
                if (prefix_pos == 6'd40 && !pure_reg)
                    next_input_state = ST_MESSAGE;
                else
                    next_input_state = ST_PREFIX;
            end else begin
                push_valid = 1'b1;
                if (prefix_pos == 6'd48)
                    push_byte = 8'h00;
                else
                    push_byte = context_length;

                if (prefix_pos + 1'b1 == prefix_total) begin
                    if (pure_reg && context_length != 0)
                        next_input_state = ST_CONTEXT;
                    else
                        next_input_state = ST_MESSAGE;
                end else begin
                    next_input_state = ST_PREFIX;
                end
            end
        end else if (state == ST_CONTEXT && ctx_valid) begin
            push_valid = 1'b1;
            push_byte = ctx_byte;
            if (context_count + 1'b1 == context_length)
                next_input_state = ST_MESSAGE;
            else
                next_input_state = ST_CONTEXT;
        end else if (state == ST_MESSAGE && msg_valid) begin
            push_valid = 1'b1;
            push_byte = msg_byte;
            push_last = msg_last;
            next_input_state = ST_MESSAGE;
        end

        message_end_event = (state == ST_MESSAGE) && msg_ready && msg_last && !msg_valid;
        lane_with_byte = lane_reg;
        if (push_valid)
            lane_with_byte[lane_fill * 8 +: 8] = push_byte;

        engine_in_valid = (state == ST_SEND_LANE);
        engine_in_data = lane_reg;
        engine_in_bytes = lane_bytes;
        engine_in_last = lane_final;

        md_bits = '0;
        for (integer md_byte = 0; md_byte < 21; md_byte = md_byte + 1)
            md_bits[167 - md_byte * 8 -: 8] = digest[md_byte * 8 +: 8];
        for (integer idx = 0; idx < 14; idx = idx + 1)
            md_idx[idx] = md_bits[167 - idx * 12 -: 12];
        idx_tree = {
            digest[21 * 8 +: 6],
            digest[22 * 8 +: 8], digest[23 * 8 +: 8],
            digest[24 * 8 +: 8], digest[25 * 8 +: 8],
            digest[26 * 8 +: 8], digest[27 * 8 +: 8]
        };
        idx_leaf = {digest[28 * 8 +: 1], digest[29 * 8 +: 8]};
    end

    assign shake_in_valid = engine_in_valid;
    assign shake_in_data = engine_in_data;
    assign shake_in_bytes = engine_in_bytes;
    assign shake_in_last = engine_in_last;

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
                .out_valid (engine_out_valid),
                .out       (engine_out),
                .permutation_start(unused_permutation_start)
            );
        end else begin : G_SHARED_SHAKE
            assign engine_in_ready = shake_in_ready;
            assign engine_out_valid = shake_out_valid;
            assign engine_out = shake_out;
        end
    endgenerate

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            resume_state <= ST_IDLE;
            pure_reg <= 1'b0;
            context_length <= '0;
            context_count <= '0;
            prefix_pos <= '0;
            prefix_total <= '0;
            header_reg <= '0;
            lane_reg <= '0;
            lane_fill <= '0;
            lane_bytes <= '0;
            lane_final <= 1'b0;
            digest <= '0;
            done <= 1'b0;
        end else begin
            done <= 1'b0;

            case (state)
                ST_IDLE: begin
                    if (start && start_ready) begin
                        pure_reg <= pure_mode;
                        context_length <= ctx_len;
                        context_count <= '0;
                        prefix_pos <= '0;
                        prefix_total <= pure_mode ? 6'd50 : 6'd48;
                        header_reg <= pack_header_lanes({randomizer, pk_seed, pk_root});
                        lane_reg <= '0;
                        lane_fill <= '0;
                        lane_bytes <= '0;
                        lane_final <= 1'b0;
                        state <= ST_PREFIX;
                    end
                end

                ST_PREFIX: begin
                    if (prefix_pos < 6'd48) begin
                        lane_reg <= header_reg[63:0];
                        header_reg <= header_reg >> 64;
                        prefix_pos <= prefix_pos + 6'd8;
                        lane_bytes <= 4'd8;
                        lane_final <= 1'b0;
                        lane_fill <= '0;
                        // Every mode needs all six R || PK.seed || PK.root
                        // lanes before message/domain bytes are accepted.
                        resume_state <= next_input_state;
                        state <= ST_SEND_LANE;
                    end else if (push_valid) begin
                        lane_reg <= lane_with_byte;
                        prefix_pos <= prefix_pos + 1'b1;
                        if (lane_fill == 4'd7) begin
                            lane_bytes <= 4'd8;
                            lane_final <= 1'b0;
                            lane_fill <= '0;
                            resume_state <= next_input_state;
                            state <= ST_SEND_LANE;
                        end else begin
                            lane_fill <= lane_fill + 1'b1;
                            state <= next_input_state;
                        end
                    end
                end

                ST_CONTEXT: begin
                    if (ctx_valid && ctx_ready) begin
                        lane_reg <= lane_with_byte;
                        context_count <= context_count + 1'b1;
                        if (lane_fill == 4'd7) begin
                            lane_bytes <= 4'd8;
                            lane_final <= 1'b0;
                            lane_fill <= '0;
                            resume_state <= next_input_state;
                            state <= ST_SEND_LANE;
                        end else begin
                            lane_fill <= lane_fill + 1'b1;
                            state <= next_input_state;
                        end
                    end
                end

                ST_MESSAGE: begin
                    if (msg_valid && msg_ready) begin
                        lane_reg <= lane_with_byte;
                        if (lane_fill == 4'd7 || push_last) begin
                            lane_bytes <= lane_fill + 1'b1;
                            lane_final <= push_last;
                            lane_fill <= '0;
                            resume_state <= ST_MESSAGE;
                            state <= ST_SEND_LANE;
                        end else begin
                            lane_fill <= lane_fill + 1'b1;
                        end
                    end else if (message_end_event) begin
                        lane_bytes <= lane_fill;
                        lane_final <= 1'b1;
                        if (lane_fill == 0)
                            lane_reg <= '0;
                        lane_fill <= '0;
                        state <= ST_SEND_LANE;
                    end
                end

                ST_SEND_LANE: begin
                    if (engine_in_valid && engine_in_ready) begin
                        lane_reg <= '0;
                        lane_bytes <= '0;
                        if (lane_final) begin
                            state <= ST_WAIT_HASH;
                        end else begin
                            lane_final <= 1'b0;
                            state <= resume_state;
                        end
                    end
                end

                ST_WAIT_HASH: begin
                    if (engine_out_valid) begin
                        digest <= engine_out;
                        done <= 1'b1;
                        state <= ST_IDLE;
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
