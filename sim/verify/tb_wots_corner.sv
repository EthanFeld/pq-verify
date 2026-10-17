`timescale 1ns/1ps
module tb_wots_corner;
    logic clk = 0;
    always #5 clk = !clk;

    logic rst_n = 0;
    logic start = 0;
    wire start_ready;
    logic [127:0] message = 0;
    logic [31:0] layer = 0;
    logic [95:0] tree = 0;
    logic [31:0] keypair = 0;
    logic [15:0] sig_base = 0;
    logic [127:0] pk_seed = 0;
    wire sig_rd_en;
    wire [15:0] sig_rd_addr;
    logic sig_valid = 0;
    logic [7:0] sig_byte = 0;
    wire scratch_wr_en;
    wire [7:0] scratch_wr_addr;
    wire [31:0] scratch_wr_data;
    wire hash_req_valid;
    logic hash_req_ready = 1;
    wire [1:0] hash_kind;
    wire [255:0] hash_adrs;
    wire [1:0] hash_src_sel;
    wire [15:0] hash_src_addr;
    wire [15:0] hash_count;
    wire [255:0] hash_pair;
    wire [127:0] hash_pk_seed;
    logic hash_rsp_valid = 0;
    logic [127:0] hash_rsp_node = 0;
    wire done;
    wire [127:0] wots_pk;

    logic pending_hash = 0;
    logic [4:0] hash_delay_count = 0;
    logic [127:0] expected_message = 0;
    logic [15:0] expected_base = 0;
    integer sig_reads = 0;
    integer prefetch_reads = 0;
    integer cached_sig_bytes = 0;
    integer scratch_writes = 0;
    integer hash_calls = 0;
    integer tlen_calls = 0;
    integer watchdog;
    logic [127:0] last_hash_result = 0;
    integer chain_hashes [0:34];

    wots_verify dut (
        .clk(clk), .rst_n(rst_n), .start(start), .start_ready(start_ready),
        .message(message), .layer(layer), .tree(tree), .keypair(keypair),
        .sig_base(sig_base), .pk_seed(pk_seed), .sig_rd_en(sig_rd_en),
        .sig_rd_addr(sig_rd_addr), .sig_valid(sig_valid), .sig_byte(sig_byte),
        .scratch_wr_en(scratch_wr_en), .scratch_wr_addr(scratch_wr_addr),
        .scratch_wr_data(scratch_wr_data), .hash_req_valid(hash_req_valid),
        .hash_req_ready(hash_req_ready), .hash_kind(hash_kind), .hash_adrs(hash_adrs),
        .hash_src_sel(hash_src_sel), .hash_src_addr(hash_src_addr),
        .hash_count(hash_count), .hash_pair(hash_pair), .hash_pk_seed(hash_pk_seed),
        .hash_rsp_valid(hash_rsp_valid), .hash_rsp_node(hash_rsp_node),
        .done(done), .wots_pk(wots_pk)
    );

    function automatic logic [3:0] digit_for(input logic [127:0] msg, input integer digit_index);
        logic [8:0] sum;
        logic [11:0] checksum;
        logic [3:0] nibble;
        begin
            if (digit_index < 32) begin
                digit_for = msg[127 - digit_index * 4 -: 4];
            end else begin
                sum = 0;
                for (integer index = 0; index < 32; index = index + 1) begin
                    nibble = msg[127 - index * 4 -: 4];
                    sum = sum + (15 - nibble);
                end
                checksum = {3'b000, sum};
                if (digit_index == 32)
                    digit_for = checksum[11:8];
                else if (digit_index == 33)
                    digit_for = checksum[7:4];
                else
                    digit_for = checksum[3:0];
            end
        end
    endfunction

    function automatic logic [127:0] mock_hash(
        input logic [255:0] pair_value, input logic [255:0] address_value
    );
        mock_hash = pair_value[127:0] ^ pair_value[255:128]
            ^ address_value[127:0] ^ 128'h6d6f636b5f776f74735f686173685f31;
    endfunction

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sig_valid <= 0;
            sig_byte <= 0;
            pending_hash <= 0;
            hash_delay_count <= 0;
            hash_rsp_valid <= 0;
            hash_rsp_node <= 0;
            sig_reads <= 0;
            prefetch_reads <= 0;
            cached_sig_bytes <= 0;
            scratch_writes <= 0;
            hash_calls <= 0;
            tlen_calls <= 0;
            last_hash_result <= 0;
            for (integer index = 0; index < 35; index = index + 1)
                chain_hashes[index] <= 0;
        end else begin
            sig_valid <= sig_rd_en;
            if (sig_rd_en) begin
                if (sig_rd_addr !== expected_base + sig_reads)
                    $fatal(1, "signature address read=%0d got=%0d expected=%0d",
                           sig_reads, sig_rd_addr, expected_base + sig_reads);
                sig_byte <= sig_rd_addr[7:0] ^ 8'h5a;
                sig_reads <= sig_reads + 1;
            end

            if (scratch_wr_en) begin
                if (scratch_wr_addr !== scratch_writes[7:0])
                    $fatal(1, "scratch write=%0d got=%0d", scratch_writes, scratch_wr_addr);
                scratch_writes <= scratch_writes + 1;
            end

            hash_rsp_valid <= 0;
            if (hash_req_valid && hash_req_ready) begin
                pending_hash <= 1;
                hash_delay_count <= 5'd23;
            end else if (pending_hash) begin
                if (hash_delay_count == 0) begin
                    pending_hash <= 0;
                    hash_rsp_valid <= 1;
                end else begin
                    hash_delay_count <= hash_delay_count - 1'b1;
                end
            end

            if (dut.prefetch_sig_rd_en)
                prefetch_reads <= prefetch_reads + 1;
            if (dut.prefetch_hit)
                cached_sig_bytes <= cached_sig_bytes + 1;

            if (hash_req_valid && hash_req_ready) begin
                last_hash_result <= mock_hash(hash_pair, hash_adrs);
                hash_rsp_node <= mock_hash(hash_pair, hash_adrs);
                if (hash_pk_seed !== pk_seed)
                    $fatal(1, "hash request lost pk_seed");
                if (hash_kind == 2'd0) begin
                    integer chain_index;
                    integer expected_calls;
                    logic [3:0] first_hash;
                    if (hash_src_sel != 2'd3 || hash_count != 16)
                        $fatal(1, "invalid WOTS F request source/count");
                    chain_index = hash_adrs[63:32];
                    if (chain_index >= 35)
                        $fatal(1, "invalid WOTS chain index %0d", chain_index);
                    first_hash = digit_for(expected_message, chain_index);
                    expected_calls = 15 - first_hash;
                    if (expected_calls == 0)
                        $fatal(1, "unexpected hash for chain=%0d digit=15", chain_index);
                    if (chain_hashes[chain_index] >= expected_calls
                        || hash_adrs[31:0] != first_hash + chain_hashes[chain_index])
                        $fatal(1, "WOTS chain mismatch chain=%0d hash=%0d digit=%0d seen=%0d",
                               chain_index, hash_adrs[31:0], first_hash,
                               chain_hashes[chain_index]);
                    chain_hashes[chain_index] <= chain_hashes[chain_index] + 1;
                    hash_calls <= hash_calls + 1;
                end else if (hash_kind == 2'd3) begin
                    tlen_calls <= tlen_calls + 1;
                    if (hash_src_sel != 2'd1 || hash_count != 560
                        || hash_adrs[127:96] != 1 || hash_adrs[63:0] != 0)
                        $fatal(1, "invalid WOTS T_len request");
                end else begin
                    $fatal(1, "unexpected WOTS hash kind %0d", hash_kind);
                end
            end
        end
    end

    task automatic run_case(input logic [127:0] msg, input logic [15:0] base);
        integer expected_hashes;
        integer expected_prefetches;
        begin
            @(negedge clk);
            rst_n = 0;
            start = 0;
            message = msg;
            expected_message = msg;
            expected_base = base;
            layer = 7;
            tree = 96'h123456789abcdef012345678;
            keypair = 32'h76543210;
            sig_base = base;
            pk_seed = 128'h00112233445566778899aabbccddeeff;
            repeat (2) @(negedge clk);
            rst_n = 1;
            @(negedge clk);
            start = 1;
            @(negedge clk);
            start = 0;

            watchdog = 0;
            while (!done) begin
                @(negedge clk);
                watchdog = watchdog + 1;
                if (watchdog > 20000) $fatal(1, "WOTS corner watchdog");
            end

            expected_hashes = 0;
            expected_prefetches = 0;
            for (integer index = 0; index < 35; index = index + 1)
                expected_hashes = expected_hashes + 15 - digit_for(msg, index);
            for (integer index = 0; index < 34; index = index + 1)
                if (digit_for(msg, index) != 4'd15)
                    expected_prefetches = expected_prefetches + 1;
            if (sig_reads != 560 || prefetch_reads != expected_prefetches * 16
                || cached_sig_bytes != expected_prefetches * 16
                || scratch_writes != 140 || hash_calls != expected_hashes
                || tlen_calls != 1 || wots_pk !== last_hash_result)
                $fatal(1, "WOTS corner counts sig=%0d prefetch=%0d cached=%0d scratch=%0d hash=%0d/%0d tlen=%0d",
                       sig_reads, prefetch_reads, cached_sig_bytes, scratch_writes,
                       hash_calls, expected_hashes, tlen_calls);
            for (integer index = 0; index < 35; index = index + 1)
                if (chain_hashes[index] != 15 - digit_for(msg, index))
                    $fatal(1, "WOTS chain %0d hash count=%0d expected=%0d", index,
                           chain_hashes[index], 15 - digit_for(msg, index));
            $display("PASS WOTS msg=%h checksum_digits=%h%h%h chains=35 hashes=%0d",
                     msg, digit_for(msg, 32), digit_for(msg, 33), digit_for(msg, 34), expected_hashes);
        end
    endtask

    initial begin
        run_case(128'h00000000000000000000000000000000, 16'h0100);
        run_case(128'hffffffffffffffffffffffffffffffff, 16'h0500);
        run_case(128'h0123456789abcdeffedcba9876543210, 16'h0900);
        $display("PASS WOTS digit/checksum/chain boundaries cases=3");
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1, "WOTS global watchdog");
    end
endmodule
