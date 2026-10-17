module fv_keccak_control #(
    parameter integer RPC = 1,
    parameter integer IN_PLACE = 0
);
    (* gclk *) reg formal_timestep;
    reg clk = 1'b0;
    (* anyseq *) reg start;
    (* anyseq *) reg state_load;
    (* anyseq *) reg [1599:0] state_in;
    wire [1599:0] state_out;
    wire busy;
    wire done;
    wire [5:0] round_base;

    reg [2:0] reset_steps = 3'd0;
    reg past_valid = 1'b0;
    reg saw_accept = 1'b0;
    reg saw_busy_start = 1'b0;
    reg saw_done = 1'b0;
    wire rst_n = (reset_steps >= 3'd4);

    always @(posedge formal_timestep) begin
        clk <= !clk;
        if (reset_steps < 3'd4)
            reset_steps <= reset_steps + 1'b1;
    end

    keccak_f1600 #(
        .RPC(RPC),
        .IN_PLACE(IN_PLACE),
        .FORMAL_CONTROL_ONLY(1)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .start(start),
        .state_load(state_load),
        .state_in(state_in),
        .state_out(state_out),
        .busy(busy),
        .done(done),
        .formal_round_base(round_base)
    );

`ifdef FORMAL
    always @(posedge clk) begin
        if (!rst_n) begin
            past_valid <= 1'b0;
            saw_accept <= 1'b0;
            saw_busy_start <= 1'b0;
            saw_done <= 1'b0;
            if (reset_steps >= 3'd2) begin
                assert (!busy);
                assert (!done);
            end
        end else begin
            if (IN_PLACE != 0)
                assume (!busy || !state_load);

            if (past_valid) begin
                if ($past(busy)) begin
                    if ($past(round_base) + RPC >= 24) begin
                        assert (!busy);
                        assert (done);
                    end else begin
                        assert (busy);
                        assert (!done);
                        assert (round_base == $past(round_base) + RPC);
                    end
                end else if ($past(start && !busy)) begin
                    assert (busy);
                    assert (!done);
                    assert (round_base == 0);
                end else begin
                    assert (!busy);
                    assert (!done);
                end

                if ($past(done))
                    assert (!done);
            end

            if (!busy && start)
                saw_accept <= 1'b1;
            if (busy && start)
                saw_busy_start <= 1'b1;
            if (done)
                saw_done <= 1'b1;

            cover (busy);
            cover (saw_accept && saw_done);
            cover (saw_busy_start && saw_done);
            if (IN_PLACE != 0)
                cover (!busy && state_load);

            past_valid <= 1'b1;
        end
    end
`endif
endmodule
