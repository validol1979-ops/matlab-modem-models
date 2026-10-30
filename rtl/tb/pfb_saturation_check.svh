// Simulation-only observer of the ACTUAL phase clamps of pfb_analysis, one sat_group_check for
// the pfb_phase field group (included in pfb_tb right after the scoreboard declarations, no core
// RTL change, no embedded FFT counts: the polyphase sat22 is the only clamp of the bank).
//
// pfb_analysis clamps sat22(acc) into phase_re/phase_im in state DONE when the FFT is not being
// fed (the FSM branch `DONE: if (!feeding)`), ONE evaluation set per output time. sat22 rounds
// first, (acc + HALF) >>> 13 with the DUT's own HALF = AW'(4096) (no overflow: |acc| <=
// ceil(TMAX/M)*2^34 plus HALF fits the default phase-local ACC_WIDTH), then clamps to 22 bits. The observer
// reproduces exactly that rounding in 128-bit signed arithmetic, so the value presented on every
// lane at a posedge of clk is the pre-clamp, already rounded value the DUT clamps on that same
// edge; the checker's OUT_WIDTH=22 comparison supplies the clamp:
//   rails HIGH = 2^21-1, LOW = -2^21  ==  pfb_fixed.sat22 ==  pfb_analysis sat22 (asymmetric).
// While the FSM waits in DONE with feeding == 1 no clamping happens, so those clocks stay invalid
// and each output time counts exactly once (M real + M imaginary evaluations, matching the model
// count M per output time per field).
//
// Lanes are field-major interleaved (re, im): lane 2n is the rounded acc_re[n], lane 2n+1 the
// rounded acc_im[n], so bucket 0 is phase.re and bucket 1 phase.im, the stage names of
// pfb_fixed.analyze(stats=...). Unknown enables are fatal in the checker; every enable here is a
// definite 0/1. done: every output bin of the vector set has been scored.

localparam int SAT_M = 1 << LOG2M;            // channels, the DUT's own M

wire sat_done = out_total > 0 && out_checked == out_total;

logic sat_phase_valid [0:2*SAT_M-1];
logic signed [127:0] sat_phase_rounded [0:2*SAT_M-1];
always_comb begin
  for (int n = 0; n < SAT_M; n++) begin
    sat_phase_valid[2*n] = 1'b0; sat_phase_valid[2*n+1] = 1'b0;
    sat_phase_rounded[2*n] = '0; sat_phase_rounded[2*n+1] = '0;
    if (dut.state == dut.DONE && !dut.feeding) begin
      sat_phase_valid[2*n] = 1'b1; sat_phase_valid[2*n+1] = 1'b1;
      // (acc + HALF) >>> 13, the DUT's rounding, unclamped, in 128-bit signed arithmetic
      sat_phase_rounded[2*n]   = (128'(dut.acc_re[n]) + 128'sd4096) >>> 13;
      sat_phase_rounded[2*n+1] = (128'(dut.acc_im[n]) + 128'sd4096) >>> 13;
    end
  end
end

sat_group_check #(.VALUES(2*SAT_M),.FIELDS(2),.RAW_WIDTH(128),.OUT_WIDTH(22),
                  .RESET_ACTIVE(RESET_ACTIVE),.NAME("pfb_phase"),
                  .EXPECTED_FILE("pfb_phase_expected.txt")) sat_check_phase
  (.clk(clk),.rst(rst),.scoring(scoring),.done(sat_done),
   .valid(sat_phase_valid),.rounded(sat_phase_rounded));
