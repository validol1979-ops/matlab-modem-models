// Observe each actual FIR clamp before its FIFO write; compare with the model counts.
// Warm-up traffic is excluded and reset clears all observations.
module fir_saturation_check #(
  parameter int AW = 44,
  parameter bit RESET_ACTIVE = 1
)(
  input logic clk, rst, scoring, sample_valid, done,
  input logic signed [AW-1:0] accumulator_re, accumulator_im
);
  longint re_pos = 0, re_neg = 0, im_pos = 0, im_neg = 0;
  longint expected_re_pos, expected_re_neg, expected_im_pos, expected_im_neg;
  bit checked = 0;
  string directory;
  int fd, rc;
  initial begin
    if (!$value$plusargs("VECTORS=%s", directory)) $fatal(1, "[SATURATION] VECTORS missing");
    fd = $fopen({directory, "/saturation_expected.txt"}, "r");
    if (!fd) $fatal(1, "[SATURATION] expected counts missing");
    rc = $fscanf(fd, "%d %d %d %d", expected_re_pos, expected_re_neg, expected_im_pos, expected_im_neg);
    $fclose(fd);
    if (rc != 4) $fatal(1, "[SATURATION] malformed expected counts");
    if ($test$plusargs("INJECT_SAT_MISMATCH")) expected_re_pos = expected_re_pos + 1;
  end
  always @(posedge clk) begin
    longint rounded_re, rounded_im;
    if (rst == RESET_ACTIVE) begin
      re_pos = 0; re_neg = 0; im_pos = 0; im_neg = 0; checked = 0;
    end else if (scoring && sample_valid) begin
      if ($isunknown(accumulator_re) || $isunknown(accumulator_im))
        $fatal(1, "[SATURATION] unknown FIR accumulator");
      rounded_re = (longint'($signed(accumulator_re)) + 65536) >>> 17;
      rounded_im = (longint'($signed(accumulator_im)) + 65536) >>> 17;
      if (rounded_re > 131071) re_pos = re_pos + 1;
      if (rounded_re < -131072) re_neg = re_neg + 1;
      if (rounded_im > 131071) im_pos = im_pos + 1;
      if (rounded_im < -131072) im_neg = im_neg + 1;
    end
  end
  always @(negedge clk) if (rst != RESET_ACTIVE && scoring && done && !checked) begin
    if (re_pos != expected_re_pos || re_neg != expected_re_neg ||
        im_pos != expected_im_pos || im_neg != expected_im_neg)
      $fatal(1, "[SATURATION] FIR counts got %0d %0d %0d %0d, expected %0d %0d %0d %0d",
             re_pos, re_neg, im_pos, im_neg, expected_re_pos, expected_re_neg, expected_im_pos, expected_im_neg);
    $display("PASS FIR SATURATION: %0d %0d %0d %0d", re_pos, re_neg, im_pos, im_neg);
    checked = 1;
  end
endmodule
