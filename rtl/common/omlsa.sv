// OM-LSA speech enhancement (research_core omlsa; bit-exact reference omlsa_fixed.enhance).
// Chain: reflect_pad (N on both sides) -> stft_analysis (N, HOP) -> omlsa_gain -> stft_synthesis
// -> cut: of the (F-1)*HOP + N synthesised samples, [N, N + L) are output (m_last on the L-th).
// Configuration (one transfer, between transactions): nnoise (1..16) and A = round(alpha*65536).
// A transaction is one Q15 signal of L >= N+1 samples (s_last on the last) with at least nnoise
// frames; it gives L Q15 samples. The signal lengths travel in a 4-entry FIFO (a next signal can
// enter while the previous one still leaves). Tables come from MEM_DIR (tools/fft_tables.py).
// Supported (N, HOP): (16, 4), (32, 8), (64, 16).
// error is sticky: any stage's error.
module omlsa #(
  parameter int LOG2N = 5,
  parameter int LOG2HOP = 3,
  parameter bit RESET_ACTIVE = 1,
  parameter MEM_DIR = "rtl/common/mem",
  // omlsa_gain intermediate widths (docs/RTL_OMLSA_WIDTHS.md); 128 each is the former layout.
  parameter int RECIP_WIDTH=18, GAMMA_WIDTH=72, XI_WIDTH=47, V_WIDTH=48, G1_WIDTH=37, T_WIDTH=48, A_WIDTH=37, OUT_WIDTH=41, GG_WIDTH=34, PREV_WIDTH=49
)(
  input logic clk, rst,
  input logic cfg_valid,
  input logic [4:0] cfg_nnoise,
  input logic [16:0] cfg_alpha,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  localparam int N = 1 << LOG2N;
  localparam TWIDDLE_FILE = LOG2N == 4 ? {MEM_DIR,"/fft_twiddle_16.mem"} : LOG2N == 6 ? {MEM_DIR,"/fft_twiddle_64.mem"} : {MEM_DIR,"/fft_twiddle_32.mem"};
  localparam WINDOW_FILE = LOG2N == 4 ? {MEM_DIR,"/stft_window_16.mem"} : LOG2N == 6 ? {MEM_DIR,"/stft_window_64.mem"} : {MEM_DIR,"/stft_window_32.mem"};
  // The reciprocal table names differ in length: chosen per generate branch below.
  wire reset_now = rst == RESET_ACTIVE;
  logic [4:0] nnoise;
  logic [16:0] alpha;
  // Signal lengths in flight.
  logic [23:0] lengths [0:3];
  logic [1:0] len_head, len_tail;
  logic [2:0] len_count;
  wire pad_ready, pad_valid, pad_last, pad_error;
  wire signed [17:0] pad_re, pad_im;
  // До входного TLAST длины ещё нет в FIFO, но сигнал уже занимает тракт.
  logic in_active;
  assign cfg_ready = !reset_now && !in_active && len_count == '0;
  wire cfg_take = cfg_valid && cfg_ready;
  // The signal length, counted at the input.
  logic [23:0] in_count;
  wire [23:0] pad_length_next = in_count + 1'b1;
  wire pad_in_ready;
  wire in_enable = !reset_now && configured && !cfg_take && len_count < 3'd4;
  assign s_ready = in_enable && pad_in_ready;
  wire take = s_valid && s_ready;
  reflect_pad #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE)) pad(
    .clk(clk),.rst(rst),.s_valid(s_valid && in_enable),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_ready(pad_in_ready),
    .m_valid(pad_valid),.m_last(pad_last),.m_re(pad_re),.m_im(pad_im),.m_ready(pad_ready),.error(pad_error));
  wire an_valid, an_last, an_ready, an_error;
  wire signed [23:0] an_re, an_im;
  stft_analysis #(.LOG2N(LOG2N),.LOG2HOP(LOG2HOP),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE),.WINDOW_FILE(WINDOW_FILE)) analysis(
    .clk(clk),.rst(rst),.s_valid(pad_valid),.s_last(pad_last),.s_re(pad_re),.s_im(pad_im),.s_ready(pad_ready),
    .m_valid(an_valid),.m_last(an_last),.m_re(an_re),.m_im(an_im),.m_ready(an_ready),.error(an_error));
  wire g_valid, g_last, g_ready, g_error;
  wire signed [23:0] g_re, g_im;
  omlsa_gain #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE),.MEM_DIR(MEM_DIR),
    .RECIP_WIDTH(RECIP_WIDTH),.GAMMA_WIDTH(GAMMA_WIDTH),.XI_WIDTH(XI_WIDTH),.V_WIDTH(V_WIDTH),.G1_WIDTH(G1_WIDTH),.T_WIDTH(T_WIDTH),.A_WIDTH(A_WIDTH),.OUT_WIDTH(OUT_WIDTH),.GG_WIDTH(GG_WIDTH),.PREV_WIDTH(PREV_WIDTH)) gain(
    .clk(clk),.rst(rst),.nnoise(nnoise),.alpha(alpha),.s_valid(an_valid),.s_last(an_last),.s_re(an_re),.s_im(an_im),.s_ready(an_ready),
    .m_valid(g_valid),.m_last(g_last),.m_re(g_re),.m_im(g_im),.m_ready(g_ready),.error(g_error));
  wire y_valid, y_last, y_error;
  wire signed [17:0] y_re, y_im;
  wire y_ready;
  generate
    if (LOG2N == 6) begin : g64
      stft_synthesis #(.LOG2N(LOG2N),.LOG2HOP(LOG2HOP),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE),.WINDOW_FILE(WINDOW_FILE),
        .RECIP_FILE({MEM_DIR,"/stft_recip_64_16.mem"})) synthesis(
        .clk(clk),.rst(rst),.s_valid(g_valid),.s_last(g_last),.s_re(g_re),.s_im(g_im),.s_ready(g_ready),
        .m_valid(y_valid),.m_last(y_last),.m_re(y_re),.m_im(y_im),.m_ready(y_ready),.error(y_error));
    end else if (LOG2N == 4) begin : g16
      stft_synthesis #(.LOG2N(LOG2N),.LOG2HOP(LOG2HOP),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE),.WINDOW_FILE(WINDOW_FILE),
        .RECIP_FILE({MEM_DIR,"/stft_recip_16_4.mem"})) synthesis(
        .clk(clk),.rst(rst),.s_valid(g_valid),.s_last(g_last),.s_re(g_re),.s_im(g_im),.s_ready(g_ready),
        .m_valid(y_valid),.m_last(y_last),.m_re(y_re),.m_im(y_im),.m_ready(y_ready),.error(y_error));
    end else begin : g32
      stft_synthesis #(.LOG2N(LOG2N),.LOG2HOP(LOG2HOP),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE),.WINDOW_FILE(WINDOW_FILE),
        .RECIP_FILE({MEM_DIR,"/stft_recip_32_8.mem"})) synthesis(
        .clk(clk),.rst(rst),.s_valid(g_valid),.s_last(g_last),.s_re(g_re),.s_im(g_im),.s_ready(g_ready),
        .m_valid(y_valid),.m_last(y_last),.m_re(y_re),.m_im(y_im),.m_ready(y_ready),.error(y_error));
    end
  endgenerate
  // Cut [N, N + L) of every synthesised transaction.
  logic [23:0] index;
  wire [23:0] length = lengths[len_head];
  // The synthesis starts before the signal's last sample (its length) is in; the samples up to
  // N + L - 1 need no length, and the last frames (which need the end pad) come after s_last,
  // so the length is known before the end of the window.
  wire known = len_count != '0;
  wire in_window = index >= 24'(N) && (!known || index < 24'(N) + length);
  assign m_valid = y_valid && in_window;
  assign m_re = y_re; assign m_im = y_im;
  assign m_last = known && index == 24'(N) + length - 1'b1;
  assign y_ready = in_window ? m_ready : 1'b1;
  wire y_take = y_valid && y_ready;
  always_ff @(posedge clk) begin
    if (reset_now) begin
      configured <= 0; error <= 0; len_head <= '0; len_tail <= '0; len_count <= '0; index <= '0; in_count <= '0; in_active <= 0;
    end else begin
      if (take) begin in_count <= s_last ? '0 : in_count + 1'b1; in_active <= !s_last; end
      if (cfg_take) begin
        nnoise <= cfg_nnoise; alpha <= cfg_alpha;
        configured <= cfg_nnoise != '0 && cfg_nnoise <= 5'd16; if (cfg_nnoise == '0 || cfg_nnoise > 5'd16) error <= 1;
      end
      if (pad_error || an_error || g_error || y_error) error <= 1;
      // The length of a signal is known once its last sample is in.
      if (take && s_last) begin lengths[len_tail] <= pad_length_next; len_tail <= len_tail + 1'b1; end
      if (y_take) begin index <= y_last ? '0 : index + 1'b1; if (y_last) len_head <= len_head + 1'b1; end
      len_count <= len_count + {2'd0, take && s_last} - {2'd0, y_take && y_last};
    end
  end
endmodule
