// Bounded FORS prefix; each accepted memory/hash request responds one cycle later.
module fv_fors_verify;
    (* gclk *) reg formal_timestep;
    reg clk = 1'b0;
    reg [2:0] reset_steps = 3'd0;
    wire rst_n = (reset_steps >= 3'd4);
    (* anyconst *) reg [13:0][11:0] md_idx;
    (* anyconst *) reg [53:0] idx_tree;
    (* anyconst *) reg [8:0] idx_leaf;
    (* anyconst *) reg [31:0] layer;
    (* anyconst *) reg [127:0] pk_seed;
    (* anyseq *) reg [31:0] sig_word;
    (* anyseq *) reg [127:0] hash_rsp_node;

    reg start_sent = 1'b0;
    reg sig_valid_q = 1'b0;
    reg hash_rsp_valid_q = 1'b0;
    reg hash_stall_done = 1'b0;
    reg busy_q = 1'b0;
    reg past_valid = 1'b0;
    wire start = rst_n && !start_sent;
    wire start_ready;
    wire sig_rd_en;
    wire [15:0] sig_rd_addr;
    wire scratch_wr_en;
    wire [7:0] scratch_wr_addr;
    wire [31:0] scratch_wr_data;
    wire hash_req_valid;
    wire hash_req_ready = !hash_req_valid || hash_stall_done;
    wire [1:0] hash_kind;
    wire [255:0] hash_adrs;
    wire [1:0] hash_src_sel;
    wire [15:0] hash_src_addr;
    wire [15:0] hash_count;
    wire [255:0] hash_pair;
    wire [127:0] hash_pk_seed;
    wire done;
    wire [127:0] fors_pk;

    always @(posedge formal_timestep) begin
        clk <= !clk;
        if (reset_steps < 3'd4)
            reset_steps <= reset_steps + 1'b1;
    end
    initial assume (!rst_n);

    fors_verify dut (
        .clk(clk), .rst_n(rst_n), .start(start), .start_ready(start_ready),
        .md_idx(md_idx), .idx_tree(idx_tree), .idx_leaf(idx_leaf), .layer(layer),
        .sig_base(16'd16), .pk_seed(pk_seed),
        .sig_rd_en(sig_rd_en), .sig_rd_addr(sig_rd_addr),
        .sig_valid(sig_valid_q), .sig_word(sig_word),
        .scratch_wr_en(scratch_wr_en), .scratch_wr_addr(scratch_wr_addr),
        .scratch_wr_data(scratch_wr_data),
        .hash_req_valid(hash_req_valid), .hash_req_ready(hash_req_ready),
        .hash_kind(hash_kind), .hash_adrs(hash_adrs),
        .hash_src_sel(hash_src_sel), .hash_src_addr(hash_src_addr),
        .hash_count(hash_count), .hash_pair(hash_pair), .hash_pk_seed(hash_pk_seed),
        .hash_rsp_valid(hash_rsp_valid_q), .hash_rsp_node(hash_rsp_node),
        .done(done), .fors_pk(fors_pk)
    );

    hs_props #(.PAYLOAD_WIDTH(676)) hash_req_checker (
        .clk(clk), .rst_n(rst_n), .valid(hash_req_valid), .ready(hash_req_ready),
        .payload({hash_kind, hash_adrs, hash_src_sel, hash_src_addr,
                  hash_count, hash_pair, hash_pk_seed})
    );
    hs_props #(.PAYLOAD_WIDTH(16), .COVER_STALL(0)) sig_read_checker (
        .clk(clk), .rst_n(rst_n), .valid(sig_rd_en), .ready(1'b1),
        .payload(sig_rd_addr)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            start_sent <= 1'b0;
            sig_valid_q <= 1'b0;
            hash_rsp_valid_q <= 1'b0;
            hash_stall_done <= 1'b0;
            busy_q <= 1'b0;
            past_valid <= 1'b0;
        end else begin
            sig_valid_q <= sig_rd_en;
            hash_rsp_valid_q <= hash_req_valid && hash_req_ready;
            if (hash_req_valid && !hash_req_ready)
                hash_stall_done <= 1'b1;
            if (start && start_ready) begin
                start_sent <= 1'b1;
                busy_q <= 1'b1;
            end
            if (busy_q && !done)
                assert (!start_ready);
            if (done) begin
                assert (busy_q);
                busy_q <= 1'b0;
            end
            if (sig_rd_en)
                assert (sig_rd_addr < 16'd8192);
            if (scratch_wr_en)
                assert ({1'b0, scratch_wr_addr} < 9'd256);
            if (past_valid && $past(done))
                assert (!done);
            past_valid <= 1'b1;
        end
    end
endmodule
