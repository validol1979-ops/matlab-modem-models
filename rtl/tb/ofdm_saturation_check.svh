// Simulation-only observers of the actual outer 18 bit clamp inputs of dut_tx/dut_rx
// (tools/ofdm_cases.py expected files, sat_diag stages tx.re/tx.im and rx.re/rx.im).
// Included inside ofdm_tb after the scoring declaration; DUT paths dut_tx and dut_rx.
// TX lane: the inverse output f_re/f_im is clamped by sat18 exactly on the prefix-RAM
// write edge, once per core sample, BEFORE the cyclic-prefix duplication (the read side
// replays each stored value N+CP times, which must not be counted again).
// RX lane: round_sat(p) is evaluated exactly when ce && pv, once per core output; the
// fed raw value is the actual rounded word (38'(p) + 38'(RND)) >>> SHIFT_RX sign-extended
// to 128 bits (it provably fits 28 bits), so a held o_re/o_im under backpressure is never
// double counted. No embedded FFT stage clamp is observed here.
wire sat_done = txo_total > 0 && tx_checked == txo_total && rx_checked == rxo_total;
localparam int SAT_SHIFT_RX = 15 - LOG2N/2;   // ofdm_rx SHIFT_RX, kept equal to the DUT
localparam int SAT_RND = 1 << (SAT_SHIFT_RX-1);
logic sat_tx_valid [0:1];
logic sat_rx_valid [0:1];
logic signed [127:0] sat_tx_raw [0:1];
logic signed [127:0] sat_rx_raw [0:1];
always_comb begin
  sat_tx_valid[0] = scoring && dut_tx.write;
  sat_tx_valid[1] = sat_tx_valid[0];
  sat_tx_raw[0] = 128'($signed(dut_tx.f_re));   // 20-bit pre-sat18 value, sign-extended
  sat_tx_raw[1] = 128'($signed(dut_tx.f_im));
  sat_rx_valid[0] = scoring && dut_rx.ce && dut_rx.pv;
  sat_rx_valid[1] = sat_rx_valid[0];
  sat_rx_raw[0] = 128'($signed((38'(dut_rx.p_re) + 38'(SAT_RND)) >>> SAT_SHIFT_RX));
  sat_rx_raw[1] = 128'($signed((38'(dut_rx.p_im) + 38'(SAT_RND)) >>> SAT_SHIFT_RX));
end
sat_group_check #(.VALUES(2),.FIELDS(2),.RAW_WIDTH(128),.OUT_WIDTH(18),.RESET_ACTIVE(RESET_ACTIVE),
  .NAME("ofdm_tx"),.EXPECTED_FILE("ofdm_tx_expected.txt")) sat_tx_check
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),.valid(sat_tx_valid),.rounded(sat_tx_raw));
sat_group_check #(.VALUES(2),.FIELDS(2),.RAW_WIDTH(128),.OUT_WIDTH(18),.RESET_ACTIVE(RESET_ACTIVE),
  .NAME("ofdm_rx"),.EXPECTED_FILE("ofdm_rx_expected.txt")) sat_rx_check
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),.valid(sat_rx_valid),.rounded(sat_rx_raw));
