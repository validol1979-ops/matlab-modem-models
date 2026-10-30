// M-FSK receiver (research_core fsk_rx; bit-exact reference fsk_fixed.receive).
// Configuration as fsk_tx (the label steps and n). A transaction is whole symbols of n Q15
// samples (s_last on the last sample) and gives one label per symbol (m_last on the last).
// M correlators in parallel: acc_m = sum_t x_t*(cos - j sin)(t*STEP_m) exactly (pilot cos
// table, two ROMs per correlator), c_m = rnd(acc_m, 17 + B) with B = bit length of n - 1,
// energy_m = re^2 + im^2, label = the first maximum. Pipeline: tables, products,
// accumulation (a symbol's last sample snapshots the sums), rounding, energies, argmax into
// an 8-entry label FIFO. One sample per clock; the input stalls only if the FIFO and the
// symbols in flight would exceed it (m_ready backpressure).
// error is sticky: more than 2^LOG2M steps, or n = 0.
module fsk_rx #(
  parameter int LOG2M = 2,
  parameter int LOG2NMAX = 5,
  parameter bit RESET_ACTIVE = 1,
  parameter TABLE_DIR = "rtl/modems/bpsk_costas_2008_08_25/tables"
)(
  input logic clk, rst,
  input logic cfg_valid, cfg_last,
  input logic [31:0] cfg_step,
  input logic [LOG2NMAX:0] cfg_n,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic [(LOG2M > 0 ? LOG2M : 1)-1:0] m_label,
  input logic m_ready,
  output logic error
);
  localparam int M = 1 << LOG2M;
  localparam int LB = LOG2M > 0 ? LOG2M : 1;
  localparam int AW = 37 + LOG2NMAX;            // correlator sums
  localparam int CW = AW - 17;                  // rounded correlation (shift >= 17)
  localparam int EW = 2*CW;                     // energy
  wire reset_now = rst == RESET_ACTIVE;

  logic [31:0] step_table [0:M-1];
  logic [LOG2M:0] loaded, count;
  logic [LOG2NMAX:0] n, t;
  logic [5:0] shift;                            // 17 + bit length of n - 1
  logic in_tx;
  logic [31:0] phase [0:M-1];
  logic [3:0] fifo_count, pending;
  logic [LB:0] fifo [0:7];
  logic [2:0] fifo_head, fifo_tail;
  assign cfg_ready = !reset_now && !in_tx && pending == '0 && t == '0;
  wire cfg_take = cfg_valid && cfg_ready;
  wire cfg_single = cfg_last && count == '0 && cfg_n != '0;
  assign s_ready = !reset_now && configured && {1'b0, fifo_count} + {1'b0, pending} < 5'd8 && (!cfg_take || cfg_single);
  wire take = s_valid && s_ready;
  wire [LOG2NMAX:0] input_n = cfg_take ? cfg_n : n;
  wire symbol_end = t == input_n - 1'b1;
  wire pop = m_valid && m_ready;

  // Stage a: table reads; b: products; c: accumulation and snapshot.
  logic a_valid, a_first, a_end, a_last, b_valid, b_first, b_end, b_last, c_valid, c_last;
  logic signed [17:0] a_re, a_im;
  logic signed [35:0] p_rc [0:M-1], p_is [0:M-1], p_ic [0:M-1], p_rs [0:M-1];
  (* use_dsp="no" *) logic signed [AW-1:0] acc_re [0:M-1], acc_im [0:M-1];
  logic signed [AW-1:0] hold_re [0:M-1], hold_im [0:M-1];
  // Decision: d (rounded), e (energies), f (argmax).
  logic d_valid, d_last, e_valid, e_last;
  logic signed [CW-1:0] r_re [0:M-1], r_im [0:M-1];
  logic [EW-1:0] energy [0:M-1];
  logic [LB-1:0] best_label;
  always_comb begin
    logic [EW-1:0] best;
    best = energy[0]; best_label = '0;
    // Only the loaded tones take part (the table may be shorter than 2^LOG2M).
    for (int m = 1; m < M; m++) if ((LOG2M+1)'(m) < loaded && energy[m] > best) begin best = energy[m]; best_label = LB'(m); end
  end
  assign m_valid = fifo_count != 4'd0;
  assign m_label = fifo[fifo_head][LB:1];
  assign m_last = fifo[fifo_head][0];

  genvar g;
  generate
    for (g = 0; g < M; g = g + 1) begin : g_correlator
      wire [17:0] cos_q, sin_q;
      sync_rom #(.WIDTH(18),.ADDR_WIDTH(12),.INIT_FILE({TABLE_DIR,"/cos.mem"})) cosine(clk,take,phase[g][31:20],cos_q);
      sync_rom #(.WIDTH(18),.ADDR_WIDTH(12),.INIT_FILE({TABLE_DIR,"/cos.mem"})) sine(clk,take,phase[g][31:20]-12'd1024,sin_q);
      wire signed [AW-1:0] sum_re = AW'(p_rc[g]) + AW'(p_is[g]), sum_im = AW'(p_ic[g]) - AW'(p_rs[g]);
      wire signed [AW-1:0] next_re = b_first ? sum_re : acc_re[g] + sum_re;
      wire signed [AW-1:0] next_im = b_first ? sum_im : acc_im[g] + sum_im;
      always_ff @(posedge clk) begin
        if (a_valid) begin
          p_rc[g] <= a_re*$signed(cos_q); p_is[g] <= a_im*$signed(sin_q);
          p_ic[g] <= a_im*$signed(cos_q); p_rs[g] <= a_re*$signed(sin_q);
        end
        if (b_valid) begin
          acc_re[g] <= next_re; acc_im[g] <= next_im;
          if (b_end) begin hold_re[g] <= next_re; hold_im[g] <= next_im; end
        end
        if (c_valid) begin
          r_re[g] <= CW'((hold_re[g] + (AW'(1) <<< (shift - 1'b1))) >>> shift);
          r_im[g] <= CW'((hold_im[g] + (AW'(1) <<< (shift - 1'b1))) >>> shift);
        end
        if (d_valid) energy[g] <= $unsigned(EW'(r_re[g])*EW'(r_re[g]) + EW'(r_im[g])*EW'(r_im[g]));
      end
    end
  endgenerate

  always_ff @(posedge clk) begin
    if (take) begin a_re <= s_re; a_im <= s_im; a_first <= t == '0; a_end <= symbol_end; a_last <= s_last; end
    b_first <= a_first; b_end <= a_end; b_last <= a_last;
    c_last <= b_last; d_last <= c_last; e_last <= d_last;
    if (reset_now) begin
      configured <= 0; error <= 0; loaded <= '0; count <= '0; t <= '0; in_tx <= 0;
      a_valid <= 0; b_valid <= 0; c_valid <= 0; d_valid <= 0; e_valid <= 0;
      pending <= '0; fifo_count <= '0; fifo_head <= '0; fifo_tail <= '0;
      for (int m = 0; m < M; m++) phase[m] <= '0;
    end else begin
      if (cfg_take) begin
        configured <= 0; count <= count + 1'b1;
        if (count < (LOG2M+1)'(M)) step_table[LB'(count)] <= cfg_step; else error <= 1;
        if (cfg_last) begin
          count <= '0; loaded <= count + 1'b1; n <= cfg_n; t <= '0;
          for (int m = 0; m < M; m++) phase[m] <= '0;
          // shift = 17 + bit length of n - 1 (17 for n = 1).
          shift <= 6'd17;
          for (int b = 0; b <= LOG2NMAX; b++) if (((cfg_n - 1'b1) >> b) != '0) shift <= 6'(18 + b);
          if (count < (LOG2M+1)'(M) && cfg_n != '0) configured <= 1; else error <= 1;
        end
      end
      // Phases: t*STEP_m for the sample being taken (restarted at every symbol).
      if (take) begin
        in_tx <= !s_last; t <= symbol_end ? '0 : t + 1'b1;
        for (int m = 0; m < M; m++) phase[m] <= symbol_end ? '0 : phase[m] +
          (cfg_take && (LOG2M+1)'(m) == count ? cfg_step : step_table[m]);
      end
      a_valid <= take; b_valid <= a_valid;
      c_valid <= b_valid && b_end; d_valid <= c_valid; e_valid <= d_valid;
      if (e_valid) begin fifo[fifo_tail] <= {best_label, e_last}; fifo_tail <= fifo_tail + 1'b1; end
      if (pop) fifo_head <= fifo_head + 1'b1;
      fifo_count <= fifo_count + {3'd0, e_valid} - {3'd0, pop};
      pending <= pending + {3'd0, take && symbol_end} - {3'd0, e_valid};
    end
  end
endmodule
