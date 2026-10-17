`timescale 1ns/1ps
module tb_hmsg_boundaries;
    parameter integer MSG_BYTES = 609;
    parameter integer CTX_BYTES = 255;

    logic clk = 0;
    always #5 clk = !clk;
    logic rst_n = 0;
    logic start = 0, pure_mode = 0;
    wire start_ready, ctx_ready, msg_ready, done;
    logic ctx_valid = 0, msg_valid = 0, msg_last = 0;
    logic [7:0] ctx_byte = 0, msg_byte = 0;
    logic [7:0] context_mem [0:(CTX_BYTES > 0 ? CTX_BYTES : 1)-1];
    logic [7:0] message_mem [0:(MSG_BYTES > 0 ? MSG_BYTES : 1)-1];
    logic [127:0] randomizer = 0, pk_seed = 0, pk_root = 0;
    logic [239:0] expected_digest = 0;
    logic [167:0] expected_md_idx = 0;
    logic [53:0] expected_tree = 0;
    logic [8:0] expected_leaf = 0;
    wire [13:0][11:0] md_idx;
    wire [53:0] idx_tree;
    wire [8:0] idx_leaf;
    string context_file, message_file;
    integer message_length, context_length, pure_value, test_id, waits;

    hmsg #(.RPC(1)) dut (
        .clk(clk), .rst_n(rst_n), .start(start), .start_ready(start_ready),
        .pure_mode(pure_mode), .ctx_len(8'(context_length)),
        .randomizer(randomizer), .pk_seed(pk_seed), .pk_root(pk_root),
        .ctx_valid(ctx_valid), .ctx_ready(ctx_ready), .ctx_byte(ctx_byte),
        .msg_valid(msg_valid), .msg_ready(msg_ready), .msg_byte(msg_byte), .msg_last(msg_last),
        .shake_in_valid(), .shake_in_ready(1'b0), .shake_in_data(), .shake_in_bytes(),
        .shake_in_last(), .shake_out_valid(1'b0), .shake_out(256'd0), .done(done),
        .md_idx(md_idx), .idx_tree(idx_tree), .idx_leaf(idx_leaf)
    );

    initial begin
        if (!$value$plusargs("context_file=%s", context_file)
                || !$value$plusargs("message_file=%s", message_file)
                || !$value$plusargs("message_length=%d", message_length)
                || !$value$plusargs("context_length=%d", context_length)
                || !$value$plusargs("pure=%d", pure_value)
                || !$value$plusargs("test_id=%d", test_id)
                || !$value$plusargs("randomizer=%h", randomizer)
                || !$value$plusargs("pk_seed=%h", pk_seed)
                || !$value$plusargs("pk_root=%h", pk_root)
                || !$value$plusargs("expected_digest=%h", expected_digest)
                || !$value$plusargs("expected_md_idx=%h", expected_md_idx)
                || !$value$plusargs("expected_tree=%h", expected_tree)
                || !$value$plusargs("expected_leaf=%h", expected_leaf))
            $fatal(1, "missing H_msg case argument");
        if (message_length < 0 || message_length > MSG_BYTES
                || context_length < 0 || context_length > CTX_BYTES || context_length > 255)
            $fatal(1, "H_msg input length exceeds replay capacity");
        $readmemh(context_file, context_mem);
        $readmemh(message_file, message_mem);
        pure_mode = pure_value != 0;
        repeat (3) @(negedge clk);
        rst_n = 1;
        @(negedge clk);
        start = 1;
        @(negedge clk);
        start = 0;

        for (integer index = 0; index < context_length; index = index + 1) begin
            ctx_valid = 1;
            ctx_byte = context_mem[index];
            while (!ctx_ready) @(negedge clk);
            @(posedge clk); #1;
            @(negedge clk);
        end
        ctx_valid = 0;
        for (integer index = 0; index < message_length; index = index + 1) begin
            msg_valid = 1;
            msg_byte = message_mem[index];
            msg_last = index == message_length - 1;
            while (!msg_ready) @(negedge clk);
            @(posedge clk); #1;
            @(negedge clk);
        end
        msg_valid = 0;
        if (message_length == 0) begin
            msg_last = 1;
            while (!msg_ready) @(negedge clk);
            @(posedge clk); #1;
            @(negedge clk);
        end
        msg_last = 0;

        waits = 0;
        while (!done) begin
            @(posedge clk); #1;
            waits = waits + 1;
            if (waits > 1000000) $fatal(1, "H_msg watchdog tc=%0d state=%0d", test_id, dut.state);
        end
        if (dut.digest[239:0] !== expected_digest)
            $fatal(1, "H_msg digest mismatch tc=%0d got=%h expected=%h",
                   test_id, dut.digest[239:0], expected_digest);
        if (md_idx !== expected_md_idx || idx_tree !== expected_tree || idx_leaf !== expected_leaf)
            $fatal(1, "H_msg split mismatch tc=%0d", test_id);
        $display("PASS Hmsg boundary tc=%0d pure=%0d ctx=%0d msg=%0d", test_id,
                 pure_mode, context_length, message_length);
        $finish;
    end

    initial begin
        #50000000;
        $fatal(1, "H_msg boundary simulation watchdog");
    end
endmodule
