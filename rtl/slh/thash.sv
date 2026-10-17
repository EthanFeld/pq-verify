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
    output logic          shake_in_valid,
    input  logic          shake_in_ready,
    output logic [63:0]   shake_in_data,
    output logic [3:0]    shake_in_bytes,
    output logic          shake_in_last,
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
        ST_WAIT_HASH
    } state_t;

    state_t state;
    logic [383:0] prefix_shift_reg;
    logic [1:0] src_sel_reg;
    logic [15:0] src_addr_reg;
    logic [255:0] pair_reg;
    logic [15:0] total_bytes;
    logic [15:0] byte_pos;
    logic [63:0] lane_reg;
    logic [63:0] lane_with_byte;
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
    logic engine_out_valid;
    logic [255:0] engine_out;

    function automatic logic [63:0] reverse_lane_bytes(input logic [63:0] value);
        begin
            for (integer index = 0; index < 8; index = index + 1)
                reverse_lane_bytes[index * 8 +: 8] = value[63 - index * 8 -: 8];
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
        req_ready = (state == ST_IDLE);
        src_rd_en = (state == ST_READ_SOURCE) && !src_valid && (src_sel_reg != 2'd3);
        src_rd_sel = src_sel_reg;
        src_rd_addr = src_addr_reg + (byte_pos - PREFIX_BYTES);

        push_valid = 1'b0;
        push_byte = 8'h00;
        if (state == ST_READ_SOURCE) begin
            if (src_sel_reg == 2'd3) begin
                push_valid = 1'b1;
                push_byte = pair_reg[255 - (byte_pos - PREFIX_BYTES) * 8 -: 8];
            end else if (src_valid) begin
                push_valid = 1'b1;
                push_byte = src_byte;
            end
        end

        lane_with_byte = lane_reg;
        if (push_valid)
            lane_with_byte[lane_fill * 8 +: 8] = push_byte;

        engine_in_valid = (state == ST_SEND_LANE);
        engine_in_data = lane_reg;
        engine_in_bytes = lane_bytes;
        engine_in_last = lane_final;
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
            prefix_shift_reg <= '0;
            src_sel_reg <= '0;
            src_addr_reg <= '0;
            pair_reg <= '0;
            total_bytes <= '0;
            byte_pos <= '0;
            lane_reg <= '0;
            lane_fill <= '0;
            lane_bytes <= '0;
            lane_final <= 1'b0;
            rsp_valid <= 1'b0;
            rsp_node <= '0;
        end else begin
            rsp_valid <= 1'b0;

            case (state)
                ST_IDLE: begin
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
                    if (push_valid) begin
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
                        end else begin
                            lane_final <= 1'b0;
                            state <= ST_FEED;
                        end
                    end
                end

                ST_WAIT_HASH: begin
                    if (engine_out_valid) begin
                        for (integer byte_index = 0; byte_index < 16; byte_index = byte_index + 1)
                            rsp_node[127 - byte_index * 8 -: 8] <= engine_out[byte_index * 8 +: 8];
                        rsp_valid <= 1'b1;
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
