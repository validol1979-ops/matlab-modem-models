// Streaming radix-2 FFT/IFFT, single-path delay feedback, decimation in frequency
// (bit-exact reference common/python/fft_fixed.py). N = 2^LOG2N, LOG2N = 2..10, one
// complex sample per clock, frames of exactly N samples back to back.
// Formats: input IN_WIDTH bits (default 18), data and output WIDTH bits (default 20;
// IN_WIDTH + 1 <= WIDTH <= 24: one 25x18 DSP per product, |X/N| < 2^(IN_WIDTH-1)*sqrt 2).
// s_inverse = 0: FFT(x)/N, every stage halves, so
// nothing can overflow (|X/N| <= max |x|). s_inverse = 1: sum_k y_k exp(+2j pi k t/N)
// without 1/N (the exact inverse of the forward transform), computed as conj of the
// unhalved transform of conj(y); its stages round by 16 instead of 17 bits and saturate
// to +-(2^(WIDTH-1)-1). The direction travels with every sample (one bit in the delay lines),
// so consecutive frames may differ.
// Stage s (D = N/2^(s+1)): position c of the sample in its group of 2D; c < D shifts the
// input into the delay line and outputs the stored difference of butterfly j = c with
// twiddle k = j*2^s; c >= D outputs the sum a+b (k = 0) and stores a-b. The output is
// multiplied by the Q16 ROM twiddle (cos, sin) and rounded half up (the last stage,
// always k = 0, needs no multiplier). Each stage adds P = 4 pipeline registers (operand
// and ROM read, products, rounded and shifted sums, saturation), so the chain latency is
// L = N-1 + 4*LOG2N advances; the chain output comes in bit-reversed order.
// Advance: the whole chain moves only when a sample is accepted or a bubble is inserted.
// Back-to-back frames never insert bubbles. When a frame has ended and no next sample is
// offered, the core drains: s_ready drops and L bubbles flush the chain (pending counts
// the advances still needed after the last sample). A frame that starts on an empty chain
// restarts the group counters. Gaps inside a frame just stop the chain.
// Valid chain outputs are those at least L advances after the start of the current burst
// of frames, while a sample is accepted or pending > 0.
// Reorder: two banks of N words in one sync_ram; output i of a frame goes to address
// bitrev(i), a full bank is read in natural order into a 4-entry output FIFO (m_ready
// backpressure). The chain stalls only if the next bank to write is still full.
// Latency (m_ready = 1): about L + N + 3 clocks from the first input sample of a frame to
// its first output. Resources: 4 multipliers per stage except the last, one delay line
// per stage (registers up to 16 deep, RAM beyond), one twiddle ROM per stage, one RAM.
// error is sticky: s_last not on the N-th sample (the frame still ends after N samples).
module fft_r2sdf #(
  parameter int LOG2N = 6,
  parameter int IN_WIDTH = 18,
  parameter int WIDTH = 20,
  parameter bit RESET_ACTIVE = 1,
  parameter TWIDDLE_FILE = "rtl/common/mem/fft_twiddle_64.mem"
)(
  input logic clk, rst,
  input logic s_valid, s_last, s_inverse,
  input logic signed [IN_WIDTH-1:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last, m_inverse,
  output logic signed [WIDTH-1:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  localparam int N = 1 << LOG2N;
  localparam int P = 4;
  localparam int L = N - 1 + P*LOG2N;
  localparam int LW = $clog2(L + 1);
  // Widths: data W, butterfly V = W+1, products V+18, sums V+19, shifted sums H = W+4.
  localparam int W = WIDTH, V = WIDTH + 1, PW = WIDTH + 19, SW = WIDTH + 20, H = WIDTH + 4;
  localparam logic signed [W-1:0] MAX = W'((1 << (W - 1)) - 1);
  localparam logic signed [W-1:0] MIN = W'(1 - (1 << (W - 1)));
  function automatic int offset(input int stage);
    int total;
    total = 0;
    for (int t = 0; t < stage; t++) total += (N >> (t + 1)) + P;
    return total % N;
  endfunction
  function automatic logic [LOG2N-1:0] bitrev(input logic [LOG2N-1:0] value);
    for (int b = 0; b < LOG2N; b++) bitrev[b] = value[LOG2N-1-b];
  endfunction
  // Saturate a rounded, shifted value to +-(2^(W-1)-1) (sign-extension check).
  function automatic logic signed [W-1:0] sat(input logic signed [H-1:0] value);
    if (value[H-1:W-1] != {(H-W+1){value[H-1]}}) return value[H-1] ? MIN : MAX;
    if (value[W-1:0] == {1'b1, {(W-1){1'b0}}}) return MIN;
    return value[W-1:0];
  endfunction
  wire reset_now = rst == RESET_ACTIVE;

  // Input side: frame position, inverse flag, burst and drain control.
  logic [LOG2N-1:0] in_count, gcount;
  logic frame_inverse, draining;
  logic [LW-1:0] pending, fill;
  logic chain_valid, adv, take, bubble;
  logic [LOG2N-1:0] gcount_now;
  logic [LW-1:0] fill_now;
  wire first = in_count == '0;
  wire burst_start = first && pending == '0;
  // Reorder write side.
  logic wbank, rbank;
  logic [1:0] full, bank_inverse;
  logic [LOG2N-1:0] out_count;
  // Reader and output FIFO.
  logic [LOG2N-1:0] ridx;
  logic inflight, inflight_last, inflight_inverse;
  logic [2*W+1:0] fifo [0:3];
  logic [1:0] fifo_head, fifo_tail;
  logic [2:0] fifo_count;
  wire [2*W-1:0] ram_q;
  wire read_issue = full[rbank] && ({1'b0,fifo_count} + {3'd0,inflight}) < 4'd4;
  wire pop = m_valid && m_ready;

  // The chain output of this advance is a frame sample when the burst has run L advances
  // and the advance carries a sample or flushes a pending frame.
  always_comb begin
    fill_now = burst_start ? '0 : fill;
    gcount_now = burst_start ? '0 : gcount;
    chain_valid = fill_now == LW'(L);
    // A real advance: the output must have a free bank (or be a non-sample).
    s_ready = !reset_now && !draining && (!chain_valid || !full[wbank]);
    take = s_valid && s_ready;
    bubble = !reset_now && draining && (!chain_valid || !full[wbank]);
    adv = take || bubble;
  end

  // Stage 0 input: conj for the inverse, zeros for bubbles, sign-extended to 20 bits.
  wire inverse_now = first ? s_inverse : frame_inverse;
  logic signed [W-1:0] stage_re [0:LOG2N], stage_im [0:LOG2N];
  logic stage_inv [0:LOG2N];
  assign stage_inv[0] = !bubble && inverse_now;
  assign stage_re[0] = bubble ? '0 : W'(s_re);
  assign stage_im[0] = bubble ? '0 : inverse_now ? W'(0) - W'(s_im) : W'(s_im);

  genvar g;
  generate
    for (g = 0; g < LOG2N; g = g + 1) begin : g_stage
      localparam int D = N >> (g + 1);
      localparam int CW = LOG2N - g;
      wire [CW-1:0] c = CW'(gcount_now - LOG2N'(offset(g)));
      wire upper = c[CW-1];
      wire [2*V:0] delayed;
      wire a_inv = delayed[2*V];
      wire signed [V-1:0] a_re = delayed[2*V-1:V], a_im = delayed[V-1:0];
      // Sums take the flag of the current group, stored differences their own.
      wire v_inv = upper ? stage_inv[g] : a_inv;
      wire signed [V-1:0] b_re = V'(stage_re[g]), b_im = V'(stage_im[g]);
      wire signed [V-1:0] v_re = upper ? a_re + b_re : a_re;
      wire signed [V-1:0] v_im = upper ? a_im + b_im : a_im;
      wire signed [V-1:0] w_re = upper ? a_re - b_re : b_re;
      wire signed [V-1:0] w_im = upper ? a_im - b_im : b_im;
      fft_delay #(.WIDTH(2*V+1),.DEPTH(D),.RESET_ACTIVE(RESET_ACTIVE)) line(.clk(clk),.rst(rst),.ce(adv),.s_data({stage_inv[g],w_re,w_im}),.m_data(delayed));
      logic signed [V-1:0] v1_re, v1_im;
      logic v1_inv, v2_inv, v3_inv, r_inv;
      if (g < LOG2N - 1) begin : g_twiddle
        // Twiddle k = j*2^s for the stored differences, 0 for the sums.
        wire [LOG2N-2:0] k = upper ? '0 : (LOG2N-1)'(c[CW-2:0]) << g;
        wire [35:0] twiddle;
        sync_rom #(.WIDTH(36),.ADDR_WIDTH(LOG2N-1),.INIT_FILE(TWIDDLE_FILE)) rom(
          .clk(clk),.rd_en(adv),.rd_addr(k),.rd_data(twiddle));
        wire signed [17:0] cosine = twiddle[35:18], sine = twiddle[17:0];
        logic signed [PW-1:0] p_rc, p_is, p_ic, p_rs;
        logic signed [H-1:0] h_re, h_im;
        logic signed [W-1:0] r_re, r_im;
        // Round half up: forward + 2^16 then >>> 17, inverse + 2^15 then >>> 16.
        wire signed [SW-1:0] rounding = v2_inv ? SW'(32768) : SW'(65536);
        wire [4:0] shift = v2_inv ? 5'd16 : 5'd17;
        always_ff @(posedge clk) if (adv) begin
          v1_re <= v_re; v1_im <= v_im; v1_inv <= v_inv; v2_inv <= v1_inv; v3_inv <= v2_inv; r_inv <= v3_inv;
          p_rc <= v1_re*cosine; p_is <= v1_im*sine; p_ic <= v1_im*cosine; p_rs <= v1_re*sine;
          // (v_re + j v_im)(cos - j sin)
          h_re <= H'((SW'(p_rc) + SW'(p_is) + rounding) >>> shift); h_im <= H'((SW'(p_ic) - SW'(p_rs) + rounding) >>> shift);
          r_re <= sat(h_re); r_im <= sat(h_im);
        end
        assign stage_re[g+1] = r_re; assign stage_im[g+1] = r_im; assign stage_inv[g+1] = r_inv;
      end else begin : g_last
        // k = 0: W = 1 (v*2^16, rounded like the other stages); same four registers.
        logic signed [V-1:0] v2_re, v2_im;
        logic signed [H-1:0] h_re, h_im;
        logic signed [W-1:0] r_re, r_im;
        wire signed [SW-1:0] rounding = v2_inv ? SW'(32768) : SW'(65536);
        wire [4:0] shift = v2_inv ? 5'd16 : 5'd17;
        always_ff @(posedge clk) if (adv) begin
          v1_re <= v_re; v1_im <= v_im; v2_re <= v1_re; v2_im <= v1_im; v1_inv <= v_inv; v2_inv <= v1_inv; v3_inv <= v2_inv; r_inv <= v3_inv;
          h_re <= H'(((SW'(v2_re) <<< 16) + rounding) >>> shift); h_im <= H'(((SW'(v2_im) <<< 16) + rounding) >>> shift);
          r_re <= sat(h_re); r_im <= sat(h_im);
        end
        assign stage_re[g+1] = r_re; assign stage_im[g+1] = r_im; assign stage_inv[g+1] = r_inv;
      end
    end
  endgenerate

  // Reorder RAM: write {wbank, bitrev(i)}, read {rbank, ridx}.
  wire write = adv && chain_valid;
  wire signed [W-1:0] out_re = stage_re[LOG2N], out_im = stage_im[LOG2N];
  sync_ram #(.WIDTH(2*W),.ADDR_WIDTH(LOG2N+1)) reorder(
    .clk(clk),.wr_en(write),.rd_en(read_issue),
    .wr_addr({wbank,bitrev(out_count)}),.rd_addr({rbank,ridx}),
    .wr_data({out_re,out_im}),.rd_data(ram_q));
  wire signed [W-1:0] q_re = ram_q[2*W-1:W], q_im = ram_q[W-1:0];

  assign m_valid = fifo_count != 3'd0;
  assign m_re = fifo[fifo_head][2*W+1:W+2];
  assign m_im = fifo[fifo_head][W+1:2];
  assign m_last = fifo[fifo_head][1];
  assign m_inverse = fifo[fifo_head][0];

  always_ff @(posedge clk) begin
    if (reset_now) begin
      in_count <= '0; gcount <= '0; pending <= '0; fill <= '0; draining <= 0; error <= 0;
      wbank <= 0; rbank <= 0; full <= '0; out_count <= '0;
      ridx <= '0; inflight <= 0; fifo_head <= '0; fifo_tail <= '0; fifo_count <= '0;
    end else begin
      // Input frames.
      if (take) begin
        in_count <= in_count + 1'b1;
        if (first) frame_inverse <= s_inverse;
        if (s_last != (in_count == LOG2N'(N-1))) error <= 1;
      end
      // Chain counters: gcount and fill restart on a burst start; pending counts the
      // advances after a frame's last sample until its last output.
      if (adv) begin
        gcount <= gcount_now + 1'b1;
        fill <= chain_valid ? fill_now : fill_now + 1'b1;
      end
      if (take && in_count == LOG2N'(N-1)) pending <= LW'(L);
      else if (adv && pending != '0) pending <= pending - 1'b1;
      // Drain only between frames, when no next sample is taken.
      if (draining) begin
        if (adv && pending == LW'(1)) draining <= 0;
      end else if (pending != '0 && !take && first) draining <= 1;
      // Reorder writes; a completed bank takes the frame's inverse flag.
      if (write) begin
        out_count <= out_count + 1'b1;
        if (out_count == LOG2N'(N-1)) begin
          full[wbank] <= 1; bank_inverse[wbank] <= stage_inv[LOG2N]; wbank <= !wbank;
        end
      end
      // Reader: natural order, one read in flight, then into the output FIFO.
      inflight <= read_issue;
      if (read_issue) begin
        inflight_last <= ridx == LOG2N'(N-1); inflight_inverse <= bank_inverse[rbank];
        ridx <= ridx + 1'b1;
        if (ridx == LOG2N'(N-1)) begin full[rbank] <= 0; rbank <= !rbank; end
      end
      if (inflight) begin
        fifo[fifo_tail] <= {q_re, inflight_inverse ? W'(0) - q_im : q_im, inflight_last, inflight_inverse};
        fifo_tail <= fifo_tail + 1'b1;
      end
      if (pop) fifo_head <= fifo_head + 1'b1;
      fifo_count <= fifo_count + {2'd0,inflight} - {2'd0,pop};
    end
  end
endmodule
