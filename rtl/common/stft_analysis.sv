// STFT analysis (bit-exact reference stft_fixed.analyze): frames of N samples every HOP,
// sqrt-Hann window, forward FFT. One transaction is one signal of L Q15 samples (s_last
// on its last sample); it gives F = 1 + (L-N)/HOP frames of N bins X/N in Q19 (24 bit),
// m_last on the very last bin. Samples after the last full frame are accepted and ignored;
// L < N gives no frames and sets error. N = 2^LOG2N (2..8), HOP = 2^LOG2HOP, N/HOP in 1, 2, 4.
// Ring buffer: sample t at address t mod 2N of one sync_ram. Frame f (start f*HOP) is read
// once its N samples are in and either the next frame's samples are in too or s_last has
// been seen, so it is known at issue whether f is the final frame; a per-frame flag FIFO
// carries that to the FFT output. The input may run up to 2N samples ahead of the frame
// being read; after s_last it waits until the transaction's frames are all read.
// Datapath: z = round(x*W, 13) (W = Q17 window ROM, z in Q19, 22 bits), fft_r2sdf
// (IN_WIDTH 22, WIDTH 24, forward). Read pipeline: RAM and window read, product, z; it
// stalls on the FFT's s_ready. Each frame needs N clocks, so with N/HOP = R the input runs
// at up to 1/R sample per clock.
// error is sticky: L < N, or the core error.
module stft_analysis #(
  parameter int LOG2N = 6,
  parameter int LOG2HOP = 4,
  parameter bit RESET_ACTIVE = 1,
  parameter TWIDDLE_FILE = "rtl/common/mem/fft_twiddle_64.mem",
  parameter WINDOW_FILE = "rtl/common/mem/stft_window_64.mem"
)(
  input logic clk, rst,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [23:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  localparam int N = 1 << LOG2N;
  localparam int HOP = 1 << LOG2HOP;
  wire reset_now = rst == RESET_ACTIVE;

  // Input side.
  logic [23:0] wcount, frame_start;
  logic last_seen;
  logic reading;
  logic [LOG2N-1:0] k;
  wire [23:0] ahead = wcount - frame_start;
  assign s_ready = !reset_now && !last_seen && ahead < 24'(2*N);
  wire take = s_valid && s_ready;
  // Frame scheduling (frame_start = the next or current frame).
  wire have_frame = wcount >= frame_start + 24'(N);
  wire next_known = wcount >= frame_start + 24'(HOP + N) || last_seen;
  wire final_frame = last_seen && wcount < frame_start + 24'(HOP + N);
  wire done = last_seen && !reading && !have_frame;

  // Read pipeline: issue -> RAM and window data -> product -> rounded z.
  logic v1, v2, v3, l1, l2, l3;
  // |x*W| < 2^17 * 2^17: the products fit 35 bits.
  logic signed [34:0] p_re, p_im;
  logic signed [21:0] z_re, z_im;
  wire f_ready;
  wire ce = !v3 || f_ready;
  wire issue = ce && reading;
  wire [35:0] ram_q;
  wire [17:0] window_q;
  sync_ram #(.WIDTH(36),.ADDR_WIDTH(LOG2N+1)) ring(
    .clk(clk),.wr_en(take),.rd_en(issue),.wr_addr(wcount[LOG2N:0]),.rd_addr((frame_start[LOG2N:0] + (LOG2N+1)'(k))),
    .wr_data({s_re,s_im}),.rd_data(ram_q));
  sync_rom #(.WIDTH(18),.ADDR_WIDTH(LOG2N),.INIT_FILE(WINDOW_FILE)) window(
    .clk(clk),.rd_en(issue),.rd_addr(k),.rd_data(window_q));
  wire signed [17:0] x_re = ram_q[35:18], x_im = ram_q[17:0];

  // Per-frame final flags, frame order through the FFT (at most a few frames in flight).
  logic [7:0] final_fifo;
  logic [2:0] final_head, final_tail;
  logic frame_final;
  wire f_valid, f_last, f_inverse, f_error;
  fft_r2sdf #(.LOG2N(LOG2N),.IN_WIDTH(22),.WIDTH(24),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) fft(
    .clk(clk),.rst(rst),.s_valid(v3),.s_last(l3),.s_inverse(1'b0),.s_re(z_re),.s_im(z_im),.s_ready(f_ready),
    .m_valid(f_valid),.m_last(f_last),.m_inverse(f_inverse),.m_re(m_re),.m_im(m_im),.m_ready(m_ready),.error(f_error));
  assign m_valid = f_valid;
  assign m_last = f_last && final_fifo[final_head];

  always_ff @(posedge clk) begin
    if (ce) begin
      l1 <= k == LOG2N'(N-1);
      // The window is positive (< 2^17), so its 18-bit word reads as signed.
      p_re <= x_re*$signed(window_q); p_im <= x_im*$signed(window_q); l2 <= l1;
      z_re <= 22'((p_re + 35'sd4096) >>> 13); z_im <= 22'((p_im + 35'sd4096) >>> 13); l3 <= l2;
    end
    if (reset_now) begin
      wcount <= '0; frame_start <= '0; last_seen <= 0; reading <= 0; k <= '0; error <= 0;
      v1 <= 0; v2 <= 0; v3 <= 0; final_head <= '0; final_tail <= '0;
    end else begin
      if (ce) begin v1 <= issue; v2 <= v1; v3 <= v2; end
      if (take) begin
        wcount <= wcount + 1'b1;
        if (s_last) begin
          last_seen <= 1;
          if (wcount + 1'b1 < 24'(N)) error <= 1;
        end
      end
      // Start a frame when its finality is known; record the flag for the FFT output.
      if (!reading && have_frame && next_known) begin
        reading <= 1; k <= '0; frame_final <= final_frame;
        final_fifo[final_tail] <= final_frame; final_tail <= final_tail + 1'b1;
      end
      if (issue) begin
        k <= k + 1'b1;
        if (k == LOG2N'(N-1)) begin reading <= 0; frame_start <= frame_start + 24'(HOP); end
      end
      // The transaction ends once no frame is left: restart for the next one.
      if (done || reading && issue && k == LOG2N'(N-1) && frame_final) begin
        wcount <= '0; frame_start <= '0; last_seen <= 0;
      end
      if (f_valid && m_ready && f_last) final_head <= final_head + 1'b1;
      if (f_error || f_valid && f_inverse) error <= 1;
    end
  end
endmodule
