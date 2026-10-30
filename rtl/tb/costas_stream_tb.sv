// Continuous-rate costas_stream.sv against the integer model (tools/costas_stream_cases.py vectors:
// sync_fixed.costas_pipelined with the same loop delay in samples). One configuration transfer
// (cl_cfg.txt: k1 k2), then cl_in.txt (`re im last`) is streamed through the DUT and every accepted
// output is scored against cl_out.txt (`re im phase last`, bit exact).
//
// +STALL_INPUT adds random gaps before offering a sample, +STALL_OUTPUT drops m_ready randomly
// (~2/3 high): output stalls freeze the pipeline, while input gaps advance it and change the
// effective delay in samples. +INJECT_MISMATCH corrupts the first expected output (negative control,
// [NUMERIC]). +RESET_MID streams half of the case, resets the DUT in the middle, requires it to come
// back silent and unconfigured, then replays the whole case and scores only the replay.
// +INJECT_HOLD_MISMATCH corrupts a stalled-output snapshot to exercise the [PROTOCOL] monitor;
// use it with +STALL_OUTPUT and expect simulation failure.
// +CFG_PROBE offers a new configuration while samples are still in flight and requires cfg_ready to
// stay low ([PROTOCOL]); after the stream drains a configuration transfer must succeed again.
//
// Throughput: with no stalls the bench holds s_valid high and m_ready high, so the claim is measured,
// not assumed - RUN_LEN is the longest run of consecutive accepts (II=1 <=> RUN_LEN == samples) and
// GAP_MAX is the largest distance between two accepted samples. Synthesis is on the agreed pause, so
// only this functional throughput is reported, never a clock period or Fmax.
`timescale 1ns/1ps
module costas_stream_tb;
  parameter bit RESET_ACTIVE = 1;
  parameter TABLE_DIR = "rtl/modems/bpsk_costas_2008_08_25/tables";
  logic clk = 0, rst = RESET_ACTIVE;
  always #5 clk = !clk;
  string directory;
  int ccf, cif, cof, rc;
  logic cfg_valid = 0, cfg_ready, configured;
  logic [31:0] cfg_k1 = 0, cfg_k2 = 0;
  logic s_valid = 0, s_last = 0, s_ready;
  logic signed [17:0] s_re = 0, s_im = 0;
  logic m_valid, m_last, m_ready = 1;
  logic signed [17:0] m_re, m_im;
  logic signed [31:0] m_phase;
  costas_stream #(.RESET_ACTIVE(RESET_ACTIVE), .TABLE_DIR(TABLE_DIR)) dut
   (.clk(clk), .rst(rst),
    .cfg_valid(cfg_valid), .cfg_k1(cfg_k1), .cfg_k2(cfg_k2),
    .cfg_ready(cfg_ready), .configured(configured),
    .s_valid(s_valid), .s_last(s_last), .s_re(s_re), .s_im(s_im), .s_ready(s_ready),
    .m_valid(m_valid), .m_last(m_last), .m_re(m_re), .m_im(m_im), .m_phase(m_phase),
    .m_ready(m_ready));

  longint k1, k2;
  int in_re[], in_im[], in_last[], in_total;
  int out_total, out_checked = 0;
  bit scoring = 1, stall_in = 0, stall_out = 0, inject = 0, cfg_probe = 0, reset_mid = 0;
  longint cycle = 0, accepted = 0, run_len = 0, run_max = 0, gap_max = 0, out_gap_max = 0;
  longint span_first = -1, span_last = -1;
  int warm_out = 0, idle_cycles = 0;
  bit no_score = 0;
  int alf = 0, obs = 0;
  longint advance = 0, step = 0;
  string accept_log, observed;
  always @(posedge clk) cycle <= cycle + 1;
  always @(posedge clk) if ($test$plusargs("TRACE") && cycle > 8 && cycle < 30)
    $display("t=%0d clk=%0d valid=%0b ready=%0b m_valid=%0b m_ready=%0b configured=%0b",
             $time, cycle, s_valid, s_ready, m_valid, m_ready, configured);
  always @(negedge clk) if (stall_out) m_ready <= (($urandom % 3) != 0);

  // Ready/valid requires the entire offered word, including valid, to remain
  // unchanged through the next edge after any stalled transfer attempt.
  bit output_held = 0;
  logic [69:0] held_output;
  longint hold_checks = 0;
  bit injected_hold = 0;
  always @(posedge clk) begin
    if (rst == RESET_ACTIVE) output_held = 0;
    else begin
      if (output_held) begin
        hold_checks = hold_checks + 1;
        if ({m_valid, m_last, m_re, m_im, m_phase} !== held_output)
          $fatal(1, "[PROTOCOL] costas_stream output changed under backpressure");
      end
      output_held = m_valid && !m_ready;
      if (output_held) begin
        held_output = {m_valid, m_last, m_re, m_im, m_phase};
        // Negative control corrupts the saved snapshot only, never the DUT.
        if (!injected_hold && $test$plusargs("INJECT_HOLD_MISMATCH")) begin
          held_output[0] = ~held_output[0];
          injected_hold = 1;
        end
      end
    end
  end

  // Scoreboard: every accepted output must equal the model exactly (re, im, phase used, last flag).
  always @(posedge clk) if (rst != RESET_ACTIVE) begin
    int re, im, phase, last;
    if (scoring && m_valid && m_ready) begin
      out_checked = out_checked + 1;
      if (obs != 0) $fdisplay(obs, "%0d %0d %0d %0d", m_re, m_im, m_phase, m_last);
      if (no_score) begin
      end else begin
      rc = $fscanf(cof, "%d %d %d %d", re, im, phase, last);
      if (inject && out_checked == 1) re = re + 1;
      if (m_re !== 18'(re) || m_im !== 18'(im) || m_phase !== phase || m_last !== 1'(last)) begin
        $display("MISMATCH output %0d: %0d,%0d/%0d,%0d phase %0d/%0d last %0d/%0d",
                 out_checked, m_re, m_im, re, im, m_phase, phase, m_last, last);
        $fatal(1, "[NUMERIC] costas_stream output");
      end
      end
    end
  end
  // A pipeline ADVANCE is a clock without backpressure (the RTL freezes every stage otherwise), so the
  // sample-domain delay is counted in advances, exactly like sync_fixed.costas_pipelined(..., gaps).
  always @(posedge clk) if (rst != RESET_ACTIVE && (m_ready || !m_valid)) advance = advance + 1;
  // Throughput and gap monitors (accepted samples / accepted outputs).
  bit prev_accept = 0, prev_out = 0;
  longint last_accept_cycle = 0, last_out_cycle = 0;
  always @(posedge clk) if (rst != RESET_ACTIVE && scoring) begin
    if (s_valid && s_ready) begin
      accepted = accepted + 1;
      if (alf != 0) $fdisplay(alf, "%0d", advance);
      if (span_first < 0) span_first = cycle;
      run_len = prev_accept ? run_len + 1 : 1;
      if (run_len > run_max) run_max = run_len;
      if (accepted > 1 && cycle - last_accept_cycle - 1 > gap_max) gap_max = cycle - last_accept_cycle - 1;
      last_accept_cycle = cycle; span_last = cycle; prev_accept = 1;
    end else prev_accept = 0;
    if (m_valid && m_ready) begin
      if (out_checked > 1 && cycle - last_out_cycle - 1 > out_gap_max)
        out_gap_max = cycle - last_out_cycle - 1;
      last_out_cycle = cycle; prev_out = 1;
    end else prev_out = 0;
  end
  always @(posedge clk) if (rst != RESET_ACTIVE && !scoring && ((m_valid && m_ready))) warm_out = warm_out + 1;

  task automatic drive_cfg;
    @(negedge clk);
    cfg_valid = 1; cfg_k1 = 32'(k1); cfg_k2 = 32'(k2);
    for (int guard = 0; guard < 65536; guard++) begin
      @(posedge clk);
      if (cfg_valid && cfg_ready) break;
      if (guard == 65535) $fatal(1, "[TIMEOUT] costas_stream never accepted the configuration");
    end
    @(negedge clk); cfg_valid = 0;
    for (int guard = 0; guard < 65536; guard++) begin
      @(posedge clk);
      if (configured) return;
      if (guard == 65535) $fatal(1, "[TIMEOUT] costas_stream never configured");
    end
  endtask
  // Offer one sample at the next negedge and wait for its accepting posedge. `probe` additionally
  // raises cfg_valid for the very same posedge: a configuration offered while samples are in flight
  // must be refused (cfg_ready low) and must not disturb the stream.
  task automatic drive_in(input int re, input int im, input int last, input bit probe = 0);
    if (stall_in && (($urandom % 8) == 0)) begin
      @(negedge clk); s_valid = 0; repeat (1 + $urandom % 4) @(negedge clk);
    end else @(negedge clk);
    s_valid = 1; s_re = 18'(re); s_im = 18'(im); s_last = 1'(last);
    if (probe) begin cfg_valid = 1; cfg_k1 = 32'(k1 + 1); cfg_k2 = 32'(k2 + 1); end
    for (int guard = 0; guard < 65536; guard++) begin
      @(posedge clk);
      if (probe && cfg_ready) $fatal(1, "[PROTOCOL] cfg accepted while samples were still in flight");
      if (s_valid && s_ready) begin
        if (probe) cfg_valid = 0;
        return;
      end
      if (guard == 65535) $fatal(1, "[THROUGHPUT] input sample never accepted (cycle %0d)", cycle);
    end
  endtask

  initial begin
    int re, im, last;
    if (!$value$plusargs("VECTORS=%s", directory)) $fatal(1, "VECTORS is required");
    stall_in = $test$plusargs("STALL_INPUT"); stall_out = $test$plusargs("STALL_OUTPUT");
    inject = $test$plusargs("INJECT_MISMATCH"); cfg_probe = $test$plusargs("CFG_PROBE");
    reset_mid = $test$plusargs("RESET_MID");
    no_score = $test$plusargs("NO_SCORE");
    if ($value$plusargs("ACCEPT_LOG=%s", accept_log)) alf = $fopen(accept_log, "w");
    if ($value$plusargs("OBSERVED=%s", observed)) obs = $fopen(observed, "w");
    ccf = $fopen({directory, "/cl_cfg.txt"}, "r");
    rc = $fscanf(ccf, "%d %d", k1, k2);
    $fclose(ccf);
    cif = $fopen({directory, "/cl_in.txt"}, "r");
    rc = $fscanf(cif, "%d", in_total);
    in_re = new[in_total]; in_im = new[in_total]; in_last = new[in_total];
    for (int j = 0; j < in_total; j = j + 1) begin
      rc = $fscanf(cif, "%d %d %d", re, im, last);
      in_re[j] = re; in_im[j] = im; in_last[j] = last;
    end
    $fclose(cif);
    if (!no_score) begin
      cof = $fopen({directory, "/cl_out.txt"}, "r");
      rc = $fscanf(cof, "%d", out_total);
    end else out_total = in_total;
    repeat (10) @(negedge clk); rst = !RESET_ACTIVE; repeat (3) @(negedge clk);
    drive_cfg;
    if (reset_mid) begin
      scoring = 0;
      for (int j = 0; j < (in_total / 2); j = j + 1) drive_in(in_re[j], in_im[j], in_last[j]);
      @(negedge clk); s_valid = 0; s_last = 0;
      @(negedge clk); rst = RESET_ACTIVE;
      repeat (5) @(negedge clk); rst = !RESET_ACTIVE;
      @(negedge clk);
      if (m_valid !== 1'b0) $fatal(1, "[RESET] output valid after mid-stream reset");
      if (configured !== 1'b0) $fatal(1, "[RESET] configured survived the reset");
      accepted = 0; run_len = 0; run_max = 0; gap_max = 0; out_gap_max = 0;
      span_first = -1; span_last = -1; prev_accept = 0; prev_out = 0; out_checked = 0;
      scoring = 1;
      drive_cfg;
    end
    for (int j = 0; j < in_total; j = j + 1)
      drive_in(in_re[j], in_im[j], in_last[j], cfg_probe && j == in_total / 3);
    @(negedge clk); s_valid = 0; s_last = 0;
    for (int t = 0; t < 100000; t = t + 1) begin
      @(negedge clk);
      idle_cycles = m_valid ? 0 : idle_cycles + 1;
      if (!no_score && out_checked >= out_total) t = 100000;
      else if (no_score && idle_cycles > 40) t = 100000;
    end
    if (!no_score && out_checked != out_total)
      $fatal(1, "[TIMEOUT] %0d of %0d outputs delivered", out_checked, out_total);
    if (no_score && out_checked != in_total)
      $fatal(1, "[COUNT] %0d of %0d outputs delivered", out_checked, in_total);
    if (accepted != in_total) $fatal(1, "[COUNT] %0d of %0d samples accepted", accepted, in_total);
    if (cfg_probe) begin
      // Once the pipeline is empty a configuration must be accepted again.
      @(negedge clk); cfg_valid = 1; cfg_k1 = 32'(k1); cfg_k2 = 32'(k2);
      for (int guard = 0; guard < 64; guard++) begin
        @(posedge clk);
        if (cfg_valid && cfg_ready) begin
          @(negedge clk); cfg_valid = 0;
          $display("CFG_PROBE: refused while busy, accepted when idle");
          guard = 64;
        end else if (guard == 63) $fatal(1, "[PROTOCOL] cfg never re-armed after the stream");
      end
    end
    if (!stall_in && !stall_out && !reset_mid && run_max != accepted)
      $fatal(1, "[THROUGHPUT] longest accept run %0d of %0d samples (II != 1)", run_max, accepted);
    if (!stall_in && !stall_out && gap_max != 0)
      $fatal(1, "[THROUGHPUT] input gap %0d cycles without stall plusargs", gap_max);
    if (stall_out && hold_checks == 0)
      $fatal(1, "[COVERAGE] no stalled output was checked");
    if (alf != 0) $fclose(alf);
    if (obs != 0) $fclose(obs);
    repeat (5) @(negedge clk);
    $display("COSTAS_STREAM backpressure hold checks: %0d", hold_checks);
    $display("PASS COSTAS_STREAM: %0d samples, %0d outputs, run_max %0d, gap_max %0d, out_gap_max %0d, span %0d, cycles %0d",
             accepted, out_checked, run_max, gap_max, out_gap_max, span_last - span_first, cycle);
    $finish;
  end
  initial begin #200000000; $fatal(1, "COSTAS_STREAM testbench did not drain"); end
endmodule
