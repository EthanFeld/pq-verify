module ht_verify (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          start,
    output logic          start_ready,
    input  logic [127:0]  message,
    input  logic [53:0]   idx_tree,
    input  logic [8:0]    idx_leaf,
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
    output logic [127:0]  root
);
    localparam logic [15:0] XMSS_SIGNATURE_BYTES = 16'd704;

    typedef enum logic [2:0] {
        ST_IDLE,
        ST_WOTS_START,
        ST_WOTS_WAIT,
        ST_XMSS_START,
        ST_XMSS_WAIT
    } state_t;

    state_t state;
    logic [2:0] layer_number;
    logic [53:0] tree_index;
    logic [8:0] leaf_index;
    logic [127:0] layer_message;
    logic [15:0] sig_base_reg;
    logic [127:0] seed_reg;
    logic [15:0] layer_sig_base;

    logic wots_start;
    logic wots_start_ready;
    logic wots_sig_rd_en;
    logic [15:0] wots_sig_rd_addr;
    logic wots_scratch_wr_en;
    logic [7:0] wots_scratch_wr_addr;
    logic [31:0] wots_scratch_wr_data;
    logic wots_hash_req_valid;
    logic [1:0] wots_hash_kind;
    logic [255:0] wots_hash_adrs;
    logic [1:0] wots_hash_src_sel;
    logic [15:0] wots_hash_src_addr;
    logic [15:0] wots_hash_count;
    logic [255:0] wots_hash_pair;
    logic [127:0] wots_hash_pk_seed;
    logic wots_done;
    logic [127:0] wots_pk;

    logic xmss_start;
    logic xmss_start_ready;
    logic xmss_sig_rd_en;
    logic [15:0] xmss_sig_rd_addr;
    logic xmss_hash_req_valid;
    logic [1:0] xmss_hash_kind;
    logic [255:0] xmss_hash_adrs;
    logic [1:0] xmss_hash_src_sel;
    logic [15:0] xmss_hash_src_addr;
    logic [15:0] xmss_hash_count;
    logic [255:0] xmss_hash_pair;
    logic [127:0] xmss_hash_pk_seed;
    logic xmss_done;
    logic [127:0] xmss_root;

    assign layer_sig_base = sig_base_reg + layer_number * XMSS_SIGNATURE_BYTES;

    wots_verify u_wots_verify (
        .clk(clk), .rst_n(rst_n),
        .start(wots_start), .start_ready(wots_start_ready),
        .message(layer_message), .layer({29'd0, layer_number}),
        .tree({42'd0, tree_index}), .keypair({23'd0, leaf_index}),
        .sig_base(layer_sig_base), .pk_seed(seed_reg),
        .sig_rd_en(wots_sig_rd_en), .sig_rd_addr(wots_sig_rd_addr),
        .sig_valid(sig_valid), .sig_byte(sig_byte),
        .scratch_wr_en(wots_scratch_wr_en), .scratch_wr_addr(wots_scratch_wr_addr),
        .scratch_wr_data(wots_scratch_wr_data),
        .hash_req_valid(wots_hash_req_valid), .hash_req_ready(hash_req_ready),
        .hash_kind(wots_hash_kind), .hash_adrs(wots_hash_adrs),
        .hash_src_sel(wots_hash_src_sel), .hash_src_addr(wots_hash_src_addr),
        .hash_count(wots_hash_count), .hash_pair(wots_hash_pair),
        .hash_pk_seed(wots_hash_pk_seed),
        .hash_rsp_valid(hash_rsp_valid), .hash_rsp_node(hash_rsp_node),
        .done(wots_done), .wots_pk(wots_pk)
    );

    xmss_verify u_xmss_verify (
        .clk(clk), .rst_n(rst_n),
        .start(xmss_start), .start_ready(xmss_start_ready),
        .leaf(wots_pk), .leaf_index(leaf_index),
        .layer({29'd0, layer_number}), .tree({42'd0, tree_index}),
        .sig_base(layer_sig_base), .pk_seed(seed_reg),
        .sig_rd_en(xmss_sig_rd_en), .sig_rd_addr(xmss_sig_rd_addr),
        .sig_valid(sig_valid), .sig_byte(sig_byte),
        .hash_req_valid(xmss_hash_req_valid), .hash_req_ready(hash_req_ready),
        .hash_kind(xmss_hash_kind), .hash_adrs(xmss_hash_adrs),
        .hash_src_sel(xmss_hash_src_sel), .hash_src_addr(xmss_hash_src_addr),
        .hash_count(xmss_hash_count), .hash_pair(xmss_hash_pair),
        .hash_pk_seed(xmss_hash_pk_seed),
        .hash_rsp_valid(hash_rsp_valid), .hash_rsp_node(hash_rsp_node),
        .done(xmss_done), .root(xmss_root)
    );

    always_comb begin
        start_ready = (state == ST_IDLE);
        wots_start = (state == ST_WOTS_START);
        xmss_start = (state == ST_XMSS_START);

        if (state == ST_WOTS_WAIT) begin
            sig_rd_en = wots_sig_rd_en;
            sig_rd_addr = wots_sig_rd_addr;
            hash_req_valid = wots_hash_req_valid;
            hash_kind = wots_hash_kind;
            hash_adrs = wots_hash_adrs;
            hash_src_sel = wots_hash_src_sel;
            hash_src_addr = wots_hash_src_addr;
            hash_count = wots_hash_count;
            hash_pair = wots_hash_pair;
            hash_pk_seed = wots_hash_pk_seed;
        end else if (state == ST_XMSS_WAIT) begin
            sig_rd_en = xmss_sig_rd_en;
            sig_rd_addr = xmss_sig_rd_addr;
            hash_req_valid = xmss_hash_req_valid;
            hash_kind = xmss_hash_kind;
            hash_adrs = xmss_hash_adrs;
            hash_src_sel = xmss_hash_src_sel;
            hash_src_addr = xmss_hash_src_addr;
            hash_count = xmss_hash_count;
            hash_pair = xmss_hash_pair;
            hash_pk_seed = xmss_hash_pk_seed;
        end else begin
            sig_rd_en = 1'b0;
            sig_rd_addr = 16'd0;
            hash_req_valid = 1'b0;
            hash_kind = 2'd0;
            hash_adrs = 256'd0;
            hash_src_sel = 2'd0;
            hash_src_addr = 16'd0;
            hash_count = 16'd0;
            hash_pair = 256'd0;
            hash_pk_seed = seed_reg;
        end

        scratch_wr_en = (state == ST_WOTS_WAIT) && wots_scratch_wr_en;
        scratch_wr_addr = wots_scratch_wr_addr;
        scratch_wr_data = wots_scratch_wr_data;
        root = xmss_root;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            layer_number <= '0;
            tree_index <= '0;
            leaf_index <= '0;
            layer_message <= '0;
            sig_base_reg <= '0;
            seed_reg <= '0;
            done <= 1'b0;
        end else begin
            done <= 1'b0;
            case (state)
                ST_IDLE: begin
                    if (start && start_ready) begin
                        layer_number <= '0;
                        tree_index <= idx_tree;
                        leaf_index <= idx_leaf;
                        layer_message <= message;
                        sig_base_reg <= sig_base;
                        seed_reg <= pk_seed;
                        state <= ST_WOTS_START;
                    end
                end

                ST_WOTS_START: begin
                    if (wots_start_ready)
                        state <= ST_WOTS_WAIT;
                end

                ST_WOTS_WAIT: begin
                    if (wots_done)
                        state <= ST_XMSS_START;
                end

                ST_XMSS_START: begin
                    if (xmss_start_ready)
                        state <= ST_XMSS_WAIT;
                end

                ST_XMSS_WAIT: begin
                    if (xmss_done) begin
                        if (layer_number == 3'd6) begin
                            done <= 1'b1;
                            state <= ST_IDLE;
                        end else begin
                            layer_message <= xmss_root;
                            leaf_index <= tree_index[8:0];
                            tree_index <= tree_index >> 9;
                            layer_number <= layer_number + 1'b1;
                            state <= ST_WOTS_START;
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
