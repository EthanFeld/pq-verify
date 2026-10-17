module wots_verify (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          start,
    output logic          start_ready,
    input  logic [127:0]  message,
    input  logic [31:0]   layer,
    input  logic [95:0]   tree,
    input  logic [31:0]   keypair,
    input  logic [15:0]   sig_base,
    input  logic [127:0]  pk_seed,
    output logic          sig_rd_en,
    output logic [15:0]   sig_rd_addr,
    input  logic          sig_valid,
    input  logic [7:0]    sig_byte,
    output logic          scratch_wr_en,
    output logic [7:0]    scratch_wr_addr,
    output logic [31:0]   scratch_wr_data,
    output logic          hash_req_valid,
    input  logic          hash_req_ready,
    output logic [1:0]    hash_kind,
    output logic [255:0]  hash_adrs,
    output logic [1:0]    hash_src_sel,
    output logic [15:0]   hash_src_addr,
    output logic [15:0]   hash_count,
    output logic [255:0]  hash_pair,
    output logic [127:0]  hash_pk_seed,
    input  logic          hash_rsp_valid,
    input  logic [127:0]  hash_rsp_node,
    output logic          done,
    output logic [127:0]  wots_pk
);
    localparam logic [15:0] NODE_BYTES = 16'd16;

    typedef enum logic [3:0] {
        ST_IDLE,
        ST_SIG_REQUEST,
        ST_SIG_WAIT,
        ST_HASH_REQUEST,
        ST_HASH_WAIT,
        ST_CHAIN_WRITE,
        ST_TLEN_REQUEST,
        ST_TLEN_WAIT
    } state_t;

    state_t state;
    logic [127:0] message_reg;
    logic [127:0] chain_node;
    logic [31:0] layer_reg;
    logic [95:0] tree_reg;
    logic [31:0] keypair_reg;
    logic [15:0] sig_base_reg;
    logic [127:0] seed_reg;
    logic [5:0] chain_number;
    logic [3:0] byte_index;
    logic [3:0] chain_digit;
    logic [3:0] hash_index;
    logic [1:0] word_index;
    logic [11:0] checksum_value;
    logic [8:0] checksum_sum;
    logic [8:0] checksum_terms [0:31];
    logic [8:0] checksum_level1 [0:15];
    logic [8:0] checksum_level2 [0:7];
    logic [8:0] checksum_level3 [0:3];
    logic [8:0] checksum_level4 [0:1];
    logic [31:0] chain_word;
    logic [31:0] hash_word;
    logic [31:0] type_word;
    logic [31:0] index_word;
    logic [4:0] prefetch_issue_count;
    logic [4:0] prefetch_capture_count;
    logic [5:0] prefetch_chain_number;
    logic [127:0] prefetch_sig;
    logic prefetch_issue_done;
    logic prefetch_capture_pending;
    logic prefetch_valid;
    logic prefetch_hit;
    logic prefetch_sig_rd_en;
    logic [15:0] prefetch_sig_rd_addr;

    always_comb begin
        for (integer digit_index = 0; digit_index < 32; digit_index = digit_index + 1)
            checksum_terms[digit_index] = {5'd0, ~message_reg[127 - digit_index * 4 -: 4]};
        for (integer pair_index = 0; pair_index < 16; pair_index = pair_index + 1)
            checksum_level1[pair_index] = checksum_terms[2 * pair_index]
                + checksum_terms[2 * pair_index + 1];
        for (integer pair_index = 0; pair_index < 8; pair_index = pair_index + 1)
            checksum_level2[pair_index] = checksum_level1[2 * pair_index]
                + checksum_level1[2 * pair_index + 1];
        for (integer pair_index = 0; pair_index < 4; pair_index = pair_index + 1)
            checksum_level3[pair_index] = checksum_level2[2 * pair_index]
                + checksum_level2[2 * pair_index + 1];
        for (integer pair_index = 0; pair_index < 2; pair_index = pair_index + 1)
            checksum_level4[pair_index] = checksum_level3[2 * pair_index]
                + checksum_level3[2 * pair_index + 1];
        checksum_sum = checksum_level4[0] + checksum_level4[1];
        checksum_value = {3'b000, checksum_sum};

        if (chain_number < 6'd32)
            chain_digit = message_reg[127 - chain_number * 4 -: 4];
        else if (chain_number == 6'd32)
            chain_digit = checksum_value[11:8];
        else if (chain_number == 6'd33)
            chain_digit = checksum_value[7:4];
        else
            chain_digit = checksum_value[3:0];

        start_ready = (state == ST_IDLE);
        prefetch_hit = prefetch_valid && (prefetch_chain_number == chain_number);
        prefetch_sig_rd_en = (state == ST_HASH_WAIT) && (hash_index == 4'd14)
            && (chain_number < 6'd34) && !prefetch_issue_done;
        prefetch_sig_rd_addr = sig_base_reg + ({10'd0, chain_number} + 16'd1) * NODE_BYTES
            + {12'd0, prefetch_issue_count[3:0]};
        sig_rd_en = ((state == ST_SIG_REQUEST) && !prefetch_hit) || prefetch_sig_rd_en;
        if (prefetch_sig_rd_en)
            sig_rd_addr = prefetch_sig_rd_addr;
        else
            sig_rd_addr = sig_base_reg + chain_number * NODE_BYTES
                + {12'd0, byte_index};

        scratch_wr_en = (state == ST_CHAIN_WRITE);
        scratch_wr_addr = {chain_number, 2'b00} + {6'd0, word_index};
        scratch_wr_data = chain_node[127 - word_index * 32 -: 32];

        hash_req_valid = (state == ST_HASH_REQUEST) || (state == ST_TLEN_REQUEST);
        hash_kind = 2'd0;
        hash_src_sel = 2'd3;
        hash_src_addr = 16'd0;
        hash_count = 16'd16;
        hash_pair = {chain_node, 128'd0};
        type_word = 32'd0; // WOTS hash chain
        chain_word = {26'd0, chain_number};
        hash_word = {28'd0, hash_index};
        index_word = 32'd0;

        if (state == ST_TLEN_REQUEST || state == ST_TLEN_WAIT) begin
            hash_kind = 2'd3;
            hash_src_sel = 2'd1; // chain ends in scratch RAM
            hash_src_addr = 16'd0;
            hash_count = 16'd560;
            type_word = 32'd1; // WOTS public key
            chain_word = 32'd0;
            hash_word = 32'd0;
        end

        hash_adrs = {
            layer_reg, tree_reg, type_word, keypair_reg,
            chain_word, index_word | hash_word
        };
        hash_pk_seed = seed_reg;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            message_reg <= '0;
            chain_node <= '0;
            layer_reg <= '0;
            tree_reg <= '0;
            keypair_reg <= '0;
            sig_base_reg <= '0;
            seed_reg <= '0;
            chain_number <= '0;
            byte_index <= '0;
            hash_index <= '0;
            word_index <= '0;
            prefetch_issue_count <= '0;
            prefetch_capture_count <= '0;
            prefetch_chain_number <= '0;
            prefetch_sig <= '0;
            prefetch_issue_done <= 1'b0;
            prefetch_capture_pending <= 1'b0;
            prefetch_valid <= 1'b0;
            done <= 1'b0;
            wots_pk <= '0;
        end else begin
            done <= 1'b0;
            prefetch_capture_pending <= prefetch_sig_rd_en;

            if (prefetch_sig_rd_en) begin
                if (prefetch_issue_count == 5'd0)
                    prefetch_chain_number <= chain_number + 6'd1;
                prefetch_issue_count <= prefetch_issue_count + 1'b1;
                if (prefetch_issue_count == 5'd15)
                    prefetch_issue_done <= 1'b1;
            end

            if (prefetch_capture_pending && sig_valid) begin
                prefetch_sig[127 - prefetch_capture_count * 8 -: 8] <= sig_byte;
                prefetch_capture_count <= prefetch_capture_count + 1'b1;
                if (prefetch_capture_count == 5'd15)
                    prefetch_valid <= 1'b1;
            end

            case (state)
                ST_IDLE: begin
                    if (start && start_ready) begin
                        message_reg <= message;
                        layer_reg <= layer;
                        tree_reg <= tree;
                        keypair_reg <= keypair;
                        sig_base_reg <= sig_base;
                        seed_reg <= pk_seed;
                        chain_number <= '0;
                        byte_index <= '0;
                        word_index <= '0;
                        prefetch_issue_count <= '0;
                        prefetch_capture_count <= '0;
                        prefetch_issue_done <= 1'b0;
                        prefetch_valid <= 1'b0;
                        state <= ST_SIG_REQUEST;
                    end
                end

                ST_SIG_REQUEST: begin
                    if (prefetch_hit) begin
                        chain_node[127 - byte_index * 8 -: 8]
                            <= prefetch_sig[127 - byte_index * 8 -: 8];
                        if (byte_index == 4'd15) begin
                            byte_index <= '0;
                            prefetch_issue_count <= '0;
                            prefetch_capture_count <= '0;
                            prefetch_issue_done <= 1'b0;
                            prefetch_valid <= 1'b0;
                            if (chain_digit == 4'd15) begin
                                word_index <= '0;
                                state <= ST_CHAIN_WRITE;
                            end else begin
                                hash_index <= chain_digit;
                                state <= ST_HASH_REQUEST;
                            end
                        end else begin
                            byte_index <= byte_index + 1'b1;
                        end
                    end else begin
                        state <= ST_SIG_WAIT;
                    end
                end

                ST_SIG_WAIT: begin
                    if (sig_valid) begin
                        chain_node[127 - byte_index * 8 -: 8] <= sig_byte;
                        if (byte_index == 4'd15) begin
                            byte_index <= '0;
                            prefetch_issue_count <= '0;
                            prefetch_capture_count <= '0;
                            prefetch_issue_done <= 1'b0;
                            prefetch_valid <= 1'b0;
                            if (chain_digit == 4'd15) begin
                                word_index <= '0;
                                state <= ST_CHAIN_WRITE;
                            end else begin
                                hash_index <= chain_digit;
                                state <= ST_HASH_REQUEST;
                            end
                        end else begin
                            byte_index <= byte_index + 1'b1;
                            state <= ST_SIG_REQUEST;
                        end
                    end
                end

                ST_HASH_REQUEST: begin
                    if (hash_req_valid && hash_req_ready)
                        state <= ST_HASH_WAIT;
                end

                ST_HASH_WAIT: begin
                    if (hash_rsp_valid) begin
                        chain_node <= hash_rsp_node;
                        if (hash_index == 4'd14) begin
                            word_index <= '0;
                            state <= ST_CHAIN_WRITE;
                        end else begin
                            hash_index <= hash_index + 1'b1;
                            state <= ST_HASH_REQUEST;
                        end
                    end
                end

                ST_CHAIN_WRITE: begin
                    if (word_index == 2'd3) begin
                        if (chain_number == 6'd34) begin
                            state <= ST_TLEN_REQUEST;
                        end else begin
                            chain_number <= chain_number + 1'b1;
                            byte_index <= '0;
                            state <= ST_SIG_REQUEST;
                        end
                    end else begin
                        word_index <= word_index + 1'b1;
                    end
                end

                ST_TLEN_REQUEST: begin
                    if (hash_req_valid && hash_req_ready)
                        state <= ST_TLEN_WAIT;
                end

                ST_TLEN_WAIT: begin
                    if (hash_rsp_valid) begin
                        wots_pk <= hash_rsp_node;
                        done <= 1'b1;
                        state <= ST_IDLE;
                    end
                end

                default: begin
                    state <= ST_IDLE;
                    done <= 1'b0;
                end
            endcase
        end
    end
endmodule
