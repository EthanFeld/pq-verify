// Start verification, reset it mid-run, then check the public idle contract.
module fv_slh_top_reset;
    (* gclk *) reg formal_timestep;
    reg clk = 1'b0;
    reg [5:0] formal_steps = 6'd0;
    reg start_sent = 1'b0;
    reg saw_active_start = 1'b0;
    reg saw_reset_recovery = 1'b0;
    reg reset_seen = 1'b0;

    wire rst_n = (formal_steps >= 6'd4)
        && !(formal_steps >= 6'd32 && formal_steps < 6'd36);
    wire start = rst_n && !start_sent;
    (* anyseq *) reg pure_mode;
    (* anyseq *) reg [7:0] ctx_len;
    (* anyseq *) reg ctx_valid;
    (* anyseq *) reg [7:0] ctx_byte;
    (* anyseq *) reg msg_valid;
    (* anyseq *) reg [7:0] msg_byte;
    (* anyseq *) reg msg_last;
    (* anyseq *) reg [127:0] pk_seed;
    (* anyseq *) reg [127:0] pk_root;
    (* anyseq *) reg sig_load_en;
    (* anyseq *) reg [10:0] sig_load_addr;
    (* anyseq *) reg [31:0] sig_load_data;
    wire start_ready;
    wire ctx_ready;
    wire msg_ready;
    wire sig_load_ready;
    wire done;
    wire valid;
    wire [31:0] cycles;
    wire [15:0] perms;

    always @(posedge formal_timestep) begin
        clk <= !clk;
        if (formal_steps < 6'd40)
            formal_steps <= formal_steps + 1'b1;
    end

    slh_verify_top #(.RPC(4), .SCRATCH_STYLE(0), .FORMAL_CONTROL_ONLY(1)) dut (
        .clk(clk), .rst_n(rst_n), .start(start), .start_ready(start_ready),
        .pure_mode(pure_mode), .ctx_len(ctx_len), .ctx_valid(ctx_valid),
        .ctx_ready(ctx_ready), .ctx_byte(ctx_byte), .msg_valid(msg_valid),
        .msg_ready(msg_ready), .msg_byte(msg_byte), .msg_last(msg_last),
        .pk_seed(pk_seed), .pk_root(pk_root), .sig_load_en(sig_load_en),
        .sig_load_addr(sig_load_addr), .sig_load_data(sig_load_data),
        .sig_load_ready(sig_load_ready), .done(done), .valid(valid),
        .cycles(cycles), .perms(perms)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            start_sent <= 1'b0;
            reset_seen <= 1'b1;
            assert (!done);
            assert (!valid);
        end else begin
            if (start && start_ready) begin
                start_sent <= 1'b1;
                saw_active_start <= 1'b1;
            end
            if (valid)
                assert (done);
            if (reset_seen) begin
                assert (start_ready);
                assert (!done);
                assert (!valid);
                if (saw_active_start)
                    saw_reset_recovery <= 1'b1;
                reset_seen <= 1'b0;
            end
            cover (saw_reset_recovery);
        end
    end
endmodule
