// RLS adaptive filter (research_core rls; bit-exact reference rls_fixed.adapt).
// Configuration (one transfer, between transactions): taps T <= 2^LOG2N, P0 = round(2^28/eps),
// LAM = round(lambda*2^28), INVL = round(2^30/lambda) (rls_fixed.parameters). A transaction is
// one signal of (x, d) Q15 pairs (s_last on the last); it restarts from P = P0 I, w = 0.
// Per sample (Q28 P, 44 bit; Q30 w, 34 bit; widths and saturations as rls_fixed):
//   pred = sat18(rnd(conj(w) h, 30)), e = sat18(d - pred) (one m_* output);
//   u = sat48(rnd(P h, 15)) row by row; q = sat50(rnd(re(h^H u), 15)); D = LAM + q (> 0);
//   one normalised reciprocal of D (norm_reciprocal, Z = 22 + bit length); g = sat40(rnd(u R, Z - 30));
//   w = sat34(w + rnd(g conj(e), 15));
//   P_ij = sat44(rnd((P_ij - sat46(rnd(g_i conj(u_j), 30)))*INVL, 30)) for i <= j, P_ji = conj(P_ij),
//   real diagonal (keeps the fixed-point P Hermitian).
// The rows are processed one per two clocks, so a sample takes about 4T + D-width + 35 clocks
// (the reciprocal dominates). After the transaction the T weights come on w_* as
// sat18(rnd(w, 15)) (w_last on the last).
// Pending configuration is held until that final weight drains. At an idle boundary
// a cfg transfer takes priority over a simultaneously offered first data sample.
// error is sticky: T = 0 or T > 2^LOG2N, LAM = 0, or a non-positive D (P lost positivity).
module rls_filter #(
  parameter int LOG2N = 2,
  parameter bit RESET_ACTIVE = 1,
  parameter int PRED_WIDTH = 53 + LOG2N,
  parameter int DOT_WIDTH = 63 + LOG2N,
  parameter int Q_WIDTH = 67 + LOG2N,
  parameter int GAIN_WIDTH = 71,
  parameter int UPDATE_WIDTH = 59,
  parameter int WEIGHT_WIDTH = 44,
  parameter int PT_WIDTH = 89,
  parameter int COV_WIDTH = 79
)(
  input logic clk, rst,
  input logic cfg_valid,
  input logic [LOG2N:0] cfg_taps,
  input logic [43:0] cfg_p0,
  input logic [29:0] cfg_lambda,
  input logic [31:0] cfg_invl,
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
  // Full signed34/44/48 states times signed18 history; two products per lane.
  // Keep the shared prediction/matrix datapath, sized for its signed44 matrix operand.
  initial if(PRED_WIDTH<53+LOG2N || DOT_WIDTH<63+LOG2N || Q_WIDTH<67+LOG2N
      || PRED_WIDTH>128 || DOT_WIDTH>128 || Q_WIDTH>128)
    $fatal(1,"[PARAMETER] RLS widths require PRED>=%0d DOT>=%0d Q>=%0d, all <=128",53+LOG2N,63+LOG2N,67+LOG2N);
  initial if(GAIN_WIDTH<71 || UPDATE_WIDTH<59 || WEIGHT_WIDTH<44 || PT_WIDTH<89 || COV_WIDTH<79
      || GAIN_WIDTH>128 || UPDATE_WIDTH>128 || WEIGHT_WIDTH>128 || PT_WIDTH>128 || COV_WIDTH>128)
    $fatal(1,"[PARAMETER] RLS update widths require GAIN>=71 UPDATE>=59 WEIGHT>=44 PT>=89 COV>=79, all <=128");
  wire reset_now = rst == RESET_ACTIVE;
  // Round half up by s, then saturate to `bits` (two's complement), on 128-bit values.
  function automatic logic signed [127:0] rs(input logic signed [127:0] v, input int s, input int bits);
    logic signed [127:0] r, hi, lo;
    r = s == 0 ? v : (v + (128'sd1 <<< (s - 1))) >>> s;
    hi = (128'sd1 <<< (bits - 1)) - 1; lo = -(128'sd1 <<< (bits - 1));
    return r > hi ? hi : r < lo ? lo : r;
  endfunction
  function automatic logic signed [127:0] rv(input logic signed [127:0] v, input logic [6:0] s);
    return (v + (128'sd1 <<< (s - 1'b1))) >>> s;
  endfunction

  logic [LOG2N:0] taps;
  logic [43:0] p0;
  logic [29:0] lam;
  logic [31:0] invl;
  typedef enum logic [3:0] {IDLE, PRODUCT, SUM, ERROR, U, Q, RECIP, GAIN, WEIGHT, PT, PN, DUMP} state_t;
  state_t state;
  logic transaction_active;
  logic signed [17:0] h_re [0:N-1], h_im [0:N-1];
  logic signed [33:0] wr [0:N-1], wi [0:N-1];
  logic signed [43:0] pr [0:N-1][0:N-1], pi [0:N-1][0:N-1];
  logic signed [47:0] ur [0:N-1], ui [0:N-1];
  logic signed [39:0] gr [0:N-1], gi [0:N-1];
  logic signed [45:0] tr [0:N-1], ti [0:N-1];
  logic signed [17:0] d_re, d_im, e_re, e_im;
  logic signed [PRED_WIDTH-1:0] sum_re, sum_im;
  logic sample_last;
  logic [NB-1:0] row;
  logic [LOG2N:0] dump;
  logic signed [50:0] dden;
  logic norm_start, norm_done, norm_zero;
  logic [23:0] r;
  logic [6:0] shift;
  norm_reciprocal #(.WIDTH(51),.RESET_ACTIVE(RESET_ACTIVE)) norm(
    .clk(clk),.rst(rst),.start(norm_start),.energy(51'(dden)),.done(norm_done),.zero(norm_zero),.r(r),.shift(shift));
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
  wire active [0:N-1];
  genvar a;
  generate for (a = 0; a < N; a = a + 1) begin : g_active assign active[a] = (LOG2N+1)'(a) < taps; end endgenerate
  // Combinational sums of the current step.
  logic signed [DOT_WIDTH-1:0] acc_re, acc_im;
  logic signed [Q_WIDTH-1:0] q_sum;
  always_comb begin
    acc_re = '0; acc_im = '0; q_sum = '0;
    for (int j = 0; j < N; j++) if (active[j]) begin
      // pred: conj(w) h; U: P[row] h; Q: re(conj(h) u)
      if (state == PRODUCT) begin
        acc_re = acc_re + DOT_WIDTH'(wr[j])*DOT_WIDTH'(h_re[j]) + DOT_WIDTH'(wi[j])*DOT_WIDTH'(h_im[j]);
        acc_im = acc_im + DOT_WIDTH'(wr[j])*DOT_WIDTH'(h_im[j]) - DOT_WIDTH'(wi[j])*DOT_WIDTH'(h_re[j]);
      end else begin
        acc_re = acc_re + DOT_WIDTH'(pr[row][j])*DOT_WIDTH'(h_re[j]) - DOT_WIDTH'(pi[row][j])*DOT_WIDTH'(h_im[j]);
        acc_im = acc_im + DOT_WIDTH'(pr[row][j])*DOT_WIDTH'(h_im[j]) + DOT_WIDTH'(pi[row][j])*DOT_WIDTH'(h_re[j]);
      end
      q_sum = q_sum + Q_WIDTH'(h_re[j])*Q_WIDTH'(ur[j]) + Q_WIDTH'(h_im[j])*Q_WIDTH'(ui[j]);
    end
  end
  wire signed [17:0] pred_re = 18'(rs(128'(sum_re), 30, 18)), pred_im = 18'(rs(128'(sum_im), 30, 18));

  // Raw expressions retain the full state ranges. Narrow only at proven boundaries;
  // variable gain rounding stays 128-bit to preserve the existing 7-bit shift behavior.
  wire signed [GAIN_WIDTH-1:0] gain_raw_re[0:N-1],gain_raw_im[0:N-1];
  wire signed [UPDATE_WIDTH-1:0] update_raw_re[0:N-1],update_raw_im[0:N-1],update_round_re[0:N-1],update_round_im[0:N-1];
  wire signed [WEIGHT_WIDTH-1:0] weight_next_re[0:N-1],weight_next_im[0:N-1];
  wire signed [PT_WIDTH-1:0] pt_raw_re[0:N-1],pt_raw_im[0:N-1],pt_round_re[0:N-1],pt_round_im[0:N-1];
  wire signed [46:0] cov_delta_re[0:N-1],cov_delta_im[0:N-1];
  wire signed [COV_WIDTH-1:0] cov_raw_re[0:N-1],cov_raw_im[0:N-1],cov_round_re[0:N-1],cov_round_im[0:N-1];
  genvar k;
  generate for(k=0;k<N;k++)begin:g_updates
    assign gain_raw_re[k]=GAIN_WIDTH'(ur[k])*GAIN_WIDTH'($signed({1'b0,r}));
    assign gain_raw_im[k]=GAIN_WIDTH'(ui[k])*GAIN_WIDTH'($signed({1'b0,r}));
    assign update_raw_re[k]=UPDATE_WIDTH'(gr[k])*UPDATE_WIDTH'(e_re)+UPDATE_WIDTH'(gi[k])*UPDATE_WIDTH'(e_im);
    assign update_raw_im[k]=UPDATE_WIDTH'(gi[k])*UPDATE_WIDTH'(e_re)-UPDATE_WIDTH'(gr[k])*UPDATE_WIDTH'(e_im);
    assign update_round_re[k]=(update_raw_re[k]+(UPDATE_WIDTH'(1)<<<14))>>>15;
    assign update_round_im[k]=(update_raw_im[k]+(UPDATE_WIDTH'(1)<<<14))>>>15;
    assign weight_next_re[k]=WEIGHT_WIDTH'(wr[k])+WEIGHT_WIDTH'(update_round_re[k]);
    assign weight_next_im[k]=WEIGHT_WIDTH'(wi[k])+WEIGHT_WIDTH'(update_round_im[k]);
    assign pt_raw_re[k]=PT_WIDTH'(gr[row])*PT_WIDTH'(ur[k])+PT_WIDTH'(gi[row])*PT_WIDTH'(ui[k]);
    assign pt_raw_im[k]=PT_WIDTH'(gi[row])*PT_WIDTH'(ur[k])-PT_WIDTH'(gr[row])*PT_WIDTH'(ui[k]);
    assign pt_round_re[k]=(pt_raw_re[k]+(PT_WIDTH'(1)<<<29))>>>30;
    assign pt_round_im[k]=(pt_raw_im[k]+(PT_WIDTH'(1)<<<29))>>>30;
    assign cov_delta_re[k]=47'(pr[row][k])-47'(tr[k]);
    assign cov_delta_im[k]=47'(pi[row][k])-47'(ti[k]);
    assign cov_raw_re[k]=COV_WIDTH'(cov_delta_re[k])*COV_WIDTH'($signed({1'b0,invl}));
    assign cov_raw_im[k]=COV_WIDTH'(cov_delta_im[k])*COV_WIDTH'($signed({1'b0,invl}));
    assign cov_round_re[k]=(cov_raw_re[k]+(COV_WIDTH'(1)<<<29))>>>30;
    assign cov_round_im[k]=(cov_raw_im[k]+(COV_WIDTH'(1)<<<29))>>>30;
  end endgenerate

  always_ff @(posedge clk) begin
    if (reset_now) begin
      configured <= 0; error <= 0; state <= IDLE; m_valid <= 0; w_valid <= 0; norm_start <= 0;
      transaction_active <= 0;
    end else begin
      norm_start <= 0;
      if (m_valid && m_ready) m_valid <= 0;
      if (cfg_take) begin
        taps <= cfg_taps; p0 <= cfg_p0; lam <= cfg_lambda; invl <= cfg_invl;
        if (cfg_taps == '0 || too_many || cfg_lambda == '0) begin configured <= 0; error <= 1; end
        else configured <= 1;
        for (int i = 0; i < N; i++) begin
          h_re[i] <= '0; h_im[i] <= '0; wr[i] <= '0; wi[i] <= '0;
          for (int j = 0; j < N; j++) begin pr[i][j] <= i == j ? $signed(cfg_p0) : '0; pi[i][j] <= '0; end
        end
      end
      case (state)
        IDLE: if (take) begin
          transaction_active <= 1;
          for (int n = N - 1; n > 0; n--) begin h_re[n] <= h_re[n-1]; h_im[n] <= h_im[n-1]; end
          h_re[0] <= s_re; h_im[0] <= s_im; d_re <= s_dre; d_im <= s_dim; sample_last <= s_last;
          state <= PRODUCT;
        end
        PRODUCT: begin sum_re <= PRED_WIDTH'(acc_re); sum_im <= PRED_WIDTH'(acc_im); state <= ERROR; end
        ERROR: begin
          m_valid <= 1; m_last <= sample_last; m_pre <= pred_re; m_pim <= pred_im;
          e_re <= 18'(rs(128'(d_re) - 128'(pred_re), 0, 18)); e_im <= 18'(rs(128'(d_im) - 128'(pred_im), 0, 18));
          m_ere <= 18'(rs(128'(d_re) - 128'(pred_re), 0, 18)); m_eim <= 18'(rs(128'(d_im) - 128'(pred_im), 0, 18));
          row <= '0; state <= U;
        end
        // u, one row per clock.
        U: begin
          ur[row] <= 48'(rs(128'(acc_re), 15, 48)); ui[row] <= 48'(rs(128'(acc_im), 15, 48));
          if (32'(row) == 32'(taps) - 1) state <= Q; else row <= row + 1'b1;
        end
        Q: begin
          dden <= 51'(lam) + 51'(rs(128'(q_sum), 15, 50));
          norm_start <= 1; state <= RECIP;
        end
        RECIP: if (norm_start) begin end
          else if (dden <= 0 || norm_zero) begin error <= 1; state <= GAIN; end
          else if (norm_done) state <= GAIN;
        GAIN: begin
          // shift = Z - 15, so Z - 30 = shift - 15.
          for (int i = 0; i < N; i++) begin
            gr[i] <= 40'(rs(rv(128'(gain_raw_re[i]), shift - 7'd15), 0, 40));
            gi[i] <= 40'(rs(rv(128'(gain_raw_im[i]), shift - 7'd15), 0, 40));
          end
          state <= WEIGHT;
        end
        WEIGHT: begin
          // w += g conj(e)
          for (int i = 0; i < N; i++) if (active[i]) begin
            wr[i] <= 34'(rs(128'(weight_next_re[i]), 0, 34));
            wi[i] <= 34'(rs(128'(weight_next_im[i]), 0, 34));
          end
          row <= '0; state <= PT;
        end
        // P row by row: t = g_row conj(u_j), then the scaled update for j >= row, mirrored.
        PT: begin
          for (int j = 0; j < N; j++) begin
            tr[j] <= 46'(rs(128'(pt_round_re[j]), 0, 46));
            ti[j] <= 46'(rs(128'(pt_round_im[j]), 0, 46));
          end
          state <= PN;
        end
        PN: begin
          for (int j = 0; j < N; j++) if (active[j] && j >= 32'(row)) begin
            pr[row][j] <= 44'(rs(128'(cov_round_re[j]), 0, 44));
            pr[j][row] <= 44'(rs(128'(cov_round_re[j]), 0, 44));
            if (j == 32'(row)) begin pi[row][j] <= '0; end
            else begin
              pi[row][j] <= 44'(rs(128'(cov_round_im[j]), 0, 44));
              pi[j][row] <= 44'(128'sd0 - rs(128'(cov_round_im[j]), 0, 44));
            end
          end
          if (32'(row) == 32'(taps) - 1) begin
            if (sample_last) begin state <= DUMP; dump <= '0; end else state <= IDLE;
          end else begin row <= row + 1'b1; state <= PT; end
        end
        DUMP: if (!w_valid || w_ready) begin
          if (dump == taps) begin
            w_valid <= 0; state <= IDLE;
            transaction_active <= 0;
            for (int i = 0; i < N; i++) begin
              h_re[i] <= '0; h_im[i] <= '0; wr[i] <= '0; wi[i] <= '0;
              for (int j = 0; j < N; j++) begin pr[i][j] <= i == j ? $signed(p0) : '0; pi[i][j] <= '0; end
            end
          end else begin
            w_valid <= 1; w_re <= 18'(rs(128'(wr[NB'(dump)]), 15, 18)); w_im <= 18'(rs(128'(wi[NB'(dump)]), 15, 18));
            w_last <= dump == taps - 1'b1; dump <= dump + 1'b1;
          end
        end
        default: state <= IDLE;
      endcase
      if (state != DUMP && w_valid && w_ready) w_valid <= 0;
    end
  end
endmodule
