module fv_smoke;
    (* gclk *) reg formal_timestep;
    reg clk = 1'b0;
    (* anyseq *) reg a;
    (* anyseq *) reg b;

    always @(posedge formal_timestep)
        clk <= !clk;

    always @(posedge clk) begin
        assert ((a & b) == (b & a));
        cover (a && b);
    end
endmodule
