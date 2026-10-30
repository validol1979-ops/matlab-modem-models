// Simulation-only observer of the ACTUAL clamp inputs of rls_filter, one sat_group_check per
// field group (included in rls_tb right after the scoreboard declarations, no core RTL change).
//
// Every observer is pure combinational logic over the DUT's own registers and wires, qualified by
// the DUT state and by the DUT's active/row/dump registers, so the value on a lane at a posedge of
// clk is exactly the pre-clamp, already rounded value the DUT is about to clamp on that same edge:
//   ERROR  pred = rnd(sum,30)              e = d - pred                (OUT18, both clamps)
//   U      u[row] = rnd(P[row] h,15)                                   (OUT48, one row per clock)
//   Q      q = rnd(re(h^H u),15)                                       (OUT50)
//   GAIN   g[i] = rnd(u[i] R, shift-15)                                 (OUT40, active taps only)
//   WEIGHT w[i] + rnd(g conj(e),15)                                     (OUT34, active taps only)
//   PT     t[j] = rnd(g[row] conj(u_j),30) for the j >= row the update uses (OUT46, both parts)
//   PN     P.re/P.im = (P - t) INVL rnd 30, upper triangle written once (OUT44)
//   DUMP   sat18(rnd(w[dump],15)) for every reported weight             (OUT18)
// Lanes that the DUT computes and throws away (taps beyond cfg_taps, PT columns j < row, the
// second DUMP clock) are held invalid, so their contents - which are never assigned by the DUT and
// may even be unknown - are ignored, exactly as the checker requires. Unknown enables are fatal in
// the checker; every enable here is a definite 0/1.
//
// The lane order is field-major over FIELDS: lane i feeds bucket i % FIELDS, so with the interleaved
// (re, im) lanes used below bucket 0 is the real part and bucket 1 the imaginary part.

// The two rounding helpers of rls_filter, bit-exact: rs(v,s,bits) rounds then clamps to `bits`,
// rv(v,s) only rounds with a 7-bit shift. Only the rounded value is observed, the clamp is the
// checker's own OUT_WIDTH comparison.
function automatic logic signed [127:0] rls_sat_rnd(input logic signed [127:0] v, input int s);
  return s == 0 ? v : (v + (128'sd1 <<< (s - 1))) >>> s;
endfunction
function automatic logic signed [127:0] rls_sat_rv(input logic signed [127:0] v, input logic [6:0] s);
  return (v + (128'sd1 <<< (s - 1'b1))) >>> s;
endfunction

localparam int SAT_LANES = 1 << LOG2N;          // one lane set per possible tap
localparam int SAT_IB = LOG2N > 0 ? LOG2N : 1;  // the DUT's own index width (NB)
wire signed [127:0] sat_invl = 128'($signed({1'b0, dut.invl}));   // the DUT's own INVL, Q30 unsigned

// done: every sample and every weight of the vector set has been scored.
wire sat_done = out_total > 0 && out_checked == out_total && w_checked == w_total;

// ---- rls_pred_err (F4, OUT18): sat18(pred) and sat18(d - pred), one per sample
logic sat_pred_err_valid [0:3];
logic signed [127:0] sat_pred_err_rounded [0:3];
always_comb begin
  for (int k = 0; k < 4; k++) begin sat_pred_err_valid[k] = 1'b0; sat_pred_err_rounded[k] = '0; end
  if (dut.state == dut.ERROR) begin
    sat_pred_err_valid = '{4{1'b1}};
    sat_pred_err_rounded[0] = rls_sat_rnd(128'(dut.sum_re), 30);
    sat_pred_err_rounded[1] = rls_sat_rnd(128'(dut.sum_im), 30);
    sat_pred_err_rounded[2] = 128'(dut.d_re) - 128'(dut.pred_re);
    sat_pred_err_rounded[3] = 128'(dut.d_im) - 128'(dut.pred_im);
  end
end

// ---- rls_u (F2, OUT48): rnd(P[row] h, 15) for the row the U state is writing
logic sat_u_valid [0:1];
logic signed [127:0] sat_u_rounded [0:1];
always_comb begin
  sat_u_valid[0] = 1'b0; sat_u_valid[1] = 1'b0; sat_u_rounded[0] = '0; sat_u_rounded[1] = '0;
  if (dut.state == dut.U && dut.active[dut.row]) begin
    sat_u_valid[0] = 1'b1; sat_u_valid[1] = 1'b1;
    sat_u_rounded[0] = rls_sat_rnd(128'(dut.acc_re), 15);
    sat_u_rounded[1] = rls_sat_rnd(128'(dut.acc_im), 15);
  end
end

// ---- rls_q (F1, OUT50): rnd(re(h^H u), 15)
logic sat_q_valid [0:0];
logic signed [127:0] sat_q_rounded [0:0];
always_comb begin
  sat_q_valid[0] = 1'b0; sat_q_rounded[0] = '0;
  if (dut.state == dut.Q) begin
    sat_q_valid[0] = 1'b1;
    sat_q_rounded[0] = rls_sat_rnd(128'(dut.q_sum), 15);
  end
end

// ---- rls_gain (F2, OUT40): rnd(u[i] R, shift-15) per tap; the DUT also writes the taps it does
// not use (LOG2N lanes > cfg_taps), those lanes stay invalid.
logic sat_gain_valid [0:2*SAT_LANES-1];
logic signed [127:0] sat_gain_rounded [0:2*SAT_LANES-1];
always_comb begin
  for (int i = 0; i < SAT_LANES; i++) begin
    sat_gain_valid[2*i] = 1'b0; sat_gain_valid[2*i+1] = 1'b0;
    sat_gain_rounded[2*i] = '0; sat_gain_rounded[2*i+1] = '0;
    if (dut.state == dut.GAIN && dut.active[i]) begin
      sat_gain_valid[2*i] = 1'b1; sat_gain_valid[2*i+1] = 1'b1;
      sat_gain_rounded[2*i] = rls_sat_rv(128'(dut.gain_raw_re[i]), dut.shift - 7'd15);
      sat_gain_rounded[2*i+1] = rls_sat_rv(128'(dut.gain_raw_im[i]), dut.shift - 7'd15);
    end
  end
end

// ---- rls_update (F2, OUT34): w[i] + rnd(g conj(e), 15), the value the WEIGHT clamp sees
logic sat_update_valid [0:2*SAT_LANES-1];
logic signed [127:0] sat_update_rounded [0:2*SAT_LANES-1];
always_comb begin
  for (int i = 0; i < SAT_LANES; i++) begin
    sat_update_valid[2*i] = 1'b0; sat_update_valid[2*i+1] = 1'b0;
    sat_update_rounded[2*i] = '0; sat_update_rounded[2*i+1] = '0;
    if (dut.state == dut.WEIGHT && dut.active[i]) begin
      sat_update_valid[2*i] = 1'b1; sat_update_valid[2*i+1] = 1'b1;
      sat_update_rounded[2*i] = 128'(dut.weight_next_re[i]);
      sat_update_rounded[2*i+1] = 128'(dut.weight_next_im[i]);
    end
  end
end

// ---- rls_pt (F2, OUT46): t[j] = rnd(g[row] conj(u_j), 30) for the j >= row that PN consumes
// (both components, the diagonal included). t[j] with j < row is computed and discarded.
logic sat_pt_valid [0:2*SAT_LANES-1];
logic signed [127:0] sat_pt_rounded [0:2*SAT_LANES-1];
always_comb begin
  for (int i = 0; i < SAT_LANES; i++) begin
    sat_pt_valid[2*i] = 1'b0; sat_pt_valid[2*i+1] = 1'b0;
    sat_pt_rounded[2*i] = '0; sat_pt_rounded[2*i+1] = '0;
    if (dut.state == dut.PT && dut.active[i] && 32'(i) >= 32'(dut.row)) begin
      sat_pt_valid[2*i] = 1'b1; sat_pt_valid[2*i+1] = 1'b1;
      sat_pt_rounded[2*i] = 128'(dut.pt_round_re[i]);
      sat_pt_rounded[2*i+1] = 128'(dut.pt_round_im[i]);
    end
  end
end

// ---- rls_p_real (F1, OUT44): sat44 of rnd((P.re - t.re) INVL, 30), the mirror written once, so
// the upper triangle (diagonal included) is one evaluation.
logic sat_p_real_valid [0:SAT_LANES-1];
logic signed [127:0] sat_p_real_rounded [0:SAT_LANES-1];
always_comb begin
  for (int i = 0; i < SAT_LANES; i++) begin
    sat_p_real_valid[i] = 1'b0; sat_p_real_rounded[i] = '0;
    if (dut.state == dut.PN && dut.active[i] && 32'(i) >= 32'(dut.row)) begin
      sat_p_real_valid[i] = 1'b1;
      sat_p_real_rounded[i] = 128'(dut.cov_round_re[i]);
    end
  end
end

// ---- rls_p_imag (F1, OUT44): the same for the imaginary part, strictly above the diagonal (the
// diagonal is forced real and has no clamp).
logic sat_p_imag_valid [0:SAT_LANES-1];
logic signed [127:0] sat_p_imag_rounded [0:SAT_LANES-1];
always_comb begin
  for (int i = 0; i < SAT_LANES; i++) begin
    sat_p_imag_valid[i] = 1'b0; sat_p_imag_rounded[i] = '0;
    if (dut.state == dut.PN && dut.active[i] && 32'(i) > 32'(dut.row)) begin
      sat_p_imag_valid[i] = 1'b1;
      sat_p_imag_rounded[i] = 128'(dut.cov_round_im[i]);
    end
  end
end

// ---- rls_dump (F2, OUT18): rnd(w[dump], 15) of every reported weight (the DUMP clock that only
// releases w_valid has dump == taps and stays invalid).
logic sat_dump_valid [0:1];
logic signed [127:0] sat_dump_rounded [0:1];
always_comb begin
  sat_dump_valid[0] = 1'b0; sat_dump_valid[1] = 1'b0; sat_dump_rounded[0] = '0; sat_dump_rounded[1] = '0;
  if (dut.state == dut.DUMP && (!dut.w_valid || w_ready) && dut.dump < dut.taps) begin
    sat_dump_valid[0] = 1'b1; sat_dump_valid[1] = 1'b1;
    sat_dump_rounded[0] = rls_sat_rnd(128'(dut.wr[SAT_IB'(dut.dump)]), 15);
    sat_dump_rounded[1] = rls_sat_rnd(128'(dut.wi[SAT_IB'(dut.dump)]), 15);
  end
end

sat_group_check #(.VALUES(4),.FIELDS(4),.RAW_WIDTH(128),.OUT_WIDTH(18),
                  .RESET_ACTIVE(RESET_ACTIVE),.NAME("rls_pred_err"),
                  .EXPECTED_FILE("rls_pred_err_group_expected.txt")) sat_check_pred_err
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),
   .valid(sat_pred_err_valid),.rounded(sat_pred_err_rounded));
sat_group_check #(.VALUES(2),.FIELDS(2),.RAW_WIDTH(128),.OUT_WIDTH(48),
                  .RESET_ACTIVE(RESET_ACTIVE),.NAME("rls_u"),
                  .EXPECTED_FILE("rls_u_group_expected.txt")) sat_check_u
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),
   .valid(sat_u_valid),.rounded(sat_u_rounded));
sat_group_check #(.VALUES(1),.FIELDS(1),.RAW_WIDTH(128),.OUT_WIDTH(50),
                  .RESET_ACTIVE(RESET_ACTIVE),.NAME("rls_q"),
                  .EXPECTED_FILE("rls_q_group_expected.txt")) sat_check_q
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),
   .valid(sat_q_valid),.rounded(sat_q_rounded));
sat_group_check #(.VALUES(2*SAT_LANES),.FIELDS(2),.RAW_WIDTH(128),.OUT_WIDTH(40),
                  .RESET_ACTIVE(RESET_ACTIVE),.NAME("rls_gain"),
                  .EXPECTED_FILE("rls_gain_group_expected.txt")) sat_check_gain
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),
   .valid(sat_gain_valid),.rounded(sat_gain_rounded));
sat_group_check #(.VALUES(2*SAT_LANES),.FIELDS(2),.RAW_WIDTH(128),.OUT_WIDTH(34),
                  .RESET_ACTIVE(RESET_ACTIVE),.NAME("rls_update"),
                  .EXPECTED_FILE("rls_update_group_expected.txt")) sat_check_update
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),
   .valid(sat_update_valid),.rounded(sat_update_rounded));
sat_group_check #(.VALUES(2*SAT_LANES),.FIELDS(2),.RAW_WIDTH(128),.OUT_WIDTH(46),
                  .RESET_ACTIVE(RESET_ACTIVE),.NAME("rls_pt"),
                  .EXPECTED_FILE("rls_pt_group_expected.txt")) sat_check_pt
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),
   .valid(sat_pt_valid),.rounded(sat_pt_rounded));
sat_group_check #(.VALUES(SAT_LANES),.FIELDS(1),.RAW_WIDTH(128),.OUT_WIDTH(44),
                  .RESET_ACTIVE(RESET_ACTIVE),.NAME("rls_p_real"),
                  .EXPECTED_FILE("rls_p_real_group_expected.txt")) sat_check_p_real
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),
   .valid(sat_p_real_valid),.rounded(sat_p_real_rounded));
sat_group_check #(.VALUES(SAT_LANES),.FIELDS(1),.RAW_WIDTH(128),.OUT_WIDTH(44),
                  .RESET_ACTIVE(RESET_ACTIVE),.NAME("rls_p_imag"),
                  .EXPECTED_FILE("rls_p_imag_group_expected.txt")) sat_check_p_imag
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),
   .valid(sat_p_imag_valid),.rounded(sat_p_imag_rounded));
sat_group_check #(.VALUES(2),.FIELDS(2),.RAW_WIDTH(128),.OUT_WIDTH(18),
                  .RESET_ACTIVE(RESET_ACTIVE),.NAME("rls_dump"),
                  .EXPECTED_FILE("rls_dump_group_expected.txt")) sat_check_dump
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),
   .valid(sat_dump_valid),.rounded(sat_dump_rounded));
