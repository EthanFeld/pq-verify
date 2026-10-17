`timescale 1ns/1ps
module tb_verify_robust;
    parameter integer RPC = 4;
    parameter integer MSG_BYTES = 1;
    parameter integer CTX_BYTES = 1;
    parameter integer MUTATION_COUNT = 200;
    parameter integer FIRST_MUTATION = 0;

    logic clk = 0;
    always #5 clk = !clk;
    logic rst_n = 0, start = 0, pure_mode = 1;
    wire start_ready, ctx_ready, msg_ready, sig_load_ready, done, valid;
    logic ctx_valid = 0, msg_valid = 0, msg_last = 0, sig_load_en = 0;
    logic [7:0] ctx_byte = 0, msg_byte = 0;
    logic [127:0] pk_seed = 0, pk_root = 0;
    logic [10:0] sig_load_addr = 0;
    logic [31:0] sig_load_data = 0;
    wire [31:0] cycles;
    wire [15:0] perms;

    logic [31:0] signature_mem [0:1963];
    logic [7:0] message_mem [0:(MSG_BYTES > 0 ? MSG_BYTES : 1)-1];
    logic [7:0] context_mem [0:(CTX_BYTES > 0 ? CTX_BYTES : 1)-1];
    logic [31:0] mutation_mem [0:MUTATION_COUNT-1];
    logic [127:0] base_seed, base_root;
    string signature_file, message_file, context_file, mutation_file;
    logic [127:0] seed_arg, root_arg;
    integer first_mutation, mutation_count;
    integer kind, offset, bit_index, waits, performed = 0;

    slh_verify_top #(.RPC(RPC)) dut (
        .clk(clk), .rst_n(rst_n), .start(start), .start_ready(start_ready),
        .pure_mode(pure_mode), .ctx_len(8'(CTX_BYTES)),
        .ctx_valid(ctx_valid), .ctx_ready(ctx_ready), .ctx_byte(ctx_byte),
        .msg_valid(msg_valid), .msg_ready(msg_ready), .msg_byte(msg_byte), .msg_last(msg_last),
        .pk_seed(pk_seed), .pk_root(pk_root), .sig_load_en(sig_load_en),
        .sig_load_addr(sig_load_addr), .sig_load_data(sig_load_data), .sig_load_ready(sig_load_ready),
        .done(done), .valid(valid), .cycles(cycles), .perms(perms)
    );

    task automatic begin_verify(input integer mut_kind, mut_offset, mut_bit);
        logic [31:0] load_word;
        integer word_index;
        begin
            if (!start_ready) $fatal(1, "start not ready before case");
            base_seed = seed_arg;
            base_root = root_arg;
            if (mut_kind == 2) begin
                if (mut_offset < 16)
                    base_seed[127 - 8*mut_offset - mut_bit] = ~base_seed[127 - 8*mut_offset - mut_bit];
                else
                    base_root[127 - 8*(mut_offset-16) - mut_bit] = ~base_root[127 - 8*(mut_offset-16) - mut_bit];
            end
            pk_seed = base_seed;
            pk_root = base_root;
            for (word_index = 0; word_index < 1964; word_index = word_index + 1) begin
                @(negedge clk);
                if (!sig_load_ready) $fatal(1, "signature load not ready word=%0d", word_index);
                load_word = signature_mem[word_index];
                if (mut_kind == 1 && mut_offset/4 == word_index)
                    load_word = load_word ^ (32'h1 << (8*(3-(mut_offset%4)) + mut_bit));
                sig_load_en = 1;
                sig_load_addr = 11'(word_index);
                sig_load_data = load_word;
            end
            @(negedge clk);
            sig_load_en = 0;
            $display("LOAD signature complete kind=%0d offset=%0d", mut_kind, mut_offset);
            $fflush();
            if (!start_ready) $fatal(1, "start not ready after signature load");
            start = 1;
            @(negedge clk);
            start = 0;
        end
    endtask

    task automatic feed_inputs(input integer mut_kind, mut_offset, mut_bit);
        integer index, stream_wait;
        begin
            for (index = 0; index < CTX_BYTES; index = index + 1) begin
                ctx_valid = 1;
                ctx_byte = context_mem[index];
                if (mut_kind == 4 && mut_offset == index)
                    ctx_byte = ctx_byte ^ (8'h1 << mut_bit);
                stream_wait = 0;
                while (!ctx_ready) begin
                    @(negedge clk);
                    stream_wait = stream_wait + 1;
                    if (stream_wait > 100000) $fatal(1, "context ready watchdog index=%0d", index);
                end
                @(posedge clk); #1;
                @(negedge clk);
            end
            ctx_valid = 0;
            $display("INPUT context sent mutation kind=%0d offset=%0d", mut_kind, mut_offset);
            $fflush();
            for (index = 0; index < MSG_BYTES; index = index + 1) begin
                msg_valid = 1;
                msg_byte = message_mem[index];
                if (mut_kind == 3 && mut_offset == index)
                    msg_byte = msg_byte ^ (8'h1 << mut_bit);
                msg_last = index == MSG_BYTES - 1;
                stream_wait = 0;
                while (!msg_ready) begin
                    @(negedge clk);
                    stream_wait = stream_wait + 1;
                    if (stream_wait > 100000) $fatal(1, "message ready watchdog index=%0d", index);
                end
                @(posedge clk); #1;
                @(negedge clk);
            end
            msg_valid = 0;
            msg_last = 0;
            $display("INPUT message sent mutation kind=%0d offset=%0d", mut_kind, mut_offset);
            $fflush();
        end
    endtask

    task automatic finish_verify(input integer expected_valid, label);
        integer wait_cycles;
        begin
            wait_cycles = 0;
            while (done !== 1'b1) begin
                @(posedge clk); #1;
                wait_cycles = wait_cycles + 1;
                if (wait_cycles > 1000000) $fatal(1, "case watchdog label=%0d state=%0d", label, dut.state);
            end
            if (valid !== (expected_valid != 0))
                $fatal(1, "verdict mismatch label=%0d got=%0d expected=%0d", label, valid, expected_valid);
            $display("CASE pass label=%0d valid=%0d cycles=%0d perms=%0d", label, valid, cycles, perms);
            $fflush();
        end
    endtask

    task automatic run_case(input integer mut_kind, mut_offset, mut_bit,
                            input integer expected_valid, label);
        begin
            begin_verify(mut_kind, mut_offset, mut_bit);
            feed_inputs(mut_kind, mut_offset, mut_bit);
            finish_verify(expected_valid, label);
        end
    endtask

    task automatic reset_during_verify;
        integer reset_wait, observed_perms;
        begin
            begin_verify(0, 0, 0);
            feed_inputs(0, 0, 0);
            reset_wait = 0;
            while (dut.perms < 16 && done !== 1'b1) begin
                @(posedge clk); #1;
                reset_wait = reset_wait + 1;
                if (reset_wait > 100000) $fatal(1, "reset setup watchdog");
            end
            if (done === 1'b1) $fatal(1, "verify finished before mid-run reset");
            observed_perms = dut.perms;
            @(negedge clk);
            rst_n = 0;
            ctx_valid = 0;
            msg_valid = 0;
            msg_last = 0;
            sig_load_en = 0;
            repeat (4) @(negedge clk);
            rst_n = 1;
            repeat (3) @(negedge clk);
            if (done !== 1'b0 || !start_ready) $fatal(1, "reset did not restore idle");
            $display("RESET mid-verify observed perms=%0d; idle recovered", observed_perms);
        end
    endtask

    initial begin
        if (!$value$plusargs("signature_file=%s", signature_file)
                || !$value$plusargs("message_file=%s", message_file)
                || !$value$plusargs("context_file=%s", context_file)
                || !$value$plusargs("mutation_file=%s", mutation_file)
                || !$value$plusargs("pk_seed=%h", seed_arg)
                || !$value$plusargs("pk_root=%h", root_arg)
                || !$value$plusargs("first_mutation=%d", first_mutation)
                || !$value$plusargs("mutation_count=%d", mutation_count))
            $fatal(1, "missing robustness argument");
        if (first_mutation < 0 || mutation_count < 1
                || first_mutation + mutation_count > MUTATION_COUNT)
            $fatal(1, "invalid mutation slice");
        $readmemh(signature_file, signature_mem);
        $readmemh(message_file, message_mem);
        $readmemh(context_file, context_mem);
        $readmemh(mutation_file, mutation_mem);
        repeat (3) @(negedge clk);
        rst_n = 1;
        for (integer case_index = first_mutation;
             case_index < first_mutation + mutation_count; case_index = case_index + 1) begin
            kind = mutation_mem[case_index][31:24];
            offset = mutation_mem[case_index][23:8];
            bit_index = mutation_mem[case_index][7:0];
            if (kind < 1 || kind > 4 || bit_index > 7)
                $fatal(1, "bad mutation descriptor index=%0d", case_index);
            if ((kind == 1 && offset >= 7856) || (kind == 2 && offset >= 32)
                    || (kind == 3 && offset >= MSG_BYTES) || (kind == 4 && offset >= CTX_BYTES))
                $fatal(1, "mutation offset out of range index=%0d", case_index);
            run_case(kind, offset, bit_index, 0, case_index);
            performed = performed + 1;
        end
        run_case(0, 0, 0, 1, 1000);
        run_case(0, 0, 0, 1, 1001);
        reset_during_verify();
        run_case(0, 0, 0, 1, 1002);
        $display("PASS robustness mutations=%0d slice=%0d:%0d back_to_back=2 reset_recovery=1 RPC=%0d",
                 performed, first_mutation, first_mutation + mutation_count - 1, RPC);
        $finish;
    end

    initial begin
        #5000000000;
        $fatal(1, "global robustness watchdog");
    end
endmodule
