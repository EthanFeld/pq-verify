module xmss_verify (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          start,
    output logic          start_ready,
    input  logic [127:0]  leaf,
    input  logic [8:0]    leaf_index,
    input  logic [31:0]   layer,
    input  logic [95:0]   tree,
    input  logic [15:0]   sig_base,
    input  logic [127:0]  pk_seed,
    output logic          sig_rd_en,
    output logic [15:0]   sig_rd_addr,
    input  logic          sig_valid,
    input  logic [7:0]    sig_byte,
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
    output logic [127:0]  root
);
    localparam logic [15:0] WOTS_SIG_BYTES = 16'd560;
    localparam logic [15:0] NODE_BYTES = 16'd16;

    typedef enum logic [2:0] {
        ST_IDLE,
        ST_SIG_REQUEST,
        ST_SIG_WAIT,
        ST_HASH_REQUEST,
        ST_HASH_WAIT
    } state_t;

    state_t state;
    logic [127:0] node_reg;
    logic [127:0] auth_reg;
    logic [8:0] leaf_index_reg;
    logic [3:0] level;
    logic [3:0] sig_byte_index;
    logic [31:0] layer_reg;
    logic [95:0] tree_reg;
    logic [15:0] sig_base_reg;
    logic [127:0] seed_reg;
    logic [31:0] height_word;
    logic [31:0] index_word;

    always_comb begin
        start_ready = (state == ST_IDLE);
        sig_rd_en = (state == ST_SIG_REQUEST);
        sig_rd_addr = sig_base_reg + WOTS_SIG_BYTES
            + (level * NODE_BYTES) + {12'd0, sig_byte_index};

        hash_req_valid = (state == ST_HASH_REQUEST);
        hash_kind = 2'd1; // H
        height_word = {28'd0, level} + 1'b1;
        index_word = {24'd0, leaf_index_reg[8:1]};
        hash_adrs = {
            layer_reg, tree_reg, 32'd2, 32'd0, height_word, index_word
        };
        hash_src_sel = 2'd3; // request-local 32-byte pair
        hash_src_addr = 16'd0;
        hash_count = 16'd32;
        hash_pair = (leaf_index_reg[0])
            ? {auth_reg, node_reg}
            : {node_reg, auth_reg};
        hash_pk_seed = seed_reg;
        root = node_reg;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            node_reg <= '0;
            auth_reg <= '0;
            leaf_index_reg <= '0;
            level <= '0;
            sig_byte_index <= '0;
            layer_reg <= '0;
            tree_reg <= '0;
            sig_base_reg <= '0;
            seed_reg <= '0;
            done <= 1'b0;
        end else begin
            done <= 1'b0;

            case (state)
                ST_IDLE: begin
                    if (start && start_ready) begin
                        node_reg <= leaf;
                        leaf_index_reg <= leaf_index;
                        layer_reg <= layer;
                        tree_reg <= tree;
                        sig_base_reg <= sig_base;
                        seed_reg <= pk_seed;
                        level <= '0;
                        sig_byte_index <= '0;
                        auth_reg <= '0;
                        state <= ST_SIG_REQUEST;
                    end
                end

                ST_SIG_REQUEST: begin
                    state <= ST_SIG_WAIT;
                end

                ST_SIG_WAIT: begin
                    if (sig_valid) begin
                        auth_reg[127 - sig_byte_index * 8 -: 8] <= sig_byte;
                        if (sig_byte_index == 4'd15) begin
                            sig_byte_index <= '0;
                            state <= ST_HASH_REQUEST;
                        end else begin
                            sig_byte_index <= sig_byte_index + 1'b1;
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
                        node_reg <= hash_rsp_node;
                        leaf_index_reg <= leaf_index_reg >> 1;
                        if (level == 4'd8) begin
                            done <= 1'b1;
                            state <= ST_IDLE;
                        end else begin
                            level <= level + 1'b1;
                            sig_byte_index <= '0;
                            state <= ST_SIG_REQUEST;
                        end
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
