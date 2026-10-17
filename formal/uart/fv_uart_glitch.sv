module fv_uart_glitch;
    (* gclk *) reg formal_timestep;
    reg clk = 1'b0;
    reg [2:0] reset_steps = 3'd0;
    reg [5:0] active_cycles = 6'd0;
    wire rst_n = (reset_steps >= 3'd4);
    wire rx = (active_cycles != 6'd7);
    wire byte_valid;
    wire [7:0] byte_data;
    wire framing_error;

    always @(posedge formal_timestep) begin
        clk <= !clk;
        if (reset_steps < 3'd4)
            reset_steps <= reset_steps + 1'b1;
    end

    initial assume (!rst_n);

    uart_rx #(.CLKS_PER_BIT(4)) dut (
        .clk(clk), .rst_n(rst_n), .rx(rx), .byte_valid(byte_valid),
        .byte_data(byte_data), .framing_error(framing_error)
    );

    always @(posedge clk) begin
        if (!rst_n)
            active_cycles <= 6'd0;
        else begin
            if (active_cycles < 6'd20)
                active_cycles <= active_cycles + 1'b1;
            assert (!byte_valid);
            assert (!framing_error);
            cover (active_cycles == 6'd8);
        end
    end
endmodule
