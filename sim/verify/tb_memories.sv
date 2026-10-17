`timescale 1ns/1ps
module tb_memories;
    logic clk = 0;
    always #5 clk = !clk;

    logic sig_wr_en = 0;
    logic [10:0] sig_wr_addr = 0, sig_rd_addr = 0;
    logic [31:0] sig_wr_data = 0;
    wire [31:0] sig_rd_data;

    logic scratch_wr_en = 0;
    logic [7:0] scratch_wr_addr = 0, scratch_rd_addr = 0;
    logic [31:0] scratch_wr_data = 0;
    wire [31:0] scratch_block_data, scratch_distributed_data, scratch_register_data;

    sig_ram signature_memory (
        .clk(clk), .wr_en(sig_wr_en), .wr_addr(sig_wr_addr), .wr_data(sig_wr_data),
        .rd_addr(sig_rd_addr), .rd_data(sig_rd_data)
    );
    scratch_ram #(.RAM_STYLE(0)) block_memory (
        .clk(clk), .wr_en(scratch_wr_en), .wr_addr(scratch_wr_addr), .wr_data(scratch_wr_data),
        .rd_addr(scratch_rd_addr), .rd_data(scratch_block_data)
    );
    scratch_ram #(.RAM_STYLE(1)) distributed_memory (
        .clk(clk), .wr_en(scratch_wr_en), .wr_addr(scratch_wr_addr), .wr_data(scratch_wr_data),
        .rd_addr(scratch_rd_addr), .rd_data(scratch_distributed_data)
    );
    scratch_ram #(.RAM_STYLE(2)) register_memory (
        .clk(clk), .wr_en(scratch_wr_en), .wr_addr(scratch_wr_addr), .wr_data(scratch_wr_data),
        .rd_addr(scratch_rd_addr), .rd_data(scratch_register_data)
    );

    task automatic check_scratch(input logic [31:0] expected);
        if (scratch_block_data !== expected || scratch_distributed_data !== expected
                || scratch_register_data !== expected)
            $fatal(1, "scratch read mismatch block=%h distributed=%h registers=%h expected=%h",
                   scratch_block_data, scratch_distributed_data, scratch_register_data, expected);
    endtask

    initial begin
        // Address ends verify the declared depths: 2048 signature words, 256 scratch words.
        @(negedge clk);
        sig_wr_en = 1;
        sig_wr_addr = 11'd0;
        sig_wr_data = 32'h1357_9bdf;
        scratch_wr_en = 1;
        scratch_wr_addr = 8'd0;
        scratch_wr_data = 32'h2468_ace0;
        @(posedge clk); #1;

        @(negedge clk);
        sig_wr_addr = 11'd2047;
        sig_wr_data = 32'hdead_beef;
        scratch_wr_addr = 8'd255;
        scratch_wr_data = 32'hcafe_f00d;
        @(posedge clk); #1;

        // Registered read returns data after the sampling edge.
        @(negedge clk);
        sig_wr_en = 0;
        sig_rd_addr = 11'd0;
        scratch_wr_en = 0;
        scratch_rd_addr = 8'd0;
        @(posedge clk); #1;
        if (sig_rd_data !== 32'h1357_9bdf) $fatal(1, "signature address zero read mismatch");
        check_scratch(32'h2468_ace0);

        @(negedge clk);
        sig_rd_addr = 11'd2047;
        scratch_rd_addr = 8'd255;
        @(posedge clk); #1;
        if (sig_rd_data !== 32'hdead_beef) $fatal(1, "signature last address read mismatch");
        check_scratch(32'hcafe_f00d);

        // Same-edge read/write is read-first; the next read sees the committed word.
        @(negedge clk);
        sig_wr_en = 1;
        sig_wr_addr = 11'd2047;
        sig_wr_data = 32'h0123_4567;
        sig_rd_addr = 11'd2047;
        scratch_wr_en = 1;
        scratch_wr_addr = 8'd255;
        scratch_wr_data = 32'h89ab_cdef;
        scratch_rd_addr = 8'd255;
        @(posedge clk); #1;
        if (sig_rd_data !== 32'hdead_beef) $fatal(1, "signature read-during-write was not read-first");
        check_scratch(32'hcafe_f00d);

        @(negedge clk);
        sig_wr_en = 0;
        scratch_wr_en = 0;
        @(posedge clk); #1;
        if (sig_rd_data !== 32'h0123_4567) $fatal(1, "signature write did not commit");
        check_scratch(32'h89ab_cdef);

        $display("PASS memory interfaces: signature depth/registered read/read-first; scratch styles 0/1/2");
        $finish;
    end
endmodule
