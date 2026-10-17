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
    integer hash_call_count [0:4];
    integer hash_absorb_total [0:4];
    integer hash_permute_total [0:4];
    integer hash_response_total [0:4];
    integer hash_idle_total [0:4];
    integer hash_call_active = 0, hash_last_input = 0, hash_gap_active = 0;
    integer hash_current_kind = 0, hash_last_kind = 0, hash_have_last_kind = 0;
    integer hash_gap_cycles = 0;
    integer hash_call_absorb = 0, hash_call_permute = 0;
    integer hash_call_response = 0, hash_call_idle = 0;

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

    // Exclusive per-call accounting: absorb/controller work before the final
    // lane, Keccak busy cycles, non-busy response slack, then inter-call gap.
    // Input and response work are kept separate from overlapping permutation.
    always @(negedge clk) begin
        if (!rst_n) begin
            hash_call_active = 0;
            hash_last_input = 0;
            hash_gap_active = 0;
            hash_have_last_kind = 0;
            hash_gap_cycles = 0;
            hash_call_absorb = 0;
            hash_call_permute = 0;
            hash_call_response = 0;
            hash_call_idle = 0;
            for (integer kind_index = 0; kind_index < 5; kind_index = kind_index + 1) begin
                hash_call_count[kind_index] = 0;
                hash_absorb_total[kind_index] = 0;
                hash_permute_total[kind_index] = 0;
                hash_response_total[kind_index] = 0;
                hash_idle_total[kind_index] = 0;
            end
        end else if (hash_call_active) begin
            if (hash_current_kind == 4) begin
                if (dut.u_shared_shake256.u_keccak.busy)
                    hash_call_permute = hash_call_permute + 1;
                if (!hash_last_input) begin
                    if (!dut.u_shared_shake256.u_keccak.busy)
                        hash_call_absorb = hash_call_absorb + 1;
                    if (dut.hmsg_shake_in_valid && dut.hmsg_shake_in_ready
                            && dut.hmsg_shake_in_last)
                        hash_last_input = 1;
                end else if (!dut.u_shared_shake256.u_keccak.busy && !dut.hmsg_done) begin
                    hash_call_response = hash_call_response + 1;
                end
            end else begin
                if (dut.u_shared_shake256.u_keccak.busy)
                    hash_call_permute = hash_call_permute + 1;
                if (!hash_last_input) begin
                    if (!dut.u_shared_shake256.u_keccak.busy)
                        hash_call_absorb = hash_call_absorb + 1;
                    if (dut.shake_shared_in_valid && dut.shake_shared_in_ready
                            && dut.shake_shared_in_last)
                        hash_last_input = 1;
                    if (dut.thash_shake_bulk_valid && dut.thash_shake_bulk_ready)
                        hash_last_input = 1;
                end else if (!dut.u_shared_shake256.u_keccak.busy
                        && !dut.hash_rsp_valid) begin
                    hash_call_response = hash_call_response + 1;
                end
            end

            if ((hash_current_kind == 4 && dut.hmsg_done)
                    || (hash_current_kind != 4 && dut.hash_rsp_valid)) begin
                hash_call_response = hash_call_response + 1;
                hash_call_count[hash_current_kind] = hash_call_count[hash_current_kind] + 1;
                hash_absorb_total[hash_current_kind] =
                    hash_absorb_total[hash_current_kind] + hash_call_absorb;
                hash_permute_total[hash_current_kind] =
                    hash_permute_total[hash_current_kind] + hash_call_permute;
                hash_response_total[hash_current_kind] =
                    hash_response_total[hash_current_kind] + hash_call_response;
                hash_idle_total[hash_current_kind] =
                    hash_idle_total[hash_current_kind] + hash_call_idle;
                hash_last_kind = hash_current_kind;
                hash_have_last_kind = 1;
                hash_call_active = 0;
                hash_gap_active = 1;
                hash_gap_cycles = 0;
                // E3 lets WOTS accept the next chain hash on the response
                // cycle. Close the completed call above, then start the new
                // call on that same sampled cycle so its handshake and later
                // permutation remain in the exclusive cycle ledger.
                if (hash_current_kind != 4 && dut.hash_req_valid && dut.hash_req_ready) begin
                    hash_current_kind = dut.hash_kind;
                    hash_call_active = 1;
                    hash_last_input = 0;
                    // The accepted request shares the just-counted response
                    // cycle; its first exclusive absorb cycle is next cycle.
                    hash_call_absorb = 0;
                    hash_call_permute = 0;
                    hash_call_response = 0;
                    hash_call_idle = 0;
                    hash_gap_active = 0;
                    hash_gap_cycles = 0;
                end
            end
        end else if (dut.hmsg_start) begin
            hash_current_kind = 4;
            hash_call_active = 1;
            hash_last_input = 0;
            hash_call_absorb = 1;
            hash_call_permute = 0;
            hash_call_response = 0;
            hash_call_idle = hash_gap_active ? hash_gap_cycles : 0;
            hash_gap_active = 0;
            hash_gap_cycles = 0;
        end else if (dut.start && dut.start_ready) begin
            hash_gap_active = 1;
            hash_gap_cycles = 0;
        end else if (dut.hash_req_valid && dut.hash_req_ready) begin
            hash_current_kind = dut.hash_kind;
            hash_call_active = 1;
            hash_last_input = 0;
            hash_call_absorb = 1;
            hash_call_permute = 0;
            hash_call_response = 0;
            hash_call_idle = hash_gap_active ? hash_gap_cycles : 0;
            hash_gap_active = 0;
            hash_gap_cycles = 0;
        end else if (hash_gap_active) begin
            hash_gap_cycles = hash_gap_cycles + 1;
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
            if (waits > 1000000)
                $fatal(1, "verifier watchdog top=%0d ht=%0d wots=%0d chain=%0d byte=%0d prefetch=%0d/%0d issue=%0d count=%0d capture=%0d pending=%0d xmss=%0d level=%0d word=%0d sig_rd=%0d addr=%0d sig_valid=%0d hash_req=%0d hash_rsp=%0d cycles=%0d",
                       dut.state, dut.u_ht_verify.state,
                       dut.u_ht_verify.u_wots_verify.state,
                       dut.u_ht_verify.u_wots_verify.chain_number,
                       dut.u_ht_verify.u_wots_verify.byte_index,
                       dut.u_ht_verify.u_wots_verify.prefetch_valid,
                       dut.u_ht_verify.u_wots_verify.prefetch_chain_number,
                       dut.u_ht_verify.u_wots_verify.prefetch_issue_done,
                       dut.u_ht_verify.u_wots_verify.prefetch_issue_count,
                       dut.u_ht_verify.u_wots_verify.prefetch_capture_count,
                       dut.u_ht_verify.u_wots_verify.prefetch_capture_pending,
                       dut.u_ht_verify.u_xmss_verify.state,
                       dut.u_ht_verify.u_xmss_verify.level,
                       dut.u_ht_verify.u_xmss_verify.sig_word_index,
                       dut.stage_sig_rd_en, dut.stage_sig_rd_addr,
                       dut.stage_sig_valid, dut.hash_req_valid,
                       dut.hash_rsp_valid, cycles);
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
        for (integer kind_index = 0; kind_index < 5; kind_index = kind_index + 1)
            $display("HASH_TOTAL tc=%0d kind=%0d calls=%0d absorb=%0d permutation=%0d response=%0d idle=%0d",
                     test_id, kind_index, hash_call_count[kind_index],
                     hash_absorb_total[kind_index], hash_permute_total[kind_index],
                     hash_response_total[kind_index],
                     hash_idle_total[kind_index]
                         + ((hash_gap_active && hash_have_last_kind
                             && hash_last_kind == kind_index) ? hash_gap_cycles : 0));
        $display("PASS verify tc=%0d RPC=%0d valid=%0d cycles=%0d perms=%0d", test_id, RPC, valid, cycles, perms);
        $finish;
    end

    initial begin
        #20000000;
        $fatal(1, "simulation watchdog");
    end
endmodule
