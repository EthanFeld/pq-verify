`timescale 1ns/1ps
module tb_adrs;
    logic clk = 0;
    always #5 clk = !clk;
    logic rst_n = 1;
    logic set_layer = 0, set_tree = 0, set_type_and_clear = 0;
    logic set_keypair = 0, set_chain = 0, set_tree_height = 0;
    logic set_hash = 0, set_tree_index = 0;
    logic [31:0] layer_value = 0, type_value = 0, keypair_value = 0;
    logic [31:0] word6_value = 0, word7_value = 0;
    logic [95:0] tree_value = 0;
    wire [255:0] address;
    logic [255:0] expected = 0;
    logic [255:0] trace_addresses [0:49];
    string trace_file;
    integer trace_count = 0;

    adrs dut (
        .clk(clk), .rst_n(rst_n), .set_layer(set_layer), .layer_value(layer_value),
        .set_tree(set_tree), .tree_value(tree_value),
        .set_type_and_clear(set_type_and_clear), .type_value(type_value),
        .set_keypair(set_keypair), .keypair_value(keypair_value),
        .set_chain(set_chain), .set_tree_height(set_tree_height), .word6_value(word6_value),
        .set_hash(set_hash), .set_tree_index(set_tree_index), .word7_value(word7_value),
        .address(address)
    );

    task automatic check_address(input string label);
        if (address !== expected) $fatal(1, "%s address=%h expected=%h", label, address, expected);
    endtask

    task automatic step;
        @(posedge clk); #1;
        check_address("setter");
        @(negedge clk);
        set_layer = 0;
        set_tree = 0;
        set_type_and_clear = 0;
        set_keypair = 0;
        set_chain = 0;
        set_tree_height = 0;
        set_hash = 0;
        set_tree_index = 0;
    endtask

    initial begin
        #1 rst_n = 0;
        #1;
        check_address("async reset");
        @(negedge clk);
        rst_n = 1;

        // Set each big-endian FIPS ADRS field, then exercise the type reset.
        layer_value = 32'h0102_0304;
        set_layer = 1;
        expected[255:224] = layer_value;
        step();

        tree_value = 96'h1112_1314_1516_1718_191a_1b1c;
        set_tree = 1;
        expected[223:128] = tree_value;
        step();

        type_value = 32'd3;
        set_type_and_clear = 1;
        expected[127:96] = type_value;
        expected[95:0] = '0;
        step();

        keypair_value = 32'h2122_2324;
        set_keypair = 1;
        expected[95:64] = keypair_value;
        step();

        word6_value = 32'h3132_3334;
        set_chain = 1;
        expected[63:32] = word6_value;
        step();

        word6_value = 32'h4142_4344;
        set_tree_height = 1;
        expected[63:32] = word6_value;
        step();

        word7_value = 32'h5152_5354;
        set_hash = 1;
        expected[31:0] = word7_value;
        step();

        word7_value = 32'h6162_6364;
        set_tree_index = 1;
        expected[31:0] = word7_value;
        step();

        // Clear/type has priority over all field setters on a shared clock edge.
        set_type_and_clear = 1;
        set_layer = 1;
        set_tree = 1;
        set_keypair = 1;
        set_chain = 1;
        set_hash = 1;
        type_value = 32'd4;
        expected[127:96] = type_value;
        expected[95:0] = '0;
        step();

        // Replay actual Python-reference addresses for all ADRS types in one
        // valid ACVP trace; compare each registered field update to the trace.
        if ($value$plusargs("trace_file=%s", trace_file)) begin
            if (!$value$plusargs("trace_count=%d", trace_count) || trace_count != 50)
                $fatal(1, "ADRS trace replay requires exactly 50 addresses");
            $readmemh(trace_file, trace_addresses, 0, trace_count - 1);
            for (integer index = 0; index < trace_count; index = index + 1) begin
                expected[255:224] = trace_addresses[index][255:224];
                layer_value = trace_addresses[index][255:224];
                set_layer = 1;
                step();

                expected[223:128] = trace_addresses[index][223:128];
                tree_value = trace_addresses[index][223:128];
                set_tree = 1;
                step();

                expected[127:96] = trace_addresses[index][127:96];
                expected[95:0] = '0;
                type_value = trace_addresses[index][127:96];
                set_type_and_clear = 1;
                step();

                expected[95:64] = trace_addresses[index][95:64];
                keypair_value = trace_addresses[index][95:64];
                set_keypair = 1;
                step();

                expected[63:32] = trace_addresses[index][63:32];
                word6_value = trace_addresses[index][63:32];
                set_chain = 1;
                step();

                expected[31:0] = trace_addresses[index][31:0];
                word7_value = trace_addresses[index][31:0];
                set_hash = 1;
                step();
                if (address !== trace_addresses[index])
                    $fatal(1, "Python ADRS trace mismatch index=%0d got=%h expected=%h",
                           index, address, trace_addresses[index]);
            end
        end

        $display("PASS ADRS field layout, aliases, priority/reset, Python trace sequences=%0d", trace_count);
        $finish;
    end
endmodule
