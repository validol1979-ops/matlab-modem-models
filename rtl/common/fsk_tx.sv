// M-FSK transmitter (research_core fsk_tx; bit-exact reference fsk_fixed.transmit).
// Configuration (between transactions): the phase step of every label, one 32-bit word per
// transfer (fsk_fixed.steps designs them, turns * 2^32 per sample), and the symbol length n
// (sampled with cfg_last). A transaction is labels (s_last on the last) and gives n samples
// per label, m_last on the very last: the phase of sample t of a symbol is t*STEP mod 2^32,
// its top 12 bits index the pilot's Q17 cos table, y = (rnd(cos, 2), rnd(sin, 2)) in Q15.
// One sample per clock, symbols back to back (the next label is taken with the last sample);
// m_ready backpressure. error is sticky: a label without a loaded step, more than 2^LOG2M
// steps, or n = 0.
module fsk_tx #(
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
  input logic [(LOG2M > 0 ? LOG2M : 1)-1:0] s_label,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  localparam int M = 1 << LOG2M;
  localparam int LB = LOG2M > 0 ? LOG2M : 1;
  wire reset_now = rst == RESET_ACTIVE;
  logic [31:0] step_table [0:M-1];
  logic [LOG2M:0] loaded, count;
  logic [LOG2NMAX:0] n, t;
  logic active, in_tx, cur_last, e_valid, e_last, o_valid, o_last;
  logic [31:0] phase, step;
  logic signed [17:0] o_re, o_im;
  wire ce = !o_valid || m_ready;
  wire emit = active && ce;
  wire symbol_end = t == n - 1'b1;
  assign cfg_ready = !reset_now && !in_tx && !active && !e_valid && !o_valid;
  wire cfg_take = cfg_valid && cfg_ready;
  // A one-word valid table can coherently start a new frame on this edge. A
  // partial/invalid configuration must finish before a label can be accepted.
  wire cfg_single = cfg_last && count == '0 && cfg_n != '0;
  assign s_ready = !reset_now && configured && ce && (!active || symbol_end) && (!cfg_take || cfg_single);
  wire take = s_valid && s_ready;
  wire [17:0] cos_q, sin_q;
  sync_rom #(.WIDTH(18),.ADDR_WIDTH(12),.INIT_FILE({TABLE_DIR,"/cos.mem"})) cosine(clk,ce,phase[31:20],cos_q);
  sync_rom #(.WIDTH(18),.ADDR_WIDTH(12),.INIT_FILE({TABLE_DIR,"/cos.mem"})) sine(clk,ce,phase[31:20]-12'd1024,sin_q);
  assign m_valid = o_valid; assign m_last = o_last; assign m_re = o_re; assign m_im = o_im;
  always_ff @(posedge clk) begin
    if (ce) begin
      o_re <= 18'((19'($signed(cos_q)) + 19'sd2) >>> 2); o_im <= 18'((19'($signed(sin_q)) + 19'sd2) >>> 2); o_last <= e_last;
      e_last <= cur_last && symbol_end;
    end
    if (reset_now) begin
      configured <= 0; error <= 0; loaded <= '0; count <= '0; active <= 0; in_tx <= 0; e_valid <= 0; o_valid <= 0;
    end else begin
      if (cfg_take) begin
        configured <= 0; count <= count + 1'b1;
        if (count < (LOG2M+1)'(M)) step_table[LB'(count)] <= cfg_step; else error <= 1;
        if (cfg_last) begin
          count <= '0; loaded <= count + 1'b1; n <= cfg_n;
          if (count < (LOG2M+1)'(M) && cfg_n != '0) configured <= 1; else error <= 1;
        end
      end
      if (ce) begin e_valid <= emit; o_valid <= e_valid; end
      if (emit) begin phase <= phase + step; t <= t + 1'b1; if (symbol_end) active <= 0; end
      if (take) begin
        active <= 1; in_tx <= !s_last; t <= '0; phase <= '0; cur_last <= s_last;
        step <= cfg_take && s_label == LB'(count) ? cfg_step : step_table[s_label];
        if ((LOG2M+1)'(s_label) >= (cfg_take ? count + 1'b1 : loaded)) error <= 1;
      end
    end
  end
endmodule
