module fv_keccak_lut4;
    (* gclk *) reg formal_timestep;
    (* anyconst *) reg [3:0] input_value;
    wire [3:0] portable_output;
    wire [3:0] native_output;

    keccak_lut4 #(.INIT(16'h6996), .NATIVE(0)) portable_xor4 (
        .i(input_value), .o(portable_output[0])
    );
    keccak_lut4 #(.INIT(16'h6666), .NATIVE(0)) portable_xor2 (
        .i(input_value), .o(portable_output[1])
    );
    keccak_lut4 #(.INIT(16'h9696), .NATIVE(0)) portable_theta (
        .i(input_value), .o(portable_output[2])
    );
    keccak_lut4 #(.INIT(16'h659a), .NATIVE(0)) portable_chi (
        .i(input_value), .o(portable_output[3])
    );

    keccak_lut4 #(.INIT(16'h6996), .NATIVE(1)) native_xor4 (
        .i(input_value), .o(native_output[0])
    );
    keccak_lut4 #(.INIT(16'h6666), .NATIVE(1)) native_xor2 (
        .i(input_value), .o(native_output[1])
    );
    keccak_lut4 #(.INIT(16'h9696), .NATIVE(1)) native_theta (
        .i(input_value), .o(native_output[2])
    );
    keccak_lut4 #(.INIT(16'h659a), .NATIVE(1)) native_chi (
        .i(input_value), .o(native_output[3])
    );

    always @(posedge formal_timestep) begin
        assert (portable_output == native_output);
        cover (input_value == 4'hf);
    end
endmodule
