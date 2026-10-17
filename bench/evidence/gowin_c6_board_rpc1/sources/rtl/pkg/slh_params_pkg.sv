package slh_params_pkg;
    localparam integer PARAM_SET_SHAKE_128S = 0;
    localparam integer PARAM_SET = PARAM_SET_SHAKE_128S;

    localparam integer N = 16;
    localparam integer H = 63;
    localparam integer D = 7;
    localparam integer HP = 9;
    localparam integer A = 12;
    localparam integer K = 14;
    localparam integer LG_W = 4;
    localparam integer W = 1 << LG_W;
    localparam integer LEN1 = (8 * N + LG_W - 1) / LG_W;
    localparam integer LEN2 = 3;
    localparam integer LEN = LEN1 + LEN2;
    localparam integer M = 30;

    localparam integer PK_BYTES = 2 * N;
    localparam integer R_OFFSET = 0;
    localparam integer R_BYTES = N;
    localparam integer FORS_OFFSET = R_OFFSET + R_BYTES;
    localparam integer FORS_BYTES = K * (A + 1) * N;
    localparam integer HT_OFFSET = FORS_OFFSET + FORS_BYTES;
    localparam integer XMSS_BYTES = (HP + LEN) * N;
    localparam integer HT_BYTES = D * XMSS_BYTES;
    localparam integer SIG_BYTES = HT_OFFSET + HT_BYTES;
endpackage
