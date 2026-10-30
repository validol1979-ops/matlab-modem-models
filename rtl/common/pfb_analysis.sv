// Polyphase analysis bank (research_core pfb/wola; bit-exact reference pfb_fixed.analyze).
// M = 2^LOG2M channels (4..64), runtime taps (T <= 2^LOG2TMAX, Q17) and decimation D
// (1..M) from the configuration port. One transaction is one signal of L Q15 samples
// (s_last on its last sample); for every output time end = 0, D, 2D, ... < L it gives M
// bins (m_last on the transaction's very last bin):
//   acc[n] = sum_{j <= min(end, T-1), j mod M = n} H[j]*x[end-j] (exact),
//   p[n] = sat22(round(acc[n], 13)) (Q19), q[m] = p[(m + end) mod M] (the exp(2j pi k end/M)
//   rotation as a circular shift), Y = fft_r2sdf forward (22 -> 24 bit) = fft(q)/M in Q19.
// LANES = 2^LOG2LANES multiply-accumulate lanes (LANES divides M): step c handles taps
// j = c*LANES + l. Taps sit in LANES banks (bank l, address c), the signal history in LANES
// banks of a ring of RING samples (sample t in bank t mod LANES), so each step reads one
// word per bank; lane l takes bank (end - l) mod LANES. An output time takes ceil(T/LANES)
// steps plus 4 pipeline clocks; the next one accumulates while the previous phases feed the
// FFT (M clocks), so one output time costs about max(ceil(T/LANES) + 5, M) clocks.
// An output time starts once its sample and the next output time's samples are in (or s_last
// is seen), so its finality is known; a flag FIFO carries it to the FFT output. The input may
// run ahead of the oldest needed sample by RING - TMAX; after s_last it waits until the
// transaction's last output time has been accumulated. Configuration is accepted only between
// transactions. error is sticky: more than TMAX taps, D outside 1..M, or the core error.
module pfb_analysis #(
  parameter int LOG2M = 2,
  parameter int LOG2LANES = 2,
  parameter int LOG2TMAX = 6,
  parameter bit RESET_ACTIVE = 1,
  parameter TWIDDLE_FILE = "rtl/common/mem/fft_twiddle_4.mem",
  parameter int ACC_WIDTH = 36 + (LOG2TMAX > LOG2M ? LOG2TMAX - LOG2M : 0)
)(
  input logic clk, rst,
  input logic cfg_valid, cfg_last,
  input logic signed [17:0] cfg_tap,
  input logic [LOG2M:0] cfg_decimation,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [23:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  localparam int M = 1 << LOG2M;
  localparam int LANES = 1 << LOG2LANES;
  localparam int TMAX = 1 << LOG2TMAX;
  localparam int LOG2RING = (LOG2TMAX > LOG2M ? LOG2TMAX : LOG2M) + 2;
  localparam int RING = 1 << LOG2RING;
  localparam int BW = LOG2RING - LOG2LANES;                         // history bank address
  localparam int TW = LOG2TMAX > LOG2LANES ? LOG2TMAX - LOG2LANES : 1; // tap bank address
  localparam int SW = LOG2TMAX - LOG2LANES + 1;                     // step counter
  // Each phase contains at most ceil(TMAX/M) real signed18 products, not TMAX.
  // A product can equal +2^34, requiring 36 bits; each doubling adds one bit.
  // The same width also contains the +4096 rounding bias at the upper bound.
  localparam int SAFE_AW = 36 + (LOG2TMAX > LOG2M ? LOG2TMAX - LOG2M : 0);
  localparam int AW = ACC_WIDTH;
  localparam int LB = LOG2LANES > 0 ? LOG2LANES : 1;                // lane index
  localparam logic signed [AW-1:0] HALF = AW'(4096);
  wire reset_now = rst == RESET_ACTIVE;
  initial if(ACC_WIDTH < SAFE_AW || ACC_WIDTH > 63)
    $fatal(1,"[PARAMETER] PFB ACC_WIDTH must be in %0d..63",SAFE_AW);

  function automatic logic signed [21:0] sat22(input logic signed [AW-1:0] value);
    logic signed [AW-1:0] rounded;
    rounded = (value + HALF) >>> 13;
    if (rounded[AW-1:21] != {(AW-21){rounded[AW-1]}}) return rounded[AW-1] ? 22'sh200000 : 22'sd2097151;
    return rounded[21:0];
  endfunction

  // Configuration.
  logic [LOG2TMAX:0] tap_count, taps;
  logic [LOG2M:0] decimation;
  wire cfg_take = cfg_valid && cfg_ready;
  // Transaction state.
  logic [23:0] wcount, next_end, cur_end;
  logic last_seen, cur_final;
  typedef enum logic [1:0] {IDLE, RUN, DRAIN, DONE} state_t;
  state_t state;
  logic [SW-1:0] step, steps;
  logic [2:0] drain;
  // Feed of the rotated phases into the FFT.
  logic feeding;
  logic [LOG2M-1:0] feed_index, feed_shift;
  logic signed [21:0] phase_re [0:M-1], phase_im [0:M-1];
  logic [7:0] final_fifo;
  logic [2:0] final_head, final_tail;
  wire f_ready, f_valid, f_last, f_inverse, f_error;
  wire busy = wcount != '0 || last_seen || state != IDLE || feeding;
  assign cfg_ready = !reset_now && !busy;
  wire [23:0] oldest = state == IDLE ? next_end : cur_end;
  assign s_ready = !reset_now && configured && !cfg_take && !last_seen && wcount < oldest + 24'(RING - TMAX);
  wire take = s_valid && s_ready;
  wire [23:0] d24 = 24'(decimation);
  wire start = configured && state == IDLE && wcount > next_end && (wcount > next_end + d24 || last_seen);
  wire issue = state == RUN;

  // Banks: taps (bank l, address c) and history (sample t in bank t mod LANES).
  wire [17:0] tap_q [0:LANES-1];
  wire [35:0] hist_q [0:LANES-1];
  genvar b;
  generate
    for (b = 0; b < LANES; b = b + 1) begin : g_bank
      // Bank b holds the samples t = b mod LANES; at step c lane l = (end - b) mod LANES
      // reads t = end - c*LANES - l, i.e. word (end >> LOG2LANES) - (b > end mod LANES) - c.
      wire borrow;
      if (b == 0) begin : g_first
        assign borrow = 1'b0;
      end else begin : g_other
        assign borrow = (cur_end & 24'(LANES - 1)) < 24'(b);
      end
      wire [BW-1:0] base = BW'(cur_end >> LOG2LANES) - BW'(borrow);
      sync_ram #(.WIDTH(18),.ADDR_WIDTH(TW)) tap_bank(
        .clk(clk),.wr_en(cfg_take && (tap_count & (LOG2TMAX+1)'(LANES-1)) == (LOG2TMAX+1)'(b)),.rd_en(issue),
        .wr_addr(TW'(tap_count >> LOG2LANES)),.rd_addr(TW'(step)),.wr_data(cfg_tap),.rd_data(tap_q[b]));
      sync_ram #(.WIDTH(36),.ADDR_WIDTH(BW)) hist_bank(
        .clk(clk),.wr_en(take && (wcount & 24'(LANES-1)) == 24'(b)),.rd_en(issue),
        .wr_addr(BW'(wcount >> LOG2LANES)),.rd_addr(base - BW'(step)),.wr_data({s_re,s_im}),.rd_data(hist_q[b]));
    end
  endgenerate

  // Pipeline: issue -> i (step and validity registered) -> r (lane operands) -> p (products)
  // -> accumulate.
  logic i_valid [0:LANES-1], r_valid [0:LANES-1], p_valid [0:LANES-1];
  logic [LOG2M-1:0] i_index [0:LANES-1], r_index [0:LANES-1], p_index [0:LANES-1];
  logic [LB-1:0] i_end_low;
  logic signed [17:0] r_tap [0:LANES-1], r_re [0:LANES-1], r_im [0:LANES-1];
  logic signed [35:0] p_re [0:LANES-1], p_im [0:LANES-1];
  (* use_dsp="no" *) logic signed [AW-1:0] acc_re [0:M-1], acc_im [0:M-1];

  fft_r2sdf #(.LOG2N(LOG2M),.IN_WIDTH(22),.WIDTH(24),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) fft(
    .clk(clk),.rst(rst),.s_valid(feeding),.s_last(feed_index == LOG2M'(M-1)),.s_inverse(1'b0),
    .s_re(phase_re[LOG2M'(feed_index + feed_shift)]),.s_im(phase_im[LOG2M'(feed_index + feed_shift)]),.s_ready(f_ready),
    .m_valid(f_valid),.m_last(f_last),.m_inverse(f_inverse),.m_re(m_re),.m_im(m_im),.m_ready(m_ready),.error(f_error));
  assign m_valid = f_valid;
  assign m_last = f_last && final_fifo[final_head];

  always_ff @(posedge clk) begin
    // Datapath pipeline.
    for (int l = 0; l < LANES; l++) begin
      // Tap j = step*LANES + l is used if j < T and j <= end.
      i_valid[l] <= issue && (32'(step) << LOG2LANES) + 32'(l) < 32'(taps) && (32'(step) << LOG2LANES) + 32'(l) <= 32'(cur_end);
      i_index[l] <= LOG2M'((32'(step) << LOG2LANES) + 32'(l));
      r_valid[l] <= i_valid[l]; r_index[l] <= i_index[l]; r_tap[l] <= $signed(tap_q[l]);
      r_re[l] <= $signed(hist_q[LB'(i_end_low - LB'(l)) & LB'(LANES-1)][35:18]);
      r_im[l] <= $signed(hist_q[LB'(i_end_low - LB'(l)) & LB'(LANES-1)][17:0]);
      p_valid[l] <= r_valid[l]; p_index[l] <= r_index[l];
      p_re[l] <= r_tap[l]*r_re[l]; p_im[l] <= r_tap[l]*r_im[l];
    end
    i_end_low <= LB'(cur_end) & LB'(LANES-1);
    // Accumulators: phase n is only ever touched by lane n mod LANES.
    for (int n = 0; n < M; n++) begin
      if (start) begin acc_re[n] <= '0; acc_im[n] <= '0; end
      else if (p_valid[n % LANES] && p_index[n % LANES] == LOG2M'(n)) begin
        acc_re[n] <= acc_re[n] + AW'(p_re[n % LANES]); acc_im[n] <= acc_im[n] + AW'(p_im[n % LANES]);
      end
    end
    if (reset_now) begin
      configured <= 0; error <= 0; tap_count <= '0; taps <= '0; decimation <= '0;
      wcount <= '0; next_end <= '0; cur_end <= '0; last_seen <= 0; state <= IDLE; step <= '0; drain <= '0;
      feeding <= 0; feed_index <= '0; final_head <= '0; final_tail <= '0;
    end else begin
      if (cfg_take) begin
        configured <= 0; tap_count <= tap_count + 1'b1;
        if (tap_count >= (LOG2TMAX+1)'(TMAX)) error <= 1;
        if (cfg_last) begin
          tap_count <= '0; taps <= tap_count + 1'b1; decimation <= cfg_decimation;
          if (tap_count < (LOG2TMAX+1)'(TMAX) && cfg_decimation >= (LOG2M+1)'(1) && cfg_decimation <= (LOG2M+1)'(M)) configured <= 1;
          else error <= 1;
        end
      end
      if (take) begin wcount <= wcount + 1'b1; if (s_last) last_seen <= 1; end
      case (state)
        IDLE: if (start) begin
          state <= RUN; step <= '0; cur_end <= next_end; next_end <= next_end + d24;
          cur_final <= last_seen && next_end + d24 >= wcount;
          steps <= SW'((taps + (LOG2TMAX+1)'(LANES-1)) >> LOG2LANES);
        end
        RUN: begin step <= step + 1'b1; if (step == steps - 1'b1) begin state <= DRAIN; drain <= 3'd4; end end
        DRAIN: begin drain <= drain - 1'b1; if (drain == 3'd1) state <= DONE; end
        DONE: if (!feeding) begin
          // Hand the rounded phases to the feed; a final output time ends the transaction.
          for (int n = 0; n < M; n++) begin phase_re[n] <= sat22(acc_re[n]); phase_im[n] <= sat22(acc_im[n]); end
          feeding <= 1; feed_index <= '0; feed_shift <= LOG2M'(cur_end);
          final_fifo[final_tail] <= cur_final; final_tail <= final_tail + 1'b1;
          state <= IDLE;
          if (cur_final) begin wcount <= '0; next_end <= '0; last_seen <= 0; end
        end
        default: state <= IDLE;
      endcase
      if (feeding && f_ready) begin
        feed_index <= feed_index + 1'b1;
        if (feed_index == LOG2M'(M-1)) feeding <= 0;
      end
      if (f_valid && m_ready && f_last) final_head <= final_head + 1'b1;
      if (f_error || f_valid && f_inverse) error <= 1;
    end
  end
endmodule
