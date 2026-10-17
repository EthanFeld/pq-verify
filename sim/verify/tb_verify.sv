`timescale 1ns/1ps
module tb_verify;
    parameter integer RPC = 1;
    parameter integer SCRATCH_STYLE = 0;
    parameter integer MSG_BYTES = 1;
    parameter integer CTX_BYTES = 0;
    logic clk = 0;
    always #5 clk = !clk;
    logic rst_n = 0, start = 0, pure_mode = 0;
    wire start_ready, ctx_ready, msg_ready, sig_load_ready, done, valid;
    logic ctx_valid = 0, msg_valid = 0, msg_last = 0, sig_load_en = 0;
    logic [7:0] ctx_byte = 0, msg_byte = 0;
    logic [127:0] pk_seed = 0, pk_root = 0, expected_fors = 0;
    logic [239:0] expected_digest = 0;
    logic [10:0] sig_load_addr = 0;
    logic [31:0] sig_load_data = 0;
    logic [7:0] ctx_len_value = 0;
    wire [31:0] cycles;
    wire [15:0] perms;
    logic [31:0] signature_mem [0:1963];
    logic [7:0] message_mem [0:(MSG_BYTES > 0 ? MSG_BYTES : 1)-1];
    logic [7:0] context_mem [0:(CTX_BYTES > 0 ? CTX_BYTES : 1)-1];
    logic [127:0] wots_expected [0:6], roots_expected [0:6];
    string signature_file, message_file, context_file, wots_file, roots_file;
    integer test_id, mode_value, expected_valid, expected_perms, waits;
    integer message_length, context_length;
    integer wots_index = 0, root_index = 0;
    integer fors_start_perms = 0, fors_count_checks = 0;
    logic fors_count_active = 0;
    integer hmsg_start_cycle = 0, fors_stage_start_cycle = 0, ht_stage_start_cycle = 0;
    integer hmsg_stage_cycles = 0, fors_stage_cycles = 0, ht_stage_cycles = 0;
    // Four signature words are read in two synchronous-RAM phases each.
    localparam integer TOP_LEVEL_SETUP_CYCLES = 8;
    logic hmsg_stage_active = 0, fors_stage_active = 0, ht_stage_active = 0;
    localparam integer FORS_EXPECTED_PERMS = 185;

    slh_verify_top #(.RPC(RPC), .SCRATCH_STYLE(SCRATCH_STYLE)) dut (
        .clk(clk), .rst_n(rst_n), .start(start), .start_ready(start_ready),
        .pure_mode(pure_mode), .ctx_len(ctx_len_value),
        .ctx_valid(ctx_valid), .ctx_ready(ctx_ready), .ctx_byte(ctx_byte),
        .msg_valid(msg_valid), .msg_ready(msg_ready), .msg_byte(msg_byte), .msg_last(msg_last),
        .pk_seed(pk_seed), .pk_root(pk_root), .sig_load_en(sig_load_en),
        .sig_load_addr(sig_load_addr), .sig_load_data(sig_load_data), .sig_load_ready(sig_load_ready),
        .done(done), .valid(valid), .cycles(cycles), .perms(perms)
    );

    // Independent Python checkpoints localize a mismatch before the final verdict.
    always @(posedge clk) begin
        #1;
        if (rst_n && dut.hmsg_done) begin
            if (dut.u_hmsg.digest[239:0] !== expected_digest)
                $fatal(1, "H_msg checkpoint mismatch got=%h expected=%h", dut.u_hmsg.digest[239:0], expected_digest);
            $display("CHECK tc=%0d H_msg pass", test_id);
            $fflush();
        end
        if (rst_n && dut.fors_done) begin
            if (dut.fors_pk !== expected_fors)
                $fatal(1, "FORS checkpoint mismatch got=%h expected=%h", dut.fors_pk, expected_fors);
            $display("CHECK tc=%0d FORS pass", test_id);
            $fflush();
        end
        if (rst_n && dut.u_ht_verify.u_wots_verify.done) begin
            if (wots_index > 6 || dut.u_ht_verify.u_wots_verify.wots_pk !== wots_expected[wots_index])
                $fatal(1, "WOTS checkpoint mismatch layer=%0d", wots_index);
            wots_index = wots_index + 1;
        end
        if (rst_n && dut.u_ht_verify.u_xmss_verify.done) begin
            if (root_index > 6 || dut.u_ht_verify.u_xmss_verify.root !== roots_expected[root_index])
                $fatal(1, "XMSS checkpoint mismatch layer=%0d", root_index);
            $display("CHECK tc=%0d layer=%0d pass", test_id, root_index);
            $fflush();
            root_index = root_index + 1;
        end
    end

    // Measure the isolated FORS interval using actual shared-engine starts.
    always @(negedge clk) begin
        if (!rst_n) begin
            fors_start_perms = 0;
            fors_count_checks = 0;
            fors_count_active = 0;
            hmsg_start_cycle = 0;
            fors_stage_start_cycle = 0;
            ht_stage_start_cycle = 0;
            hmsg_stage_cycles = 0;
            fors_stage_cycles = 0;
            ht_stage_cycles = 0;
            hmsg_stage_active = 0;
            fors_stage_active = 0;
            ht_stage_active = 0;
        end else begin
            if (dut.hmsg_start) begin
                hmsg_start_cycle = cycles;
                hmsg_stage_active = 1;
            end
            if (dut.hmsg_done && hmsg_stage_active) begin
                hmsg_stage_cycles = cycles - hmsg_start_cycle;
                hmsg_stage_active = 0;
                $display("STAGE tc=%0d name=hmsg cycles=%0d", test_id, hmsg_stage_cycles);
            end
            if (dut.fors_start) begin
                fors_stage_start_cycle = cycles;
                fors_stage_active = 1;
            end
            if (dut.fors_done && fors_stage_active) begin
                fors_stage_cycles = cycles - fors_stage_start_cycle;
                fors_stage_active = 0;
                $display("STAGE tc=%0d name=fors cycles=%0d", test_id, fors_stage_cycles);
            end
            if (dut.ht_start) begin
                ht_stage_start_cycle = cycles;
                ht_stage_active = 1;
            end
            if (dut.ht_done && ht_stage_active) begin
                ht_stage_cycles = cycles - ht_stage_start_cycle;
                ht_stage_active = 0;
                $display("STAGE tc=%0d name=hypertree cycles=%0d", test_id, ht_stage_cycles);
            end

            if (dut.fors_start && !fors_count_active) begin
                fors_start_perms = perms;
                fors_count_active = 1;
            end
            if (dut.fors_done) begin
                if (!fors_count_active) $fatal(1, "FORS completed without a counted start");
                if ((perms - fors_start_perms) != FORS_EXPECTED_PERMS)
                    $fatal(1, "FORS permutations got=%0d expected=%0d",
                           perms - fors_start_perms, FORS_EXPECTED_PERMS);
                fors_count_checks = fors_count_checks + 1;
                fors_count_active = 0;
                $display("CHECK tc=%0d FORS permutations=%0d", test_id, FORS_EXPECTED_PERMS);
                $fflush();
            end
        end
    end

    initial begin
        message_length = MSG_BYTES;
        context_length = CTX_BYTES;
        if (!$value$plusargs("signature_file=%s", signature_file)
                || !$value$plusargs("message_file=%s", message_file)
                || !$value$plusargs("context_file=%s", context_file)
                || !$value$plusargs("wots_file=%s", wots_file)
                || !$value$plusargs("roots_file=%s", roots_file)
                || !$value$plusargs("pk_seed=%h", pk_seed)
                || !$value$plusargs("pk_root=%h", pk_root)
                || !$value$plusargs("expected_fors=%h", expected_fors)
                || !$value$plusargs("expected_digest=%h", expected_digest)
                || !$value$plusargs("test_id=%d", test_id)
                || !$value$plusargs("pure=%d", mode_value)
                || !$value$plusargs("expected_valid=%d", expected_valid)
                || !$value$plusargs("expected_perms=%d", expected_perms))
            $fatal(1, "missing vector argument");
        void'($value$plusargs("message_length=%d", message_length));
        void'($value$plusargs("context_length=%d", context_length));
        if (message_length < 0 || message_length > MSG_BYTES
                || context_length < 0 || context_length > CTX_BYTES
                || context_length > 255)
            $fatal(1, "runtime input length exceeds model capacity");
        ctx_len_value = 8'(context_length);
        $readmemh(signature_file, signature_mem);
        $readmemh(message_file, message_mem);
        $readmemh(context_file, context_mem);
        $readmemh(wots_file, wots_expected);
        $readmemh(roots_file, roots_expected);
        pure_mode = mode_value != 0;
        repeat (3) @(negedge clk);
        rst_n = 1;
        for (integer word_index = 0; word_index < 1964; word_index = word_index + 1) begin
            @(negedge clk);
            if (!sig_load_ready) $fatal(1, "signature load not ready");
            sig_load_en = 1;
            sig_load_addr = 11'(word_index);
            sig_load_data = signature_mem[word_index];
        end
        @(negedge clk);
        sig_load_en = 0;
        if (!start_ready) $fatal(1, "verifier not ready");
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
            if (waits > 1000000) $fatal(1, "verifier watchdog state=%0d", dut.state);
        end
        if (valid !== (expected_valid != 0)) $fatal(1, "verdict mismatch");
        if (perms != expected_perms) $fatal(1, "permutation count got=%0d expected=%0d", perms, expected_perms);
        if (wots_index != 7 || root_index != 7) $fatal(1, "missing hypertree checkpoints");
        if (fors_count_checks != 1) $fatal(1, "FORS permutation interval was not checked");
        if (hmsg_stage_active || fors_stage_active || ht_stage_active)
            $fatal(1, "stage cycle interval was not closed");
        if (hmsg_stage_cycles + fors_stage_cycles + ht_stage_cycles
                + TOP_LEVEL_SETUP_CYCLES != cycles)
            $fatal(1, "cycle accounting mismatch: hmsg=%0d fors=%0d hypertree=%0d top=%0d total=%0d",
                   hmsg_stage_cycles, fors_stage_cycles, ht_stage_cycles,
                   TOP_LEVEL_SETUP_CYCLES, cycles);
        $display("PASS verify tc=%0d RPC=%0d valid=%0d cycles=%0d perms=%0d", test_id, RPC, valid, cycles, perms);
        $finish;
    end

    initial begin
        #20000000;
        $fatal(1, "simulation watchdog");
    end
endmodule
