// FIR with runtime complex taps (research_core fir = np.convolve; bit-exact reference
// fir_fixed.filter). Taps: T <= TMAX = 2^LOG2TMAX complex Q17 words from the configuration
// port (accepted only between transactions). A transaction is one Q15 signal of L samples
// (s_last on its last) and gives the full convolution, L + T - 1 Q15 outputs (m_last on
// the last): acc[n] = sum_j A[j]*x[n-j] exactly (x = 0 outside 0..L-1), y = sat18(round(acc, 17)).
// LANES = 2^LOG2LANES complex multiply lanes (4 multipliers each): output n takes
// ceil(T/LANES) steps, step c handling taps j = c*LANES + l; with LANES >= T one output per
// clock in the inner-frame steady window when output credits suffice. Taps sit in LANES banks (bank l, address c), the signal in LANES banks of a ring of
// 4*TMAX samples (sample t in bank t mod LANES); lane l reads bank (n - l) mod LANES. Outputs
// preserve frame and sample order; the lane products are summed by a registered adder tree
// (one level per clock), then accumulated over the steps. Output n is issued once sample n is
// in, or, after s_last, up to n = L + T - 2 (zeros past the end). A power-of-two output FIFO
// gives m_ready backpressure (an output reserves its slot at its first step).
// error is sticky: more than TMAX taps or a configuration whose full signed18 input
// box cannot fit ACC_WIDTH (including the half-up rounding addition).
module fir_runtime #(
  parameter int LOG2LANES = 2,
  parameter int LOG2TMAX = 6,
  parameter bit RESET_ACTIVE = 1,
  parameter int ACC_WIDTH = 38 + LOG2TMAX,
  parameter bit COMPACT_TREE = 1
)(
  input logic clk, rst,
  input logic cfg_valid, cfg_last,
  input logic signed [17:0] cfg_re, cfg_im,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  localparam int LANES = 1 << LOG2LANES;
  localparam int TMAX = 1 << LOG2TMAX;
  localparam int LOG2RING = LOG2TMAX + 2;
  localparam int RING = 1 << LOG2RING;
  localparam int BW = LOG2RING - LOG2LANES;
  localparam int TW = LOG2TMAX > LOG2LANES ? LOG2TMAX - LOG2LANES : 1;
  localparam int SW = LOG2TMAX - LOG2LANES + 1;
  localparam int LB = LOG2LANES > 0 ? LOG2LANES : 1;
  localparam int CW = 37 + LOG2LANES;          // lane sum
  localparam int AW = ACC_WIDTH;
  localparam int SAFE_AW = 37 + LOG2TMAX;      // all legal taps and input box corners
  localparam int DEPTH = 4 + LOG2LANES;
  // Reserve -> DEPTH registers -> o_valid -> FIFO write -> first pop. room uses
  // pre-edge occupancy, so DEPTH+3 slots avoid credit bubbles at one issue/clock.
  localparam int FIFO_LOG2 = $clog2(DEPTH+3)>3 ? $clog2(DEPTH+3) : 3;
  localparam int FIFO_DEPTH = 1 << FIFO_LOG2;
  wire reset_now = rst == RESET_ACTIVE;
  initial if(ACC_WIDTH<18||ACC_WIDTH>63) $fatal(1,"[PARAMETER] FIR ACC_WIDTH must be in 18..63");

  function automatic logic signed [17:0] sat18(input logic signed [AW-1:0] value);
    logic signed [AW-1:0] rounded;
    rounded = (value + AW'(65536)) >>> 17;
    if (rounded[AW-1:17] != {(AW-17){rounded[AW-1]}}) return rounded[AW-1] ? 18'sh20000 : 18'sd131071;
    return rounded[17:0];
  endfunction

  // Configuration and transaction state.
  logic [LOG2TMAX:0] tap_count, taps;
  wire cfg_take = cfg_valid && cfg_ready;
  wire width_ok;
  generate
    if(ACC_WIDTH < SAFE_AW) begin : g_width_guard
      // Each linear term attains its extrema at signed18 box corners. The bounds
      // include zero, so they also bound every partial sum and shortened frame edge.
      function automatic logic signed [SAFE_AW-1:0] term_bound(
        input logic signed [18:0] coefficient,input bit upper);
        logic signed [SAFE_AW-1:0] shifted;
        shifted=SAFE_AW'(coefficient)<<<17;
        return (coefficient>=0)==upper ? shifted-SAFE_AW'(coefficient) : -shifted;
      endfunction
      logic signed [SAFE_AW-1:0] lo_re,hi_re,lo_im,hi_im;
      wire signed [18:0] hr={cfg_re[17],cfg_re},hi={cfg_im[17],cfg_im};
      wire signed [SAFE_AW-1:0] next_lo_re=(tap_count==0?'0:lo_re)+term_bound(hr,0)+term_bound(-hi,0);
      wire signed [SAFE_AW-1:0] next_hi_re=(tap_count==0?'0:hi_re)+term_bound(hr,1)+term_bound(-hi,1);
      wire signed [SAFE_AW-1:0] next_lo_im=(tap_count==0?'0:lo_im)+term_bound(hi,0)+term_bound(hr,0);
      wire signed [SAFE_AW-1:0] next_hi_im=(tap_count==0?'0:hi_im)+term_bound(hi,1)+term_bound(hr,1);
      localparam logic signed [SAFE_AW-1:0] LOW=-(SAFE_AW'(1)<<(ACC_WIDTH-1));
      localparam logic signed [SAFE_AW-1:0] HIGH=(SAFE_AW'(1)<<(ACC_WIDTH-1))-1;
      assign width_ok=next_lo_re>=LOW&&next_lo_im>=LOW
                    &&next_hi_re<=HIGH-SAFE_AW'(65536)&&next_hi_im<=HIGH-SAFE_AW'(65536);
      always_ff @(posedge clk) begin
        if(reset_now) begin lo_re<=0;hi_re<=0;lo_im<=0;hi_im<=0;end
        else if(cfg_take&&tap_count<(LOG2TMAX+1)'(TMAX)) begin
          lo_re<=cfg_last?'0:next_lo_re;hi_re<=cfg_last?'0:next_hi_re;
          lo_im<=cfg_last?'0:next_lo_im;hi_im<=cfg_last?'0:next_hi_im;
        end
      end
    end else begin : g_full_width
      assign width_ok=1'b1;
    end
  endgenerate
  logic [23:0] wcount, n;
  logic last_seen;
  logic [SW-1:0] step, steps;
  logic [FIFO_LOG2:0] fifo_count, reserved;
  logic [36:0] fifo [0:FIFO_DEPTH-1];
  logic [FIFO_LOG2-1:0] fifo_head, fifo_tail;
  wire busy = wcount != '0 || last_seen || reserved != '0 || fifo_count != '0;
  assign cfg_ready = !reset_now && !error && !busy;
  // Configuration wins only when it can be accepted; a held offer cannot stop an open frame.
  assign s_ready = !reset_now && !error && configured && !cfg_take && !last_seen && wcount < n + 24'(RING - TMAX);
  wire take = s_valid && s_ready;
  // Output n exists while sample n is in or, after s_last, while n < L + T - 1.
  wire [23:0] total = wcount + 24'(taps) - 24'd1;
  wire available = configured && (n < wcount || last_seen && n < total);
  wire room = {1'b0, fifo_count} + {1'b0, reserved} < (FIFO_LOG2+2)'(FIFO_DEPTH);
  wire issue = available && (step != '0 || room);
  wire first = step == '0;
  wire last = step == steps - 1'b1;

  // Banks.
  wire [35:0] tap_q [0:LANES-1];
  wire [35:0] hist_q [0:LANES-1];
  genvar b;
  generate
    for (b = 0; b < LANES; b = b + 1) begin : g_bank
      wire borrow;
      if (b == 0) begin : g_first
        assign borrow = 1'b0;
      end else begin : g_other
        assign borrow = (n & 24'(LANES - 1)) < 24'(b);
      end
      wire [BW-1:0] base = BW'(n >> LOG2LANES) - BW'(borrow);
      sync_ram #(.WIDTH(36),.ADDR_WIDTH(TW)) tap_bank(
        .clk(clk),.wr_en(cfg_take && tap_count < (LOG2TMAX+1)'(TMAX) && (tap_count & (LOG2TMAX+1)'(LANES-1)) == (LOG2TMAX+1)'(b)),.rd_en(issue),
        .wr_addr(TW'(tap_count >> LOG2LANES)),.rd_addr(TW'(step)),.wr_data({cfg_re,cfg_im}),.rd_data(tap_q[b]));
      sync_ram #(.WIDTH(36),.ADDR_WIDTH(BW)) hist_bank(
        .clk(clk),.wr_en(take && (wcount & 24'(LANES-1)) == 24'(b)),.rd_en(issue),
        .wr_addr(BW'(wcount >> LOG2LANES)),.rd_addr(base - BW'(step)),.wr_data({s_re,s_im}),.rd_data(hist_q[b]));
    end
  endgenerate

  // Pipeline: issue -> i (validity) -> r (operands) -> p (products) -> z (complex lane
  // products) -> LOG2LANES tree levels -> accumulate -> FIFO.
  logic [DEPTH-1:0] f_valid, f_first, f_last, f_final;
  logic i_use [0:LANES-1], r_use [0:LANES-1];
  logic [LB-1:0] i_low;
  logic signed [17:0] r_tr [0:LANES-1], r_ti [0:LANES-1], r_xr [0:LANES-1], r_xi [0:LANES-1];
  logic signed [35:0] p_rr [0:LANES-1], p_ii [0:LANES-1], p_ri [0:LANES-1], p_ir [0:LANES-1];
  // An exact real lane difference fits signed36; the imaginary sum needs signed37
  // because (-2^17)*(-2^17) twice equals +2^35. Each tree level adds one bit.
  // COMPACT_TREE=0 reproduces the former uniform CW layout for numeric controls.
  genvar v, k;
  generate for(v=0;v<=LOG2LANES;v++) begin : g_tree
    localparam int RW=COMPACT_TREE ? 36+v : CW;
    localparam int IW=COMPACT_TREE ? 37+v : CW;
    (* use_dsp="no" *) logic signed [RW-1:0] re[0:(LANES>>v)-1];
    (* use_dsp="no" *) logic signed [IW-1:0] im[0:(LANES>>v)-1];
    for(k=0;k<(LANES>>v);k++) begin : g_node
      if(v==0) begin : g_lane
        always_ff @(posedge clk) begin
          re[k]<=RW'(p_rr[k])-RW'(p_ii[k]);
          im[k]<=IW'(p_ri[k])+IW'(p_ir[k]);
        end
      end else begin : g_sum
        always_ff @(posedge clk) begin
          re[k]<=RW'(g_tree[v-1].re[2*k])+RW'(g_tree[v-1].re[2*k+1]);
          im[k]<=IW'(g_tree[v-1].im[2*k])+IW'(g_tree[v-1].im[2*k+1]);
        end
      end
    end
  end endgenerate
  (* use_dsp="no" *) logic signed [AW-1:0] acc_re, acc_im;
  wire signed [AW-1:0] sum_re = AW'(g_tree[LOG2LANES].re[0]), sum_im = AW'(g_tree[LOG2LANES].im[0]);
  wire signed [AW-1:0] total_re = f_first[DEPTH-1] ? sum_re : acc_re + sum_re;
  wire signed [AW-1:0] total_im = f_first[DEPTH-1] ? sum_im : acc_im + sum_im;
  logic o_valid, o_final;
  logic signed [AW-1:0] o_re, o_im;
  assign m_valid = fifo_count != '0;
  assign m_re = fifo[fifo_head][36:19];
  assign m_im = fifo[fifo_head][18:1];
  assign m_last = fifo[fifo_head][0];
  wire pop = m_valid && m_ready;

  always_ff @(posedge clk) begin
    for (int l = 0; l < LANES; l++) begin
      // Tap j = step*LANES + l: used if j < T, j <= n and sample n - j exists.
      i_use[l] <= issue && (32'(step) << LOG2LANES) + 32'(l) < 32'(taps) && (32'(step) << LOG2LANES) + 32'(l) <= 32'(n)
                  && n - 24'((32'(step) << LOG2LANES) + 32'(l)) < wcount;
      r_use[l] <= i_use[l];
      r_tr[l] <= $signed(tap_q[l][35:18]); r_ti[l] <= $signed(tap_q[l][17:0]);
      r_xr[l] <= $signed(hist_q[LB'(i_low - LB'(l)) & LB'(LANES-1)][35:18]);
      r_xi[l] <= $signed(hist_q[LB'(i_low - LB'(l)) & LB'(LANES-1)][17:0]);
      p_rr[l] <= r_use[l] ? r_tr[l]*r_xr[l] : 36'sd0; p_ii[l] <= r_use[l] ? r_ti[l]*r_xi[l] : 36'sd0;
      p_ri[l] <= r_use[l] ? r_tr[l]*r_xi[l] : 36'sd0; p_ir[l] <= r_use[l] ? r_ti[l]*r_xr[l] : 36'sd0;
    end
    i_low <= LB'(n) & LB'(LANES-1);
    acc_re <= total_re; acc_im <= total_im;
    o_re <= total_re; o_im <= total_im; o_final <= f_final[DEPTH-1];
    if (reset_now) begin
      configured <= 0; error <= 0; tap_count <= '0; taps <= '0; wcount <= '0; n <= '0; last_seen <= 0;
      step <= '0; steps <= '0; f_valid <= '0; o_valid <= 0; reserved <= '0; fifo_count <= '0; fifo_head <= '0; fifo_tail <= '0;
    end else begin
      if (cfg_take) begin
        configured <= 0;
        if (tap_count < (LOG2TMAX+1)'(TMAX)) tap_count <= tap_count + 1'b1;
        else begin tap_count <= (LOG2TMAX+1)'(TMAX); error <= 1; end
        if (cfg_last) begin
          tap_count <= '0;
          if (tap_count < (LOG2TMAX+1)'(TMAX) && width_ok) begin
            taps <= tap_count + 1'b1;
            steps <= SW'((tap_count + (LOG2TMAX+1)'(LANES)) >> LOG2LANES);
            configured <= 1;
          end else error <= 1;
        end
      end
      if (take) begin wcount <= wcount + 1'b1; if (s_last) last_seen <= 1; end
      f_valid <= {f_valid[DEPTH-2:0], issue};
      f_first <= {f_first[DEPTH-2:0], first};
      f_last <= {f_last[DEPTH-2:0], last};
      f_final <= {f_final[DEPTH-2:0], last && last_seen && n == total - 24'd1};
      if (issue) begin
        if (last) begin
          step <= '0; n <= n + 1'b1;
          // The final output of the transaction: restart for the next one.
          if (last_seen && n == total - 24'd1) begin wcount <= '0; n <= '0; last_seen <= 0; end
        end else step <= step + 1'b1;
      end
      o_valid <= f_valid[DEPTH-1] && f_last[DEPTH-1];
      if (o_valid) begin fifo[fifo_tail] <= {sat18(o_re), sat18(o_im), o_final}; fifo_tail <= fifo_tail + 1'b1; end
      if (pop) fifo_head <= fifo_head + 1'b1;
      fifo_count <= fifo_count + (FIFO_LOG2+1)'(o_valid) - (FIFO_LOG2+1)'(pop);
      reserved <= reserved + (FIFO_LOG2+1)'(issue && first) - (FIFO_LOG2+1)'(o_valid);
    end
  end
endmodule
