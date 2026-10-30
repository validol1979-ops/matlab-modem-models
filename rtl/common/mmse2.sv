// 2x2 MMSE / zero-forcing solver (research_core mimo for n = 2; bit-exact reference
// mmse_fixed.solve): y = (H^H H + lambda I)^-1 H^H obs for every observation pair.
// Configuration (between transactions): h00, h01, h10, h11 (Q15, row-major, cfg_last on h11
// with LAMBDA = round(lambda*2^30)). The weights are then computed in hardware, exactly:
// G = H^H H + LAMBDA I (Q30), det = a d - |b|^2 (Q60), one normalised reciprocal of det
// (norm_reciprocal: Z = 22 + bit length, R = divide(2^Z, det)), M = adj(G) H^H (Q45) and
// W = rnd(M*R, Z - 39) (Q24); `configured` rises about 110 clocks after cfg_last. A singular
// normal matrix (det <= 0) or a rounded coefficient outside signed WW bits sets
// error instead; an unrepresentable coefficient never configures the datapath.
// A transaction is observation pairs (o0, o1) (s_last on the last o1); per pair
// y_i = sat18(rnd(W_i0 o_0 + W_i1 o_1, 24)) (Q15), y0 then y1 (m_last on the very last).
// One sample per clock; the pipeline never stalls and pushes both outputs of a pair into an
// 8-entry FIFO (m_ready backpressure, the pairs in flight are counted).
// Configuration is accepted only after the input TLAST and complete output drain.
// At that idle boundary configuration takes priority over a concurrent data offer.
// TLAST on o0 rejects the partial pair, clears configured and latches error until reset;
// completed pairs already in flight may drain, but the malformed pair emits no output.
// A missing cfg_last at h11 permits no additional matrix entries: the next word
// raises error, with the configuration count saturated at four until reset.
// Expression widths (docs/RTL_MMSE2_WIDTHS.md) are parameters; stored registers keep their
// sizes (Gram 39, det 76 for norm_reciprocal, M 58, W 48), so precision and timing are unchanged.
// The former layout 39/76/58/84/68 remains a valid parameter set.
module mmse2 #(
  parameter bit RESET_ACTIVE = 1,
  parameter int GRAM_WIDTH = 38,                // |h|^2 sums + LAMBDA <= 2^36 + 2^34 - 1, |b| <= 2^36
  parameter int DET_WIDTH = 74,                 // a d - |b|^2 in [-(2^72 + (2^36-2^18)^2), (2^36+2^34-1)^2]
  parameter int M_WIDTH = 55,                   // |M| <= (2^36 + 2^34 - 1) 2^17.5 < 2^54 (exact mod 2^W)
  parameter int SCALE_WIDTH = 78,               // |M R| + 2^55 < 2^77; left shifts stay below 2^57
  parameter int SUM_WIDTH = 68                  // four signed48 x signed18 products reach 2^66 (+2^23)
)(
  input logic clk, rst,
  input logic cfg_valid, cfg_last,
  input logic signed [17:0] cfg_re, cfg_im,
  input logic [33:0] cfg_lambda,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  localparam int GW = 39;                       // Gram registers
  localparam int DW = 76;                       // det register and norm_reciprocal width
  localparam int MW = 58;                       // M registers
  localparam int WW = 48;                       // weights (Q24)
  localparam int SW = SCALE_WIDTH;
  localparam int YW = SUM_WIDTH;
  initial if (GRAM_WIDTH < 38 || GRAM_WIDTH > 64 || DET_WIDTH < 74 || DET_WIDTH > 128 || M_WIDTH < 55 || M_WIDTH > 128
              || SCALE_WIDTH < 78 || SCALE_WIDTH > 128 || SUM_WIDTH < 68 || SUM_WIDTH > 128)
    $fatal(1, "[PARAMETER] MMSE2 widths require GRAM=38..64, DET=74..128, M=55..128, SCALE=78..128, SUM=68..128");
  localparam logic signed [SW-1:0] WMAX = (SW'(1) <<< (WW-1)) - SW'(1);
  localparam logic signed [SW-1:0] WMIN = -(SW'(1) <<< (WW-1));
  wire reset_now = rst == RESET_ACTIVE;
  function automatic logic signed [17:0] sat18(input logic signed [YW-1:0] value);
    logic signed [YW-1:0] rounded;
    rounded = (value + (YW'(1) <<< 23)) >>> 24;
    if (rounded > YW'(131071)) return 18'sd131071;
    if (rounded < -(YW'(131072))) return 18'sh20000;
    return rounded[17:0];
  endfunction

  // Configuration.
  logic signed [17:0] hr [0:3], hi [0:3];       // h00, h01, h10, h11
  logic [33:0] lambda;
  logic [2:0] count;
  typedef enum logic [2:0] {C_IDLE, C_GRAM, C_DET, C_RECIP, C_ADJ, C_WEIGHT} cstate_t;
  cstate_t cstate;
  logic signed [GW-1:0] ga, gd, gbr, gbi;
  logic signed [DW-1:0] det;
  logic norm_start, norm_done, norm_zero;
  logic [23:0] r;
  logic [6:0] shift;
  norm_reciprocal #(.WIDTH(DW),.RESET_ACTIVE(RESET_ACTIVE)) norm(
    .clk(clk),.rst(rst),.start(norm_start),.energy(DW'(det)),.done(norm_done),.zero(norm_zero),.r(r),.shift(shift));
  logic signed [MW-1:0] mr [0:3], mi [0:3];     // M00, M01, M10, M11
  logic signed [WW-1:0] wr [0:3], wi [0:3];
  // Data.
  logic second, frame_active;
  logic signed [17:0] or0, oi0;
  logic [3:0] fifo_count, pending;
  logic [36:0] fifo [0:7];
  logic [2:0] fifo_head, fifo_tail;
  assign cfg_ready = !reset_now && !error && cstate == C_IDLE && !frame_active
                     && pending == '0 && fifo_count == '0 && !second;
  wire cfg_take = cfg_valid && cfg_ready;
  assign s_ready = !reset_now && !error && configured && !cfg_take
                   && {1'b0, fifo_count} + {pending, 1'b0} < 5'd7;
  wire take = s_valid && s_ready;
  wire pop = m_valid && m_ready;
  logic p_valid, p_last, e_valid, e_last;
  logic signed [YW-1:0] y0r, y0i, y1r, y1i;
  logic signed [17:0] e0r, e0i, e1r, e1i;
  // conj(x) y and x y for the Gram and adjugate products.
  function automatic logic signed [GRAM_WIDTH-1:0] cjr(input logic signed [17:0] ar, ai, br, bi);
    return GRAM_WIDTH'(ar)*GRAM_WIDTH'(br) + GRAM_WIDTH'(ai)*GRAM_WIDTH'(bi);
  endfunction
  function automatic logic signed [GRAM_WIDTH-1:0] cji(input logic signed [17:0] ar, ai, br, bi);
    return GRAM_WIDTH'(ar)*GRAM_WIDTH'(bi) - GRAM_WIDTH'(ai)*GRAM_WIDTH'(br);
  endfunction
  wire signed [GRAM_WIDTH-1:0] lambda_s = GRAM_WIDTH'($signed({1'b0, lambda}));
  // Each sized expression is a function returning its own width: a size cast or a wider
  // destination would otherwise widen the operands (context-determined evaluation).
  function automatic logic signed [GRAM_WIDTH-1:0] gsum(input logic signed [GRAM_WIDTH-1:0] x, y, z);
    return x + y + z;
  endfunction
  function automatic logic signed [DET_WIDTH-1:0] det_value(input logic signed [GW-1:0] a, d, b_r, b_i);
    return DET_WIDTH'(a)*DET_WIDTH'(d) - DET_WIDTH'(b_r)*DET_WIDTH'(b_r) - DET_WIDTH'(b_i)*DET_WIDTH'(b_i);
  endfunction
  // M_ij = adj_i0 conj(h_j0) + adj_i1 conj(h_j1); adj = [[d, -b], [-conj b, a]].
  // Only +, - and * form M: the result is exact modulo 2^M_WIDTH, and its value is below 2^54.
  function automatic logic signed [M_WIDTH-1:0] mre_w(input logic signed [GW-1:0] p_r, p_i, q_r, q_i, input logic signed [17:0] u_r, u_i, v_r, v_i);
    // (p) conj(u) + (q) conj(v), real part
    return M_WIDTH'(p_r)*M_WIDTH'(u_r) + M_WIDTH'(p_i)*M_WIDTH'(u_i) + M_WIDTH'(q_r)*M_WIDTH'(v_r) + M_WIDTH'(q_i)*M_WIDTH'(v_i);
  endfunction
  function automatic logic signed [M_WIDTH-1:0] mim_w(input logic signed [GW-1:0] p_r, p_i, q_r, q_i, input logic signed [17:0] u_r, u_i, v_r, v_i);
    return M_WIDTH'(p_i)*M_WIDTH'(u_r) - M_WIDTH'(p_r)*M_WIDTH'(u_i) + M_WIDTH'(q_i)*M_WIDTH'(v_r) - M_WIDTH'(q_r)*M_WIDTH'(v_i);
  endfunction
  // Sign extension (or truncation of a value that fits) into the 58-bit M registers.
  function automatic logic signed [MW-1:0] mre(input logic signed [GW-1:0] p_r, p_i, q_r, q_i, input logic signed [17:0] u_r, u_i, v_r, v_i);
    return MW'(mre_w(p_r, p_i, q_r, q_i, u_r, u_i, v_r, v_i));
  endfunction
  function automatic logic signed [MW-1:0] mim(input logic signed [GW-1:0] p_r, p_i, q_r, q_i, input logic signed [17:0] u_r, u_i, v_r, v_i);
    return MW'(mim_w(p_r, p_i, q_r, q_i, u_r, u_i, v_r, v_i));
  endfunction
  function automatic logic signed [SW-1:0] wvalue(input logic signed [SW-1:0] product, input logic [6:0] s);
    int amount;
    // norm supplies s=Z-15. Small, well-conditioned channels can need Z-39 <= 0.
    // Subtract in a signed integer so s<24 cannot underflow in a 7-bit unsigned field.
    amount = int'(s) - 24;
    if (amount > 0) return (product + (SW'(1) <<< (amount - 1))) >>> amount;
    if (amount == 0) return product;
    return product <<< (-amount);
  endfunction
  // Raw M*R products and scaled weights before the signed48 check (observed by the bench).
  logic signed [SW-1:0] wprod_re [0:3], wprod_im [0:3], wfull_re [0:3], wfull_im [0:3];
  always_comb
    for (int k = 0; k < 4; k++) begin
      wprod_re[k] = SW'(mr[k])*SW'($signed({1'b0, r}));
      wprod_im[k] = SW'(mi[k])*SW'($signed({1'b0, r}));
      wfull_re[k] = wvalue(wprod_re[k], shift);
      wfull_im[k] = wvalue(wprod_im[k], shift);
    end
  assign m_valid = fifo_count != 4'd0;
  assign m_re = fifo[fifo_head][36:19]; assign m_im = fifo[fifo_head][18:1]; assign m_last = fifo[fifo_head][0];

  always_ff @(posedge clk) begin
    if (take && !second) begin or0 <= s_re; oi0 <= s_im; end
    if (take && second) begin
      // y_i = W_i0 o0 + W_i1 o1 (o1 = s)
      y0r <= YW'(wr[0])*YW'(or0) - YW'(wi[0])*YW'(oi0) + YW'(wr[1])*YW'(s_re) - YW'(wi[1])*YW'(s_im);
      y0i <= YW'(wr[0])*YW'(oi0) + YW'(wi[0])*YW'(or0) + YW'(wr[1])*YW'(s_im) + YW'(wi[1])*YW'(s_re);
      y1r <= YW'(wr[2])*YW'(or0) - YW'(wi[2])*YW'(oi0) + YW'(wr[3])*YW'(s_re) - YW'(wi[3])*YW'(s_im);
      y1i <= YW'(wr[2])*YW'(oi0) + YW'(wi[2])*YW'(or0) + YW'(wr[3])*YW'(s_im) + YW'(wi[3])*YW'(s_re);
      p_last <= s_last;
    end
    e0r <= sat18(y0r); e0i <= sat18(y0i); e1r <= sat18(y1r); e1i <= sat18(y1i); e_last <= p_last;
    if (reset_now) begin
      configured <= 0; error <= 0; count <= '0; cstate <= C_IDLE; norm_start <= 0; second <= 0; frame_active <= 0;
      p_valid <= 0; e_valid <= 0; pending <= '0; fifo_count <= '0; fifo_head <= '0; fifo_tail <= '0;
    end else begin
      norm_start <= 0;
      if (cfg_take) begin
        configured <= 0;
        if (count >= 3'd4) begin count <= 3'd4; error <= 1; end
        else begin
          count <= count + 1'b1;
          hr[count[1:0]] <= cfg_re; hi[count[1:0]] <= cfg_im;
          if (cfg_last) begin
            count <= '0; lambda <= cfg_lambda;
            if (count == 3'd3) cstate <= C_GRAM; else error <= 1;
          end
        end
      end
      case (cstate)
        C_IDLE: begin end
        C_GRAM: begin
          // a = |h00|^2 + |h10|^2 + L, d = |h01|^2 + |h11|^2 + L, b = conj(h00) h01 + conj(h10) h11.
          ga <= GW'(gsum(cjr(hr[0], hi[0], hr[0], hi[0]), cjr(hr[2], hi[2], hr[2], hi[2]), lambda_s));
          gd <= GW'(gsum(cjr(hr[1], hi[1], hr[1], hi[1]), cjr(hr[3], hi[3], hr[3], hi[3]), lambda_s));
          gbr <= GW'(gsum(cjr(hr[0], hi[0], hr[1], hi[1]), cjr(hr[2], hi[2], hr[3], hi[3]), '0));
          gbi <= GW'(gsum(cji(hr[0], hi[0], hr[1], hi[1]), cji(hr[2], hi[2], hr[3], hi[3]), '0));
          cstate <= C_DET;
        end
        C_DET: begin
          det <= DW'(det_value(ga, gd, gbr, gbi));
          cstate <= C_RECIP;
          norm_start <= 1;
        end
        C_RECIP: if (norm_start) begin end
          else if (det <= 0 || norm_zero) begin error <= 1; cstate <= C_IDLE; end
          else if (norm_done) cstate <= C_ADJ;
        C_ADJ: begin
          // Row 0 of adj: (d, 0), (-b); row 1: (-conj b), (a, 0). Columns of H^H: conj(h_j0), conj(h_j1).
          mr[0] <= mre(gd, 39'sd0, -gbr, -gbi, hr[0], hi[0], hr[1], hi[1]); mi[0] <= mim(gd, 39'sd0, -gbr, -gbi, hr[0], hi[0], hr[1], hi[1]);
          mr[1] <= mre(gd, 39'sd0, -gbr, -gbi, hr[2], hi[2], hr[3], hi[3]); mi[1] <= mim(gd, 39'sd0, -gbr, -gbi, hr[2], hi[2], hr[3], hi[3]);
          mr[2] <= mre(-gbr, gbi, ga, 39'sd0, hr[0], hi[0], hr[1], hi[1]); mi[2] <= mim(-gbr, gbi, ga, 39'sd0, hr[0], hi[0], hr[1], hi[1]);
          mr[3] <= mre(-gbr, gbi, ga, 39'sd0, hr[2], hi[2], hr[3], hi[3]); mi[3] <= mim(-gbr, gbi, ga, 39'sd0, hr[2], hi[2], hr[3], hi[3]);
          cstate <= C_WEIGHT;
        end
        C_WEIGHT: begin
          bit overflow;
          overflow = 0;
          for (int k = 0; k < 4; k++) begin
            if (wfull_re[k] > WMAX || wfull_re[k] < WMIN || wfull_im[k] > WMAX || wfull_im[k] < WMIN)
              overflow = 1;
            else begin wr[k] <= WW'(wfull_re[k]); wi[k] <= WW'(wfull_im[k]); end
          end
          if (overflow) begin configured <= 0; error <= 1; end
          else configured <= 1;
          cstate <= C_IDLE;
        end
        default: cstate <= C_IDLE;
      endcase
      if (take) begin
        if (s_last && !second) begin
          error <= 1; configured <= 0; second <= 0; frame_active <= 0;
        end else begin
          second <= !second;
          frame_active <= !s_last;
        end
      end
      p_valid <= take && second; e_valid <= p_valid;
      if (e_valid) begin
        fifo[fifo_tail] <= {e0r, e0i, 1'b0}; fifo[3'(fifo_tail + 1'b1)] <= {e1r, e1i, e_last}; fifo_tail <= fifo_tail + 3'd2;
      end
      if (pop) fifo_head <= fifo_head + 1'b1;
      fifo_count <= fifo_count + {2'd0, e_valid, 1'b0} - {3'd0, pop};
      pending <= pending + {3'd0, take && second} - {3'd0, e_valid};
    end
  end
endmodule
