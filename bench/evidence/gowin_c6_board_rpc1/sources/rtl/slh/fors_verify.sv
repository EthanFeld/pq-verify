module fors_verify (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          start,
    output logic          start_ready,
    input  logic [13:0][11:0] md_idx,
    input  logic [53:0]   idx_tree,
    input  logic [8:0]    idx_leaf,
    input  logic [31:0]   layer,
    input  logic [15:0]   sig_base,
    input  logic [127:0]  pk_seed,
    output logic          sig_rd_en,
    output logic [15:0]   sig_rd_addr,
    input  logic          sig_valid,
    input  logic [31:0]   sig_word,
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
    output logic [127:0]  fors_pk
);
    localparam logic [15:0] FORS_TREE_BYTES = 16'd208;

    typedef enum logic [3:0] {
        ST_IDLE,
        ST_SK_REQUEST,
        ST_SK_WAIT,
        ST_F_REQUEST,
        ST_F_WAIT,
        ST_AUTH_REQUEST,
        ST_AUTH_WAIT,
        ST_H_REQUEST,
        ST_H_WAIT,
        ST_ROOT_WRITE,
        ST_TK_REQUEST,
        ST_TK_WAIT
    } state_t;

    state_t state;
    logic [13:0][11:0] indices_reg;
    logic [3:0] tree_number;
    logic [3:0] level;
    logic [1:0] word_index;
    logic [1:0] root_word;
    logic [127:0] secret_reg;
    logic [127:0] auth_reg;
    logic [127:0] node_reg;
    logic [15:0] path_index;
    logic [31:0] layer_reg;
    logic [95:0] tree_reg;
    logic [31:0] keypair_reg;
    logic [15:0] sig_base_reg;
    logic [127:0] seed_reg;
    logic [31:0] type_word;
    logic [31:0] height_word;
    logic [31:0] index_word;

    function automatic logic [15:0] combine_fors_index(
        input logic [3:0] tree_id,
        input logic [11:0] leaf_id
    );
        combine_fors_index = {tree_id, 12'd0} | {4'd0, leaf_id};
    endfunction

    always_comb begin
        start_ready = (state == ST_IDLE);
        sig_rd_en = (state == ST_SK_REQUEST) || (state == ST_AUTH_REQUEST);
        if (state == ST_SK_REQUEST || state == ST_SK_WAIT) begin
            sig_rd_addr = sig_base_reg + tree_number * FORS_TREE_BYTES
                + {12'd0, word_index, 2'b00};
        end else begin
            sig_rd_addr = sig_base_reg + tree_number * FORS_TREE_BYTES
                + 16'd16 + level * 16'd16 + {12'd0, word_index, 2'b00};
        end

        scratch_wr_en = (state == ST_ROOT_WRITE);
        scratch_wr_addr = {2'b00, tree_number, 2'b00} + {6'd0, root_word};
        scratch_wr_data = node_reg[127 - root_word * 32 -: 32];

        hash_req_valid = (state == ST_F_REQUEST)
            || (state == ST_H_REQUEST) || (state == ST_TK_REQUEST);
        hash_kind = 2'd0;
        hash_src_sel = 2'd3;
        hash_src_addr = 16'd0;
        hash_count = 16'd16;
        hash_pair = {secret_reg, 128'd0};
        type_word = 32'd3; // FORS tree
        height_word = 32'd0;
        index_word = {16'd0, path_index};

        if (state == ST_H_REQUEST || state == ST_H_WAIT) begin
            hash_kind = 2'd1;
            hash_count = 16'd32;
            hash_pair = path_index[0]
                ? {auth_reg, node_reg}
                : {node_reg, auth_reg};
            height_word = {28'd0, level} + 1'b1;
            index_word = {17'd0, path_index[15:1]};
        end else if (state == ST_TK_REQUEST || state == ST_TK_WAIT) begin
            hash_kind = 2'd2;
            hash_src_sel = 2'd1; // FORS roots in scratch RAM
            hash_count = 16'd224;
            type_word = 32'd4; // FORS public key (roots)
            index_word = '0;
        end

        hash_adrs = {
            layer_reg, tree_reg, type_word, keypair_reg, height_word, index_word
        };
        hash_pk_seed = seed_reg;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            indices_reg <= '0;
            tree_number <= '0;
            level <= '0;
            word_index <= '0;
            root_word <= '0;
            secret_reg <= '0;
            auth_reg <= '0;
            node_reg <= '0;
            path_index <= '0;
            layer_reg <= '0;
            tree_reg <= '0;
            keypair_reg <= '0;
            sig_base_reg <= '0;
            seed_reg <= '0;
            done <= 1'b0;
            fors_pk <= '0;
        end else begin
            done <= 1'b0;

            case (state)
                ST_IDLE: begin
                    if (start && start_ready) begin
                        indices_reg <= md_idx;
                        tree_number <= '0;
                        level <= '0;
                        word_index <= '0;
                        root_word <= '0;
                        path_index <= combine_fors_index(4'd0, md_idx[0]);
                        layer_reg <= layer;
                        tree_reg <= {42'd0, idx_tree};
                        keypair_reg <= {23'd0, idx_leaf};
                        sig_base_reg <= sig_base;
                        seed_reg <= pk_seed;
                        state <= ST_SK_REQUEST;
                    end
                end

                ST_SK_REQUEST: begin
                    state <= ST_SK_WAIT;
                end

                ST_SK_WAIT: begin
                    if (sig_valid) begin
                        secret_reg[127 - word_index * 32 -: 32] <= sig_word;
                        if (word_index == 2'd3) begin
                            word_index <= '0;
                            state <= ST_F_REQUEST;
                        end else begin
                            word_index <= word_index + 1'b1;
                            state <= ST_SK_REQUEST;
                        end
                    end
                end

                ST_F_REQUEST: begin
                    if (hash_req_valid && hash_req_ready)
                        state <= ST_F_WAIT;
                end

                ST_F_WAIT: begin
                    if (hash_rsp_valid) begin
                        node_reg <= hash_rsp_node;
                        level <= '0;
                        word_index <= '0;
                        state <= ST_AUTH_REQUEST;
                    end
                end

                ST_AUTH_REQUEST: begin
                    state <= ST_AUTH_WAIT;
                end

                ST_AUTH_WAIT: begin
                    if (sig_valid) begin
                        auth_reg[127 - word_index * 32 -: 32] <= sig_word;
                        if (word_index == 2'd3) begin
                            word_index <= '0;
                            state <= ST_H_REQUEST;
                        end else begin
                            word_index <= word_index + 1'b1;
                            state <= ST_AUTH_REQUEST;
                        end
                    end
                end

                ST_H_REQUEST: begin
                    if (hash_req_valid && hash_req_ready)
                        state <= ST_H_WAIT;
                end

                ST_H_WAIT: begin
                    if (hash_rsp_valid) begin
                        node_reg <= hash_rsp_node;
                        path_index <= path_index >> 1;
                        if (level == 4'd11) begin
                            root_word <= '0;
                            state <= ST_ROOT_WRITE;
                        end else begin
                            level <= level + 1'b1;
                            word_index <= '0;
                            state <= ST_AUTH_REQUEST;
                        end
                    end
                end

                ST_ROOT_WRITE: begin
                    if (root_word == 2'd3) begin
                        if (tree_number == 4'd13) begin
                            state <= ST_TK_REQUEST;
                        end else begin
                            tree_number <= tree_number + 1'b1;
                            path_index <= combine_fors_index(
                                tree_number + 1'b1,
                                indices_reg[tree_number + 1'b1]
                            );
                            level <= '0;
                            word_index <= '0;
                            secret_reg <= '0;
                            auth_reg <= '0;
                            state <= ST_SK_REQUEST;
                        end
                    end else begin
                        root_word <= root_word + 1'b1;
                    end
                end

                ST_TK_REQUEST: begin
                    if (hash_req_valid && hash_req_ready)
                        state <= ST_TK_WAIT;
                end

                ST_TK_WAIT: begin
                    if (hash_rsp_valid) begin
                        fors_pk <= hash_rsp_node;
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
