// Simulation-only observer of the actual FFT clamp inputs. Included in fft_tb.
// Each D-slot tag line mirrors the SDF data delay, storing raw-input validity in
// the lower half and difference validity in the upper half. The four pipeline
// tags advance only with dut.adv: tag[2] identifies h at the clamp edge, tag[3]
// identifies the registered r consumed by the next stage. Nonblocking updates
// keep those stage boundaries free of simulator scheduling races.
localparam int SAT_H = WIDTH + 4;
localparam longint SAT_LIMIT = (64'sd1 << (WIDTH-1)) - 1;
int sat_eval [2][LOG2N][2][2];
int sat_pos [2][LOG2N][2][2];
int sat_neg [2][LOG2N][2][2];
int sat_frames [2];
wire sat_input_valid [0:LOG2N-1];

always @(posedge clk) begin
  if (dut.reset_now) begin
    sat_frames[0] = 0; sat_frames[1] = 0;
    for (int d=0; d<2; d++) for (int s=0; s<LOG2N; s++)
      for (int b=0; b<2; b++) for (int c=0; c<2; c++) begin
        sat_eval[d][s][b][c] = 0; sat_pos[d][s][b][c] = 0; sat_neg[d][s][b][c] = 0;
      end
  end else if (scoring && m_valid && m_ready && m_last)
    sat_frames[int'(m_inverse)] += 1;
end

genvar sat_stage;
generate
  for (sat_stage=0; sat_stage<LOG2N; sat_stage++) begin : g_sat_mon
    localparam int D = N >> (sat_stage+1);
    bit [D-1:0] line_valid;
    bit [3:0] pipe_valid;
    bit [2:0] pipe_upper;
    wire upper = dut.g_stage[sat_stage].upper;
    wire input_valid = sat_input_valid[sat_stage];
    wire sum_valid = input_valid && line_valid[D-1];
    wire operation_valid = upper ? sum_valid : line_valid[D-1];
    wire store_valid = upper ? sum_valid : input_valid;
    wire direction = dut.g_stage[sat_stage].v3_inv;
    wire signed [SAT_H-1:0] raw_re, raw_im;
    if (sat_stage == LOG2N-1) begin : g_last
      assign raw_re = dut.g_stage[sat_stage].g_last.h_re;
      assign raw_im = dut.g_stage[sat_stage].g_last.h_im;
    end else begin : g_twiddle
      assign raw_re = dut.g_stage[sat_stage].g_twiddle.h_re;
      assign raw_im = dut.g_stage[sat_stage].g_twiddle.h_im;
    end
    if (sat_stage == 0) begin : g_input
      assign sat_input_valid[0] = dut.take && scoring;
    end else begin : g_input
      assign sat_input_valid[sat_stage] = g_sat_mon[sat_stage-1].pipe_valid[3];
    end
    always @(posedge clk) begin
      if (dut.reset_now) begin
        line_valid <= '0; pipe_valid <= '0; pipe_upper <= '0;
      end else if (dut.adv) begin
        if (pipe_valid[2]) begin
          int d, b;
          longint re_value, im_value;
          if ($isunknown({direction, raw_re, raw_im}))
            $fatal(1, "[SATURATION] FFT stage %0d has unknown valid clamp data", sat_stage);
          d = int'(direction);
          b = pipe_upper[2] ? 0 : 1; // upper produces sum, lower produces stored diff
          re_value = longint'($signed(raw_re)); im_value = longint'($signed(raw_im));
          sat_eval[d][sat_stage][b][0] += 1;
          sat_eval[d][sat_stage][b][1] += 1;
          if (re_value > SAT_LIMIT) sat_pos[d][sat_stage][b][0] += 1;
          if (re_value < -SAT_LIMIT) sat_neg[d][sat_stage][b][0] += 1;
          if (im_value > SAT_LIMIT) sat_pos[d][sat_stage][b][1] += 1;
          if (im_value < -SAT_LIMIT) sat_neg[d][sat_stage][b][1] += 1;
        end
        line_valid <= (line_valid << 1) | D'(store_valid);
        pipe_valid <= {pipe_valid[2:0], operation_valid};
        pipe_upper <= {pipe_upper[1:0], upper};
      end
    end
  end
endgenerate

task automatic check_fft_saturation();
  int file_id, header, rc_sat, expected_eval, expected_pos, expected_neg, extra;
  int evaluations=0, events=0;
  file_id = $fopen({directory, "/saturation_expected.txt"}, "r");
  if (!file_id) $fatal(1, "[SATURATION] missing FFT expected counts");
  rc_sat = $fscanf(file_id, "%d", header);
  if (rc_sat != 1 || header != LOG2N) $fatal(1, "[SATURATION] invalid FFT count header");
  for (int d=0; d<2; d++) for (int s=0; s<LOG2N; s++)
    for (int b=0; b<2; b++) for (int c=0; c<2; c++) begin
      rc_sat = $fscanf(file_id, "%d %d %d", expected_eval, expected_pos, expected_neg);
      if (rc_sat != 3 || expected_eval < 0 || expected_pos < 0 || expected_neg < 0)
        $fatal(1, "[SATURATION] malformed FFT count row");
      if ($test$plusargs("INJECT_SAT_MISMATCH") && d==0 && s==0 && b==0 && c==0)
        expected_pos += 1;
      if ($test$plusargs("INJECT_SAT_EVAL_MISMATCH") && d==0 && s==0 && b==0 && c==0)
        expected_eval += 1;
      if (sat_eval[d][s][b][c] != sat_frames[d]*(N/2))
        $fatal(1, "[SATURATION] FFT validity count dir=%0d stage=%0d branch=%0d comp=%0d: %0d != %0d",
               d,s,b,c,sat_eval[d][s][b][c],sat_frames[d]*(N/2));
      if (sat_eval[d][s][b][c] != expected_eval || sat_pos[d][s][b][c] != expected_pos ||
          sat_neg[d][s][b][c] != expected_neg)
        $fatal(1, "[SATURATION] FFT dir=%0d stage=%0d branch=%0d comp=%0d: eval %0d/%0d pos %0d/%0d neg %0d/%0d",
               d,s,b,c,sat_eval[d][s][b][c],expected_eval,
               sat_pos[d][s][b][c],expected_pos,sat_neg[d][s][b][c],expected_neg);
      evaluations += sat_eval[d][s][b][c];
      events += sat_pos[d][s][b][c] + sat_neg[d][s][b][c];
    end
  if ($fscanf(file_id, "%d", extra) == 1) $fatal(1, "[SATURATION] extra FFT count rows");
  $fclose(file_id);
  $display("PASS FFT SATURATION: %0d evaluations, %0d events", evaluations, events);
endtask
