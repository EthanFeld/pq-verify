module slh_verify_top #(
    parameter integer RPC = 1,
    parameter integer SCRATCH_STYLE = 0
`ifdef FORMAL
    , parameter integer FORMAL_CONTROL_ONLY = 0
`endif
) (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          start,
    output logic          start_ready,
    input  logic          pure_mode,
    input  logic [7:0]    ctx_len,
    input  logic          ctx_valid,
    output logic          ctx_ready,
    input  logic [7:0]    ctx_byte,
    input  logic          msg_valid,
    output logic          msg_ready,
    input  logic [7:0]    msg_byte,
    input  logic          msg_last,
    input  logic [127:0]  pk_seed,
    input  logic [127:0]  pk_root,
    input  logic          sig_load_en,
    input  logic [10:0]   sig_load_addr,
    input  logic [31:0]   sig_load_data,
    output logic          sig_load_ready,
    output logic          done,
    output logic          valid,
    output logic [31:0]   cycles,
    output logic [15:0]   perms
);
    localparam logic [15:0] FORS_OFFSET = 16'd16;
    localparam logic [15:0] HT_OFFSET = 16'd2928;

    typedef enum logic [3:0] {
        ST_IDLE,
        ST_LOAD_R,
        ST_HMSG_START,
        ST_HMSG_WAIT,
        ST_FORS_START,
        ST_FORS_WAIT,
        ST_HT_START,
        ST_HT_WAIT
    } state_t;

    state_t state;
    logic [2:0] r_index;
    logic [1:0] r_word_q;
    logic r_pending;
    logic [127:0] randomizer;
    logic pure_mode_reg;
    logic [7:0] ctx_len_reg;

    logic hmsg_start;
    logic hmsg_start_ready;
    logic hmsg_done;
    logic [13:0][11:0] md_idx;
    logic [53:0] idx_tree;
    logic [8:0] idx_leaf;
    logic hmsg_shake_in_valid;
    logic hmsg_shake_in_ready;
    logic [63:0] hmsg_shake_in_data;
    logic [3:0] hmsg_shake_in_bytes;
    logic hmsg_shake_in_last;
    logic hmsg_shake_out_valid;
    logic [255:0] hmsg_shake_out;

    logic fors_start;
    logic fors_start_ready;
    logic fors_sig_rd_en;
    logic [15:0] fors_sig_rd_addr;
    logic fors_scratch_wr_en;
    logic [7:0] fors_scratch_wr_addr;
    logic [31:0] fors_scratch_wr_data;
    logic fors_hash_req_valid;
    logic [1:0] fors_hash_kind;
    logic [255:0] fors_hash_adrs;
    logic [1:0] fors_hash_src_sel;
    logic [15:0] fors_hash_src_addr;
    logic [15:0] fors_hash_count;
    logic [255:0] fors_hash_pair;
    logic [127:0] fors_hash_pk_seed;
    logic fors_done;
    logic [127:0] fors_pk;

    logic ht_start;
    logic ht_start_ready;
    logic ht_sig_rd_en;
    logic [15:0] ht_sig_rd_addr;
    logic ht_scratch_wr_en;
    logic [7:0] ht_scratch_wr_addr;
    logic [31:0] ht_scratch_wr_data;
    logic ht_hash_req_valid;
    logic [1:0] ht_hash_kind;
    logic [255:0] ht_hash_adrs;
    logic [1:0] ht_hash_src_sel;
    logic [15:0] ht_hash_src_addr;
    logic [15:0] ht_hash_count;
    logic [255:0] ht_hash_pair;
    logic [127:0] ht_hash_pk_seed;
    logic ht_done;
    logic [127:0] ht_root;

    logic stage_sig_rd_en;
    logic [15:2] stage_sig_rd_addr;
    logic stage_sig_valid;
    logic [10:0] sig_ram_rd_addr;
    logic [31:0] sig_ram_rd_data;

    logic scratch_wr_en;
    logic [7:0] scratch_wr_addr;
    logic [31:0] scratch_wr_data;
    logic [7:0] scratch_rd_addr;
    logic [31:0] scratch_rd_data;

    logic hash_req_valid;
    logic hash_req_ready;
    logic [1:0] hash_kind;
    logic [255:0] hash_adrs;
    logic [1:0] hash_src_sel;
    logic [15:0] hash_src_addr;
    logic [15:0] hash_count;
    logic [255:0] hash_pair;
    logic [127:0] hash_pk_seed;
    logic thash_src_rd_en;
    logic [1:0] thash_src_rd_sel;
    logic [15:0] thash_src_rd_addr;
    logic thash_src_valid;
    logic [1:0] thash_src_sel_q;
    logic [1:0] thash_src_offset_q;
    logic [7:0] thash_src_byte;
    logic [31:0] thash_src_word;
    logic hash_rsp_valid;
    logic [127:0] hash_rsp_node;
    logic thash_shake_in_valid;
    logic thash_shake_in_ready;
    logic [63:0] thash_shake_in_data;
    logic [3:0] thash_shake_in_bytes;
    logic thash_shake_in_last;
    logic thash_shake_bulk_valid;
    logic thash_shake_bulk_ready;
    logic [639:0] thash_shake_bulk_lanes;
    logic [6:0] thash_shake_bulk_bytes;
    logic thash_shake_out_valid;
    logic [255:0] thash_shake_out;
    logic shake_shared_in_valid;
    logic shake_shared_in_ready;
    logic [63:0] shake_shared_in_data;
    logic [3:0] shake_shared_in_bytes;
    logic shake_shared_in_last;
    logic shake_shared_bulk_valid;
    logic shake_shared_bulk_ready;
    logic [639:0] shake_shared_bulk_lanes;
    logic [6:0] shake_shared_bulk_bytes;
    logic shake_shared_out_valid;
    logic [255:0] shake_shared_out;

    logic shake_permutation_start;
    logic hmsg_input_wait;

    assign start_ready = (state == ST_IDLE);
    assign sig_load_ready = (state == ST_IDLE);
    // Count verifier work, not UART wire time spent waiting for streamed input.
    // H_msg advertises ready only while it can accept the next context/message
    // byte; an absent valid byte in that state is external transfer latency.
    assign hmsg_input_wait = (state == ST_HMSG_WAIT)
        && ((ctx_ready && !ctx_valid) || (msg_ready && !msg_valid));

    always_comb begin
        hmsg_shake_in_ready = 1'b0;
        hmsg_shake_out_valid = 1'b0;
        hmsg_shake_out = '0;
        thash_shake_in_ready = 1'b0;
        thash_shake_out_valid = 1'b0;
        thash_shake_out = '0;
        shake_shared_in_valid = 1'b0;
        shake_shared_in_data = '0;
        shake_shared_in_bytes = '0;
        shake_shared_in_last = 1'b0;
        shake_shared_bulk_valid = 1'b0;
        shake_shared_bulk_lanes = '0;
        shake_shared_bulk_bytes = '0;
        thash_shake_bulk_ready = 1'b0;
        if (state == ST_HMSG_WAIT) begin
            shake_shared_in_valid = hmsg_shake_in_valid;
            shake_shared_in_data = hmsg_shake_in_data;
            shake_shared_in_bytes = hmsg_shake_in_bytes;
            shake_shared_in_last = hmsg_shake_in_last;
            hmsg_shake_in_ready = shake_shared_in_ready;
            hmsg_shake_out_valid = shake_shared_out_valid;
            hmsg_shake_out = shake_shared_out;
        end else if (state == ST_FORS_WAIT || state == ST_HT_WAIT) begin
            shake_shared_in_valid = thash_shake_in_valid;
            shake_shared_in_data = thash_shake_in_data;
            shake_shared_in_bytes = thash_shake_in_bytes;
            shake_shared_in_last = thash_shake_in_last;
            shake_shared_bulk_valid = thash_shake_bulk_valid;
            shake_shared_bulk_lanes = thash_shake_bulk_lanes;
            shake_shared_bulk_bytes = thash_shake_bulk_bytes;
            thash_shake_in_ready = shake_shared_in_ready;
            thash_shake_bulk_ready = shake_shared_bulk_ready;
            thash_shake_out_valid = shake_shared_out_valid;
            thash_shake_out = shake_shared_out;
        end

        if (state == ST_FORS_WAIT) begin
            stage_sig_rd_en = fors_sig_rd_en;
            stage_sig_rd_addr = fors_sig_rd_addr[15:2];
            hash_req_valid = fors_hash_req_valid;
            hash_kind = fors_hash_kind;
            hash_adrs = fors_hash_adrs;
            hash_src_sel = fors_hash_src_sel;
            hash_src_addr = fors_hash_src_addr;
            hash_count = fors_hash_count;
            hash_pair = fors_hash_pair;
            hash_pk_seed = fors_hash_pk_seed;
            scratch_wr_en = fors_scratch_wr_en;
            scratch_wr_addr = fors_scratch_wr_addr;
            scratch_wr_data = fors_scratch_wr_data;
        end else if (state == ST_HT_WAIT) begin
            stage_sig_rd_en = ht_sig_rd_en;
            stage_sig_rd_addr = ht_sig_rd_addr[15:2];
            hash_req_valid = ht_hash_req_valid;
            hash_kind = ht_hash_kind;
            hash_adrs = ht_hash_adrs;
            hash_src_sel = ht_hash_src_sel;
            hash_src_addr = ht_hash_src_addr;
            hash_count = ht_hash_count;
            hash_pair = ht_hash_pair;
            hash_pk_seed = ht_hash_pk_seed;
            scratch_wr_en = ht_scratch_wr_en;
            scratch_wr_addr = ht_scratch_wr_addr;
            scratch_wr_data = ht_scratch_wr_data;
        end else begin
            stage_sig_rd_en = 1'b0;
            stage_sig_rd_addr = '0;
            hash_req_valid = 1'b0;
            hash_kind = 2'd0;
            hash_adrs = 256'd0;
            hash_src_sel = 2'd0;
            hash_src_addr = 16'd0;
            hash_count = 16'd0;
            hash_pair = 256'd0;
            hash_pk_seed = pk_seed;
            scratch_wr_en = 1'b0;
            scratch_wr_addr = 8'd0;
            scratch_wr_data = 32'd0;
        end

        // Valid source addresses fit in 13 bits (signature max is 7,856 B).
        // Clamp impossible high addresses instead of silently aliasing RAM.
        if (thash_src_rd_en && (thash_src_rd_sel == 2'd1)
                && (thash_src_rd_addr[15:13] == 3'd0))
            scratch_rd_addr = thash_src_rd_addr[9:2];
        else
            scratch_rd_addr = 8'd0;

        if (state == ST_LOAD_R)
            sig_ram_rd_addr = {8'd0, r_index};
        else if (thash_src_rd_en && (thash_src_rd_sel == 2'd0)
                && (thash_src_rd_addr[15:13] == 3'd0))
            sig_ram_rd_addr = thash_src_rd_addr[12:2];
        else if (stage_sig_rd_en && (stage_sig_rd_addr[15:13] == 3'd0))
            sig_ram_rd_addr = stage_sig_rd_addr[12:2];
        else
            sig_ram_rd_addr = 11'd0;

        if (thash_src_sel_q == 2'd1)
            thash_src_byte = scratch_rd_data[31 - thash_src_offset_q * 8 -: 8];
        else
            thash_src_byte = sig_ram_rd_data[31 - thash_src_offset_q * 8 -: 8];
        if (thash_src_sel_q == 2'd1)
            thash_src_word = scratch_rd_data;
        else
            thash_src_word = sig_ram_rd_data;

    end

    sig_ram u_sig_ram (
        .clk(clk),
        .wr_en(sig_load_en && sig_load_ready),
        .wr_addr(sig_load_addr),
        .wr_data(sig_load_data),
        .rd_addr(sig_ram_rd_addr),
        .rd_data(sig_ram_rd_data)
    );

    scratch_ram #(.RAM_STYLE(SCRATCH_STYLE)) u_scratch_ram (
        .clk(clk),
        .wr_en(scratch_wr_en),
        .wr_addr(scratch_wr_addr),
        .wr_data(scratch_wr_data),
        .rd_addr(scratch_rd_addr),
        .rd_data(scratch_rd_data)
    );

    hmsg #(.RPC(RPC), .SHARED_SHAKE(1)) u_hmsg (
        .clk(clk), .rst_n(rst_n),
        .start(hmsg_start), .start_ready(hmsg_start_ready),
        .pure_mode(pure_mode_reg), .ctx_len(ctx_len_reg),
        .randomizer(randomizer), .pk_seed(pk_seed), .pk_root(pk_root),
        .ctx_valid(ctx_valid), .ctx_ready(ctx_ready), .ctx_byte(ctx_byte),
        .msg_valid(msg_valid), .msg_ready(msg_ready), .msg_byte(msg_byte),
        .msg_last(msg_last),
        .shake_in_valid(hmsg_shake_in_valid), .shake_in_ready(hmsg_shake_in_ready),
        .shake_in_data(hmsg_shake_in_data), .shake_in_bytes(hmsg_shake_in_bytes),
        .shake_in_last(hmsg_shake_in_last), .shake_out_valid(hmsg_shake_out_valid),
        .shake_out(hmsg_shake_out), .done(hmsg_done),
        .md_idx(md_idx), .idx_tree(idx_tree), .idx_leaf(idx_leaf)
    );

    fors_verify u_fors_verify (
        .clk(clk), .rst_n(rst_n),
        .start(fors_start), .start_ready(fors_start_ready),
        .md_idx(md_idx), .idx_tree(idx_tree), .idx_leaf(idx_leaf),
        .layer(32'd0), .sig_base(FORS_OFFSET), .pk_seed(pk_seed),
        .sig_rd_en(fors_sig_rd_en), .sig_rd_addr(fors_sig_rd_addr),
        .sig_valid(stage_sig_valid), .sig_word(sig_ram_rd_data),
        .scratch_wr_en(fors_scratch_wr_en), .scratch_wr_addr(fors_scratch_wr_addr),
        .scratch_wr_data(fors_scratch_wr_data),
        .hash_req_valid(fors_hash_req_valid), .hash_req_ready(hash_req_ready),
        .hash_kind(fors_hash_kind), .hash_adrs(fors_hash_adrs),
        .hash_src_sel(fors_hash_src_sel), .hash_src_addr(fors_hash_src_addr),
        .hash_count(fors_hash_count), .hash_pair(fors_hash_pair),
        .hash_pk_seed(fors_hash_pk_seed),
        .hash_rsp_valid(hash_rsp_valid), .hash_rsp_node(hash_rsp_node),
        .done(fors_done), .fors_pk(fors_pk)
    );

    ht_verify u_ht_verify (
        .clk(clk), .rst_n(rst_n),
        .start(ht_start), .start_ready(ht_start_ready),
        .message(fors_pk), .idx_tree(idx_tree), .idx_leaf(idx_leaf),
        .sig_base(HT_OFFSET), .pk_seed(pk_seed),
        .sig_rd_en(ht_sig_rd_en), .sig_rd_addr(ht_sig_rd_addr),
        .sig_valid(stage_sig_valid),
        .sig_word(sig_ram_rd_data),
        .scratch_wr_en(ht_scratch_wr_en), .scratch_wr_addr(ht_scratch_wr_addr),
        .scratch_wr_data(ht_scratch_wr_data),
        .hash_req_valid(ht_hash_req_valid), .hash_req_ready(hash_req_ready),
        .hash_kind(ht_hash_kind), .hash_adrs(ht_hash_adrs),
        .hash_src_sel(ht_hash_src_sel), .hash_src_addr(ht_hash_src_addr),
        .hash_count(ht_hash_count), .hash_pair(ht_hash_pair),
        .hash_pk_seed(ht_hash_pk_seed),
        .hash_rsp_valid(hash_rsp_valid), .hash_rsp_node(hash_rsp_node),
        .done(ht_done), .root(ht_root)
    );

    thash #(.RPC(RPC), .SHARED_SHAKE(1)) u_thash (
        .clk(clk), .rst_n(rst_n),
        .req_valid(hash_req_valid), .req_ready(hash_req_ready),
        .req_kind(hash_kind), .req_adrs(hash_adrs),
        .req_src_sel(hash_src_sel), .req_src_addr(hash_src_addr),
        .req_count(hash_count), .pk_seed(hash_pk_seed), .req_pair(hash_pair),
        .src_rd_en(thash_src_rd_en), .src_rd_sel(thash_src_rd_sel),
        .src_rd_addr(thash_src_rd_addr), .src_valid(thash_src_valid),
        .src_byte(thash_src_byte), .src_word(thash_src_word),
        .shake_in_valid(thash_shake_in_valid), .shake_in_ready(thash_shake_in_ready),
        .shake_in_data(thash_shake_in_data), .shake_in_bytes(thash_shake_in_bytes),
        .shake_in_last(thash_shake_in_last),
        .shake_bulk_valid(thash_shake_bulk_valid), .shake_bulk_ready(thash_shake_bulk_ready),
        .shake_bulk_lanes(thash_shake_bulk_lanes), .shake_bulk_bytes(thash_shake_bulk_bytes),
        .shake_out_valid(thash_shake_out_valid),
        .shake_out(thash_shake_out), .rsp_valid(hash_rsp_valid),
        .rsp_node(hash_rsp_node)
    );

    shake256 #(
        .RPC(RPC)
`ifdef FORMAL
        , .FORMAL_CONTROL_ONLY(FORMAL_CONTROL_ONLY)
`endif
    ) u_shared_shake256 (
        .clk(clk), .rst_n(rst_n),
        .in_valid(shake_shared_in_valid), .in_ready(shake_shared_in_ready),
        .in_data(shake_shared_in_data), .in_bytes(shake_shared_in_bytes),
        .in_last(shake_shared_in_last),
        .bulk_valid(shake_shared_bulk_valid), .bulk_ready(shake_shared_bulk_ready),
        .bulk_lanes(shake_shared_bulk_lanes), .bulk_bytes(shake_shared_bulk_bytes),
        .out_valid(shake_shared_out_valid),
        .out(shake_shared_out), .permutation_start(shake_permutation_start)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            r_index <= '0;
            r_word_q <= '0;
            r_pending <= 1'b0;
            randomizer <= '0;
            pure_mode_reg <= 1'b0;
            ctx_len_reg <= '0;
            stage_sig_valid <= 1'b0;
            thash_src_valid <= 1'b0;
            thash_src_sel_q <= '0;
            thash_src_offset_q <= '0;
            done <= 1'b0;
            valid <= 1'b0;
            cycles <= '0;
            perms <= '0;
        end else begin
            done <= 1'b0;
            valid <= 1'b0;
            stage_sig_valid <= stage_sig_rd_en;
            thash_src_valid <= thash_src_rd_en;
            if (thash_src_rd_en) begin
                thash_src_sel_q <= thash_src_rd_sel;
                thash_src_offset_q <= thash_src_rd_addr[1:0];
            end

            if (state != ST_IDLE && !hmsg_input_wait)
                cycles <= cycles + 1'b1;

            // Count the shared engine's actual work instead of inferring it
            // with a 32-bit divider and per-hash length estimates.
            if (shake_permutation_start && state != ST_IDLE)
                perms <= perms + 16'd1;

            case (state)
                ST_IDLE: begin
                    if (start && start_ready) begin
                        state <= ST_LOAD_R;
                        r_index <= '0;
                        r_word_q <= '0;
                        r_pending <= 1'b0;
                        pure_mode_reg <= pure_mode;
                        ctx_len_reg <= ctx_len;
                        cycles <= '0;
                        perms <= '0;
                        valid <= 1'b0;
                    end
                end

                ST_LOAD_R: begin
                    if (!r_pending) begin
                        r_pending <= 1'b1;
                        r_word_q <= r_index[1:0];
                        r_index <= r_index + 1'b1;
                    end else begin
                        randomizer[127 - r_word_q * 32 -: 32] <= sig_ram_rd_data;
                        if (r_word_q == 2'd3) begin
                            r_pending <= 1'b0;
                            state <= ST_HMSG_START;
                        end else begin
                            r_word_q <= r_index[1:0];
                            r_index <= r_index + 1'b1;
                        end
                    end
                end

                ST_HMSG_START: begin
                    if (hmsg_start_ready)
                        state <= ST_HMSG_WAIT;
                end

                ST_HMSG_WAIT: begin
                    if (hmsg_done) begin
                        state <= ST_FORS_START;
                    end
                end

                ST_FORS_START: begin
                    if (fors_start_ready)
                        state <= ST_FORS_WAIT;
                end

                ST_FORS_WAIT: begin
                    if (fors_done)
                        state <= ST_HT_START;
                end

                ST_HT_START: begin
                    if (ht_start_ready)
                        state <= ST_HT_WAIT;
                end

                ST_HT_WAIT: begin
                    if (ht_done) begin
                        valid <= (ht_root == pk_root);
                        done <= 1'b1;
                        state <= ST_IDLE;
                    end
                end

                default: begin
                    state <= ST_IDLE;
                    valid <= 1'b0;
                    done <= 1'b0;
                end
            endcase
        end
    end

    assign hmsg_start = (state == ST_HMSG_START);
    assign fors_start = (state == ST_FORS_START);
    assign ht_start = (state == ST_HT_START);
endmodule
