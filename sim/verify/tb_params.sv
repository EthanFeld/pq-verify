`timescale 1ns/1ps
module tb_params;
    import slh_params_pkg::*;

    initial begin
        if (PARAM_SET != PARAM_SET_SHAKE_128S || N != 16 || H != 63 || D != 7
                || HP != 9 || A != 12 || K != 14 || LG_W != 4 || W != 16
                || LEN1 != 32 || LEN2 != 3 || LEN != 35 || M != 30)
            $fatal(1, "SHAKE-128s parameter constants mismatch");
        if (PK_BYTES != 32 || R_OFFSET != 0 || R_BYTES != 16
                || FORS_OFFSET != 16 || FORS_BYTES != 2912 || HT_OFFSET != 2928
                || XMSS_BYTES != 704 || HT_BYTES != 4928 || SIG_BYTES != 7856)
            $fatal(1, "SHAKE-128s signature offsets mismatch");
        $display("PASS SHAKE-128s parameter and signature layout elaboration");
        $finish;
    end
endmodule
