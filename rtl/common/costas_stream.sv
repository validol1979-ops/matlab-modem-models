// Continuous-rate (II=1) QPSK Costas loop: the same per-sample arithmetic as costas_loop.sv
// (same phase LUT rotator bpsk_rotate, same 18-bit signed values, same round/saturate, same
// 32-bit phase wrap, same K1/K2 = round(k/(2 pi)*2^33) configuration, same error
// sign(re)*im - sign(im)*re and frequency/phase update order), but fully pipelined so that one
// sample is accepted every clock.
//
// Loop delay. costas_loop.sv applies the error of a sample to the phase register before the next
// sample is rotated (a delay of one sample) by waiting the whole 7-clock rotator latency plus one
// UPDATE clock for every sample, which gives II=8. Here the rotator and the loop filter run as a
// pipeline and the error is applied 10 ADVANCES later (rotator latency 7, error stage, product
// stage, update stage), so LOOP_DELAY=10 advances = 1.25 symbols at sps=8. An advance is a clock
// without backpressure: a stall freezes every stage through one shared clock enable, so it removes
// advances and leaves the outputs unchanged, while an INPUT bubble is a missing advance that
// shortens the delay in samples (the delay in ADVANCES stays 10). That distinction is measured in
// rtl/tb/costas_stream_tb.sv (+STALL_OUTPUT reproduces the dense vectors, +STALL_INPUT is scored
// against the model fed with the logged acceptance pattern).
//
// Admissible gains shrink with the delay. With the measured QPSK detector slope and the loop's own
// update order (frequency next is used in the phase update) the characteristic polynomial
// z^10 (z-1)^2 + a z (z-1) + b z^2 has spectral radius 0.985 at k=(.08,.001), 0.992 at
// k=(.02,.0001) and 1.056 at k=(.3,.01): the aggressive acquisition setting of costas_loop.sv is
// NOT stable at this delay, and the integer model stops locking at 3 advances of delay for it.
// The 1.9x gain margin applies only along k2=k1/80; independent upper bounds on k1 and k2 do
// not guarantee stability. Check the actual gain pair and signal amplitude; keep costas_loop.sv
// for the tested high-gain acquisition setting.
// Numbers and method: docs/RTL_COSTAS_STREAM.md.
//
// Frame boundary. Unlike costas_loop.sv, which restarts from phase=frequency=0 for every
// transaction, this loop is continuous: s_last only marks the last sample of a group and is copied
// to m_last, the loop state persists across the boundary. A restart is available through an idle
// gap: cfg_ready is high only when no sample is accepted-but-not-delivered (busy==0 and no pending
// output), and taking a new configuration zeroes nothing by itself - reconfigure with the same gains
// and reset the module for a fresh start, or use costas_loop.sv for per-frame acquisition.
//
// Throughput. With s_valid held high and m_ready high, one sample is accepted every clock (II=1);
// the bench measures the longest run of consecutive accepts instead of assuming it.
// Backpressure never drops a sample: s_ready drops while the pending output is not consumed and the
// whole pipeline freezes. Functionally verified only; synthesis is on the agreed pause, so this
// header makes no physical clock-period or Fmax claim.
module costas_stream #(
  parameter bit RESET_ACTIVE = 1,
  parameter TABLE_DIR = "rtl/modems/bpsk_costas_2008_08_25/tables"
)(
  input logic clk, rst,
  input logic cfg_valid,
  input logic [31:0] cfg_k1, cfg_k2,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  output logic signed [31:0] m_phase,
  input logic m_ready
);
  wire reset_now = rst == RESET_ACTIVE;
  logic [31:0] k1, k2;
  logic signed [31:0] phase, frequency;
  logic [4:0] busy;                       // accepted but not yet delivered outputs
  wire stall = m_valid && !m_ready;
  wire pipeline_empty = busy == '0 && !m_valid;
  assign cfg_ready = !reset_now && pipeline_empty;
  wire cfg_take = cfg_valid && cfg_ready;
  assign s_ready = !reset_now && configured && !stall && !cfg_take;
  wire take = s_valid && s_ready;
  wire ce = !stall;                       // one shared clock enable freezes every stage

  // Rotator: latency 7, II=1 when ce=1. The upper tag bits are zero (only the last flag travels).
  wire signed [17:0] r_re, r_im;
  wire [31:0] r_tag;
  wire r_valid;
  wire tag_ok = r_tag[31:1] == '0;   // only the last flag travels through the rotator (as costas_loop.sv)
  bpsk_rotate #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) rotation(
    clk,rst,ce,take,s_re,s_im,phase[31:20],25'd1048576,{31'd0,s_last},r_valid,r_re,r_im,r_tag);

  // The phase used for a sample travels next to the rotator pipe (7 stages, same shifting).
  logic signed [31:0] phase_pipe [0:6];

  // Error stage: the rotated value and its phase are registered, the discriminator is combinational.
  logic signed [19:0] error_q;
  logic [1:0] error_valid;

  // Product stage: d1 = K1*error, d2 = K2*error (51 bits as in costas_loop.sv).
  logic signed [50:0] d1, d2;

  wire signed [1:0] sign_re = r_re > 0 ? 2'sd1 : r_re < 0 ? -2'sd1 : 2'sd0;
  wire signed [1:0] sign_im = r_im > 0 ? 2'sd1 : r_im < 0 ? -2'sd1 : 2'sd0;
  wire signed [19:0] error = 20'(sign_re)*20'(r_im) - 20'(sign_im)*20'(r_re);
  wire signed [31:0] frequency_next = frequency + 32'((d2 + 51'sd32768) >>> 16);

  always_ff @(posedge clk) begin
    if (reset_now) begin
      configured <= 0; busy <= '0; phase <= '0; frequency <= '0;
      m_valid <= 0; m_re <= '0; m_im <= '0; m_phase <= '0; m_last <= 0;
      error_q <= '0; error_valid <= '0; d1 <= '0; d2 <= '0;
      for (int j = 0; j < 7; j = j + 1) phase_pipe[j] <= '0;
    end
    else begin
      if (cfg_take) begin k1 <= cfg_k1; k2 <= cfg_k2; configured <= 1; end
      if (m_valid && m_ready) m_valid <= 0;
      if (take && !(m_valid && m_ready)) busy <= busy + 1'b1;
      else if (!take && (m_valid && m_ready)) busy <= busy - 1'b1;
      if (ce) begin
        // Output stage: the rotated value, the phase that was used for it and its last flag.
        m_valid <= r_valid && tag_ok;
        if (r_valid && tag_ok) begin
          m_re <= r_re; m_im <= r_im; m_phase <= phase_pipe[6]; m_last <= r_tag[0];
        end
        // Error stage.
        error_valid <= {error_valid[0], r_valid};
        error_q <= error;
        for (int j = 0; j < 7; j = j + 1)
          phase_pipe[j] <= j == 0 ? phase : phase_pipe[j-1];
        // Product stage (one sample older than the error stage).
        d1 <= 51'($signed({1'b0, k1})) * 51'(error_q);
        d2 <= 51'($signed({1'b0, k2})) * 51'(error_q);
        // Update stage: the error of the sample accepted ten clocks earlier.
        if (error_valid[1]) begin
          frequency <= frequency_next;
          phase <= phase + frequency_next + 32'((d1 + 51'sd32768) >>> 16);
        end
      end
    end
  end
endmodule
