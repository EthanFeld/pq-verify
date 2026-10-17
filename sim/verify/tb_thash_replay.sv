`timescale 1ns/1ps
module tb_thash_replay;
    parameter integer CASES = 1;
    localparam integer MESSAGE_BYTES = 560;

    logic clk = 0;
    always #5 clk = !clk;
    logic rst_n = 0;
    logic req_valid = 0;
    wire req_ready;
    logic [1:0] req_kind = 0, req_src_sel = 0;
    logic [255:0] req_adrs = 0;
    logic [15:0] req_src_addr = 0, req_count = 0;
    logic [127:0] pk_seed = 0;
    logic [255:0] req_pair = 0;
    wire src_rd_en;
    wire [1:0] src_rd_sel;
    wire [15:0] src_rd_addr;
    logic src_valid = 0;
    logic [7:0] src_byte = 0;
    logic [31:0] src_word = 0;
    wire shake_in_valid, shake_in_last;
    wire shake_in_ready;
    wire [63:0] shake_in_data;
    wire [3:0] shake_in_bytes;
    wire shake_out_valid;
    wire [255:0] shake_out;
    wire rsp_valid;
    wire [127:0] rsp_node;
    logic [7:0] source_memory [0:MESSAGE_BYTES-1];
    logic [5011:0] vectors [0:CASES-1];
    string vectors_file;
    integer source_base = 16;
    integer watchdog;

    thash #(.RPC(1)) dut (
        .clk(clk), .rst_n(rst_n), .req_valid(req_valid), .req_ready(req_ready),
        .req_kind(req_kind), .req_adrs(req_adrs), .req_src_sel(req_src_sel),
        .req_src_addr(req_src_addr), .req_count(req_count), .pk_seed(pk_seed),
        .req_pair(req_pair), .src_rd_en(src_rd_en), .src_rd_sel(src_rd_sel),
        .src_rd_addr(src_rd_addr), .src_valid(src_valid), .src_byte(src_byte),
        .src_word(src_word),
        .shake_in_valid(shake_in_valid), .shake_in_ready(shake_in_ready),
        .shake_in_data(shake_in_data), .shake_in_bytes(shake_in_bytes),
        .shake_in_last(shake_in_last), .shake_bulk_valid(),
        .shake_bulk_ready(1'b0), .shake_bulk_lanes(), .shake_bulk_bytes(),
        .shake_out_valid(shake_out_valid),
        .shake_out(shake_out), .rsp_valid(rsp_valid), .rsp_node(rsp_node)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            src_valid <= 0;
            src_byte <= 0;
            src_word <= 0;
        end else begin
            src_valid <= src_rd_en;
            if (src_rd_en) begin
                if (src_rd_addr < source_base || src_rd_addr + 4 > source_base + MESSAGE_BYTES)
                    $fatal(1, "source read outside replay message: %0d", src_rd_addr);
                src_byte <= source_memory[src_rd_addr - source_base];
                src_word <= {
                    source_memory[int'(src_rd_addr) - source_base],
                    source_memory[int'(src_rd_addr) - source_base + 1],
                    source_memory[int'(src_rd_addr) - source_base + 2],
                    source_memory[int'(src_rd_addr) - source_base + 3]
                };
            end
        end
    end

    initial begin
        if (!$value$plusargs("vectors_file=%s", vectors_file))
            $fatal(1, "missing vectors_file");
        $readmemh(vectors_file, vectors);
        repeat (3) @(negedge clk);
        rst_n = 1;

        for (integer index = 0; index < CASES; index = index + 1) begin
            for (integer byte_index = 0; byte_index < MESSAGE_BYTES; byte_index = byte_index + 1)
                source_memory[byte_index] = vectors[index][4607 - byte_index * 8 -: 8];

            req_kind = vectors[index][5009:5008];
            req_count = vectors[index][5007:4992];
            req_adrs = vectors[index][4991:4736];
            pk_seed = vectors[index][4735:4608];
            req_src_addr = 16'(source_base);
            req_pair = vectors[index][4607 -: 256];
            if (req_kind < 2)
                case (index % 3)
                    0: req_src_sel = 2'd3; // local node register
                    1: req_src_sel = 2'd0; // signature RAM
                    default: req_src_sel = 2'd1; // scratch RAM
                endcase
            else
                req_src_sel = 2'd1;

            while (!req_ready) @(negedge clk);
            @(negedge clk);
            req_valid = 1;
            @(negedge clk);
            req_valid = 0;

            watchdog = 0;
            while (!rsp_valid) begin
                @(negedge clk);
                watchdog = watchdog + 1;
                if (watchdog > 1000000) $fatal(1,
                    "thash replay watchdog index=%0d state=%0d bytes=%0d issue=%0d valid=%0b rd=%0b word=%0b fill=%0d total=%0d shake=%0b/%0b/%0b",
                    index, dut.state, dut.byte_pos, dut.src_issue_pos, src_valid, src_rd_en,
                    dut.word_source_mode, dut.lane_fill, dut.total_bytes,
                    shake_in_valid, shake_in_ready, shake_in_last);
            end
            if (rsp_node !== vectors[index][127:0])
                $fatal(1, "thash mismatch index=%0d kind=%0d bytes=%0d got=%h expected=%h",
                       index, req_kind, req_count, rsp_node, vectors[index][127:0]);
        end

        $display("PASS thash trace replay calls=%0d (F/H=500, Tk/Tlen=all selected trace calls)", CASES);
        $finish;
    end

    initial begin
        #200000000;
        $fatal(1, "thash trace replay simulation watchdog");
    end
endmodule
