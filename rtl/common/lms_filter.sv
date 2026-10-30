// LMS / NLMS adaptive filter (research_core lms, nlms; bit-exact reference lms_fixed.adapt).
// Configuration (one transfer, between transactions): mode (cfg_nlms), taps T <= 2^LOG2N,
// MU = round(step*2^17), EPS = round(eps*2^30) (lms_fixed.parameters). A transaction is one
// signal of (x, d) Q15 pairs (s_last on the last); it starts from zero weights and history.
// Per sample: h = [x_k .. x_{k-T+1}], pred = sat18(rnd(sum conj(w) h, 30)), e = sat18(d - pred)
// (one m_* output); LMS c = rnd(MU*conj(e), 12); NLMS: P = EPS + |h|^2 (exact, kept
// incrementally), s = bit length of P, r = ROM[top 10 bits of P] = round(2^19/m),
// c = rnd((MU*r)*conj(e), s - 9); w = sat34(w + rnd(h*c, 5)) for every tap (Q30). The update
// is used from the next sample (as the model), so a sample takes 8 clocks: products, sum,
// error and the reciprocal read, step, coefficient, tap products, weights.
// After the transaction the T weights come on w_* as sat18(rnd(w, 15)) (w_last on the last).
// Pending configuration is held until that final weight drains. At an idle boundary
// a cfg transfer takes priority over a simultaneously offered first data sample.
// error is sticky: T = 0 or T > 2^LOG2N, MU = 0, or EPS < 2^9 in NLMS mode.
module lms_filter #(
  parameter int LOG2N = 2,
  parameter bit RESET_ACTIVE = 1,
  parameter RECIP_FILE = "rtl/common/mem/lms_reciprocal.mem",
  parameter int ENERGY_WIDTH = 36 + LOG2N,
  // Intermediate expression widths (docs/RTL_LMS_WIDTHS.md); the prior layout is
  // 64/64/64/47/65/64/64 and stays legal for comparison.
  parameter int PRED_WIDTH = 53 + LOG2N,      // sum + 2^29 before the prediction round
  parameter int ERROR_WIDTH = 19,             // d - pred before sat18
  parameter int STEP_WIDTH = 46,              // k e (or -k e) plus the variable round add
  parameter int COEFF_WIDTH = 45,             // c registers after the variable round
  parameter int DELTA_WIDTH = 63,             // h c registers plus the round-5 add
  parameter int WEIGHT_WIDTH = 58,            // w + round5(h c) before sat34
  parameter int DUMP_WIDTH = 35               // w + 2^14 before the dump round and sat18
)(
  input logic clk, rst,
  input logic cfg_valid, cfg_nlms,
  input logic [LOG2N:0] cfg_taps,
  input logic [17:0] cfg_mu,
  input logic [33:0] cfg_eps,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im, s_dre, s_dim,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_pre, m_pim, m_ere, m_eim,
  input logic m_ready,
  output logic w_valid, w_last,
  output logic signed [17:0] w_re, w_im,
  input logic w_ready,
  output logic error
);
  localparam int N = 1 << LOG2N;
  localparam int NB = LOG2N > 0 ? LOG2N : 1;
  localparam int PW = 53 + LOG2N;              // prediction sum
  localparam int EW = ENERGY_WIDTH;
  // Each complex signed18 sample can contribute +2^35, including both MIN rails.
  // N*2^35 plus any unsigned34 EPS fits unsigned(36+LOG2N), not 39 at N=16.
  initial if(ENERGY_WIDTH<36+LOG2N || ENERGY_WIDTH>63)
    $fatal(1,"[PARAMETER] LMS ENERGY_WIDTH must be in %0d..63",36+LOG2N);
  // Configuration contract: 1 <= MU <= 2^17, reciprocal ROM 513..1024, so k <= 2^27 and
  // |k e| <= 2^44; NLMS shift = s - 9 <= 27 + LOG2N (P < 2^(36+LOG2N)), LMS shift = 12.
  function automatic int step_min(input int log2n);
    longint high;
    int width;
    high = (longint'(1) <<< 44) + (longint'(1) <<< (26 + log2n));
    width = 1;
    while (high >= (longint'(1) <<< (width - 1))) width++;
    return width;
  endfunction
  localparam int STEP_MIN = step_min(LOG2N);
  initial if(PRED_WIDTH<53+LOG2N || ERROR_WIDTH<19 || STEP_WIDTH<STEP_MIN || COEFF_WIDTH<45 || DELTA_WIDTH<63
      || WEIGHT_WIDTH<58 || DUMP_WIDTH<35 || PRED_WIDTH>128 || ERROR_WIDTH>128 || STEP_WIDTH>128
      || COEFF_WIDTH>128 || DELTA_WIDTH>128 || WEIGHT_WIDTH>128 || DUMP_WIDTH>128)
    $fatal(1,"[PARAMETER] LMS widths require PRED>=%0d ERROR>=19 STEP>=%0d COEFF>=45 DELTA>=63 WEIGHT>=58 DUMP>=35, all <=128",
      53+LOG2N,STEP_MIN);
  wire reset_now = rst == RESET_ACTIVE;
  function automatic logic signed [17:0] sat18(input logic signed [127:0] value);
    if (value > 128'sd131071) return 18'sd131071;
    if (value < -128'sd131072) return 18'sh20000;
    return value[17:0];
  endfunction
  function automatic logic signed [33:0] sat34(input logic signed [127:0] value);
    if (value > 128'sd8589934591) return 34'sd8589934591;
    if (value < -128'sd8589934592) return 34'sh200000000;
    return value[33:0];
  endfunction

  logic nlms;
  logic [LOG2N:0] taps;
  logic [17:0] mu;
  logic [33:0] eps;
  typedef enum logic [3:0] {IDLE, PRODUCT, SUM, ERROR, STEP, COEFF, TAP, WEIGHT, DUMP} state_t;
  state_t state;
  logic transaction_active;
  logic signed [17:0] h_re [0:N-1], h_im [0:N-1];
  logic signed [33:0] wr [0:N-1], wi [0:N-1];
  logic signed [17:0] d_re, d_im, e_re, e_im;
  logic sample_last;
  logic [EW-1:0] power;                       // |h|^2 over the T taps, exact
  logic signed [52:0] pr_re [0:N-1], pr_im [0:N-1];
  logic signed [PW-1:0] sum_re, sum_im, tree_re, tree_im;
  logic signed [17:0] pred_re, pred_im;
  logic [5:0] s;
  logic [27:0] k;
  logic [6:0] shift;
  logic signed [COEFF_WIDTH-1:0] c_re, c_im;
  logic signed [DELTA_WIDTH-1:0] dl_re [0:N-1], dl_im [0:N-1];
  logic [LOG2N:0] dump;
  wire [8:0] mantissa;                         // the top 10 bits of P minus 512 (bit 9 is always 1)
  wire [10:0] r_q;
  // More taps than lanes (impossible for LOG2N = 0: the field is one bit).
  wire too_many;
  generate
    if (LOG2N == 0) begin : g_one
      assign too_many = 1'b0;
    end else begin : g_many
      assign too_many = cfg_taps > (LOG2N+1)'(N);
    end
  endgenerate
  assign cfg_ready = !reset_now && !transaction_active && state == IDLE && !m_valid && !w_valid;
  wire cfg_take = cfg_valid && cfg_ready;
  assign s_ready = !reset_now && configured && state == IDLE && !m_valid && !cfg_take;
  wire take = s_valid && s_ready;
  // The sample leaving the T-tap window (zero for T = 0 handled by the configuration check).
  wire signed [17:0] old_re = h_re[NB'(taps - 1'b1)], old_im = h_im[NB'(taps - 1'b1)];
  wire [EW-1:0] p_total = EW'(eps) + power;
  logic [5:0] p_bits;
  always_comb begin
    p_bits = '0;
    for (int b = 0; b < EW; b++) if (p_total[b]) p_bits = 6'(b + 1);
  end
  assign mantissa = 9'(p_total >> (p_bits - 6'd10));
  always_comb begin
    tree_re = '0; tree_im = '0;
    for (int n = 0; n < N; n++) begin tree_re = tree_re + PW'(pr_re[n]); tree_im = tree_im + PW'(pr_im[n]); end
  end
  // Explicitly sized expressions; every narrowing is at a proven range.
  // pr: conj(w) h of signed34 x signed18 needs exactly 53 bits; the tree N*2^51 needs 53+LOG2N.
  wire signed [52:0] product_re [0:N-1], product_im [0:N-1];
  wire signed [PRED_WIDTH-1:0] pred_raw_re = PRED_WIDTH'(sum_re) + (PRED_WIDTH'(1) <<< 29);
  wire signed [PRED_WIDTH-1:0] pred_raw_im = PRED_WIDTH'(sum_im) + (PRED_WIDTH'(1) <<< 29);
  wire signed [PRED_WIDTH-1:0] pred_round_re = pred_raw_re >>> 30, pred_round_im = pred_raw_im >>> 30;
  assign pred_re = sat18(128'(pred_round_re));
  assign pred_im = sat18(128'(pred_round_im));
  wire signed [ERROR_WIDTH-1:0] error_raw_re = ERROR_WIDTH'(d_re) - ERROR_WIDTH'(pred_re);
  wire signed [ERROR_WIDTH-1:0] error_raw_im = ERROR_WIDTH'(d_im) - ERROR_WIDTH'(pred_im);
  // c = rnd(k conj(e), shift) in Q20; the round add 2^(shift-1) is part of the sized sum.
  wire signed [STEP_WIDTH-1:0] step_raw_re = STEP_WIDTH'($signed({1'b0, k})) * STEP_WIDTH'(e_re);
  wire signed [STEP_WIDTH-1:0] step_raw_im = -(STEP_WIDTH'($signed({1'b0, k})) * STEP_WIDTH'(e_im));
  wire signed [STEP_WIDTH-1:0] step_add = STEP_WIDTH'(1) <<< (shift - 7'd1);
  wire signed [STEP_WIDTH-1:0] step_sum_re = step_raw_re + step_add, step_sum_im = step_raw_im + step_add;
  // |c| <= 2^43 for every shift >= 1: the arithmetic shift is narrowed to the c registers.
  wire signed [COEFF_WIDTH-1:0] step_round_re = COEFF_WIDTH'(step_sum_re >>> shift);
  wire signed [COEFF_WIDTH-1:0] step_round_im = COEFF_WIDTH'(step_sum_im >>> shift);
  wire signed [DELTA_WIDTH-1:0] tap_re [0:N-1], tap_im [0:N-1];
  wire signed [DELTA_WIDTH-1:0] delta_round_re [0:N-1], delta_round_im [0:N-1];
  wire signed [WEIGHT_WIDTH-1:0] weight_next_re [0:N-1], weight_next_im [0:N-1];
  genvar lane;
  generate for (lane = 0; lane < N; lane++) begin : g_lanes
    assign product_re[lane] = 53'(wr[lane])*53'(h_re[lane]) + 53'(wi[lane])*53'(h_im[lane]);
    assign product_im[lane] = 53'(wr[lane])*53'(h_im[lane]) - 53'(wi[lane])*53'(h_re[lane]);
    assign tap_re[lane] = DELTA_WIDTH'(h_re[lane])*DELTA_WIDTH'(c_re) - DELTA_WIDTH'(h_im[lane])*DELTA_WIDTH'(c_im);
    assign tap_im[lane] = DELTA_WIDTH'(h_re[lane])*DELTA_WIDTH'(c_im) + DELTA_WIDTH'(h_im[lane])*DELTA_WIDTH'(c_re);
    assign delta_round_re[lane] = (dl_re[lane] + (DELTA_WIDTH'(1) <<< 4)) >>> 5;
    assign delta_round_im[lane] = (dl_im[lane] + (DELTA_WIDTH'(1) <<< 4)) >>> 5;
    assign weight_next_re[lane] = WEIGHT_WIDTH'(wr[lane]) + WEIGHT_WIDTH'(delta_round_re[lane]);
    assign weight_next_im[lane] = WEIGHT_WIDTH'(wi[lane]) + WEIGHT_WIDTH'(delta_round_im[lane]);
  end endgenerate
  wire signed [33:0] dump_re = wr[NB'(dump)], dump_im = wi[NB'(dump)];
  wire signed [DUMP_WIDTH-1:0] dump_raw_re = DUMP_WIDTH'(dump_re) + (DUMP_WIDTH'(1) <<< 14);
  wire signed [DUMP_WIDTH-1:0] dump_raw_im = DUMP_WIDTH'(dump_im) + (DUMP_WIDTH'(1) <<< 14);
  wire signed [DUMP_WIDTH-1:0] dump_round_re = dump_raw_re >>> 15, dump_round_im = dump_raw_im >>> 15;
  sync_rom #(.WIDTH(11),.ADDR_WIDTH(9),.INIT_FILE(RECIP_FILE)) reciprocal(
    .clk(clk),.rd_en(state == ERROR),.rd_addr(mantissa),.rd_data(r_q));
  always_ff @(posedge clk) begin
    if (reset_now) begin
      configured <= 0; error <= 0; state <= IDLE; m_valid <= 0; w_valid <= 0; power <= '0;
      transaction_active <= 0;
      for (int n = 0; n < N; n++) begin h_re[n] <= '0; h_im[n] <= '0; wr[n] <= '0; wi[n] <= '0; end
    end else begin
      if (m_valid && m_ready) m_valid <= 0;
      if (cfg_take) begin
        nlms <= cfg_nlms; taps <= cfg_taps; mu <= cfg_mu; eps <= cfg_eps;
        if (cfg_taps == '0 || too_many || cfg_mu == '0 || cfg_mu > 18'd131072 || cfg_nlms && cfg_eps < 34'd512) begin
          configured <= 0; error <= 1;
        end else configured <= 1;
      end
      case (state)
        IDLE: if (take) begin
          transaction_active <= 1;
          for (int n = N - 1; n > 0; n--) begin h_re[n] <= h_re[n-1]; h_im[n] <= h_im[n-1]; end
          h_re[0] <= s_re; h_im[0] <= s_im; d_re <= s_dre; d_im <= s_dim; sample_last <= s_last;
          power <= power + EW'(37'(s_re*s_re) + 37'(s_im*s_im)) - EW'(37'(old_re*old_re) + 37'(old_im*old_im));
          state <= PRODUCT;
        end
        PRODUCT: begin
          // conj(w) h for the active taps.
          for (int n = 0; n < N; n++)
            if ((LOG2N+1)'(n) < taps) begin
              pr_re[n] <= product_re[n];
              pr_im[n] <= product_im[n];
            end else begin pr_re[n] <= '0; pr_im[n] <= '0; end
          state <= SUM;
        end
        SUM: begin sum_re <= tree_re; sum_im <= tree_im; state <= ERROR; end
        ERROR: begin
          m_valid <= 1; m_last <= sample_last;
          m_pre <= pred_re; m_pim <= pred_im;
          e_re <= sat18(128'(error_raw_re)); e_im <= sat18(128'(error_raw_im));
          m_ere <= sat18(128'(error_raw_re)); m_eim <= sat18(128'(error_raw_im));
          s <= p_bits;
          state <= STEP;
        end
        STEP: begin
          k <= nlms ? 28'(mu)*28'(r_q) : 28'(mu);
          shift <= nlms ? 7'(s) - 7'd9 : 7'd12;
          state <= COEFF;
        end
        COEFF: begin
          // c = mu conj(e) in Q20.
          c_re <= step_round_re;
          c_im <= step_round_im;
          state <= TAP;
        end
        TAP: begin
          for (int n = 0; n < N; n++) begin
            dl_re[n] <= tap_re[n];
            dl_im[n] <= tap_im[n];
          end
          state <= WEIGHT;
        end
        WEIGHT: begin
          for (int n = 0; n < N; n++) if ((LOG2N+1)'(n) < taps) begin
            wr[n] <= sat34(128'(weight_next_re[n])); wi[n] <= sat34(128'(weight_next_im[n]));
          end
          if (sample_last) begin state <= DUMP; dump <= '0; end else state <= IDLE;
        end
        DUMP: if (!w_valid || w_ready) begin
          if (dump == taps) begin
            // All weights are out: clear the filter for the next transaction.
            w_valid <= 0; state <= IDLE; power <= '0;
            transaction_active <= 0;
            for (int n = 0; n < N; n++) begin h_re[n] <= '0; h_im[n] <= '0; wr[n] <= '0; wi[n] <= '0; end
          end else begin
            w_valid <= 1; w_re <= sat18(128'(dump_round_re)); w_im <= sat18(128'(dump_round_im));
            w_last <= dump == taps - 1'b1; dump <= dump + 1'b1;
          end
        end
        default: state <= IDLE;
      endcase
      if (state != DUMP && w_valid && w_ready) w_valid <= 0;
    end
  end
endmodule
