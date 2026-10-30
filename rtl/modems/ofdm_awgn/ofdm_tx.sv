// OFDM transmitter frame back end (bit-exact reference common/python/ofdm_fixed.py
// transmit(): ifft(s)*sqrt(n) with a cyclic prefix). A frame is N Q15 symbols in and N+CP
// Q15 samples out: wave[N-CP..N-1], then wave[0..N-1].
// Prescale: y = round(s*K, SHIFT_TX) = s/sqrt(N) (K = 46341 for odd LOG2N, 32768 for even,
// SHIFT_TX = 15 + (LOG2N+1)/2) in three registers (operand, product, rounded value) that
// share the enable ce = !y_valid || fft s_ready. The unhalved inverse of fft_r2sdf
// (s_inverse = 1) then gives ifft(s)*sqrt(N) directly; it is saturated to 18 bits.
// Prefix buffer: two banks of N words in one sync_ram. The FFT output index i goes to
// {wbank, i} (the FFT stalls while that bank is full); a full bank is read at indices
// N-CP..N-1, 0..N-1 into a 4-entry output FIFO (m_ready backpressure) and freed after its
// last read. Steady state: the output takes N+CP clocks per frame, the input N.
// Latency (m_ready = 1): about 3 + (N-1+4*LOG2N) + N + 3 core clocks + N + 2 clocks from a
// frame's first symbol to its first output sample.
// error is sticky: s_last not on the N-th symbol of a frame (the frame still ends after N
// symbols), the core error, or core frame flags that disagree with the buffer.
module ofdm_tx #(
  parameter int LOG2N = 5,
  parameter int CP = 8,
  parameter bit RESET_ACTIVE = 1,
  parameter TWIDDLE_FILE = "rtl/common/mem/fft_twiddle_32.mem"
)(
  input logic clk, rst,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  localparam int N = 1 << LOG2N;
  localparam int FRAME = N + CP;
  localparam int K = (LOG2N % 2) != 0 ? 46341 : 32768;
  localparam int SHIFT_TX = 15 + (LOG2N + 1)/2;
  localparam logic signed [36:0] RND = 37'sd1 <<< (SHIFT_TX - 1);
  localparam logic signed [17:0] K_MUL = 18'(K);
  wire reset_now = rst == RESET_ACTIVE;

  // Saturate the 20-bit inverse output to 18 bits (sign-extension check).
  function automatic logic signed [17:0] sat18(input logic signed [19:0] value);
    if (value[19:17] != {3{value[19]}}) return value[19] ? 18'sh20000 : 18'sd131071;
    return value[17:0];
  endfunction

  // Prescale pipeline and input frame counter.
  logic [LOG2N-1:0] in_count;
  logic signed [17:0] a_re, a_im;
  logic signed [35:0] p_re, p_im;
  logic signed [17:0] y_re, y_im;
  logic a_valid, a_last, p_valid, p_last, y_valid, y_last;
  logic f_ready, f_valid, f_last, f_inverse, f_error;
  logic signed [19:0] f_re, f_im;
  wire ce = !y_valid || f_ready;
  assign s_ready = ce && !reset_now;
  wire take = s_valid && s_ready;

  // Prefix buffer: write side.
  logic wbank, rbank;
  logic [1:0] full;
  logic [LOG2N-1:0] widx;
  wire f_take_ready = !full[wbank];
  wire write = f_valid && f_take_ready;

  fft_r2sdf #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) fft(
    .clk(clk),.rst(rst),.s_valid(y_valid),.s_last(y_last),.s_inverse(1'b1),.s_re(y_re),.s_im(y_im),.s_ready(f_ready),
    .m_valid(f_valid),.m_last(f_last),.m_inverse(f_inverse),.m_re(f_re),.m_im(f_im),.m_ready(f_take_ready),.error(f_error));
  // Read side: position 0..N+CP-1 of the output frame and its buffer index.
  logic [LOG2N:0] rpos;
  logic [LOG2N-1:0] ridx;
  generate
    if (CP == 0) begin : g_no_cp
      assign ridx = rpos[LOG2N-1:0];
    end else begin : g_cp
      assign ridx = rpos < (LOG2N+1)'(CP) ? LOG2N'(rpos + (LOG2N+1)'(N-CP)) : LOG2N'(rpos - (LOG2N+1)'(CP));
    end
  endgenerate
  logic inflight, inflight_last;
  logic [37:0] fifo [0:3];
  logic [1:0] fifo_head, fifo_tail;
  logic [2:0] fifo_count;
  wire [35:0] ram_q;
  wire read_issue = full[rbank] && ({1'b0,fifo_count} + {3'd0,inflight}) < 4'd4;
  wire pop = m_valid && m_ready;
  sync_ram #(.WIDTH(36),.ADDR_WIDTH(LOG2N+1)) prefix(
    .clk(clk),.wr_en(write),.rd_en(read_issue),.wr_addr({wbank,widx}),.rd_addr({rbank,ridx}),
    .wr_data({sat18(f_re),sat18(f_im)}),.rd_data(ram_q));

  assign m_valid = fifo_count != 3'd0;
  assign m_re = fifo[fifo_head][37:20];
  assign m_im = fifo[fifo_head][19:2];
  assign m_last = fifo[fifo_head][1];

  always_ff @(posedge clk) begin
    if (ce) begin
      a_re <= s_re; a_im <= s_im; a_last <= in_count == LOG2N'(N-1);
      p_re <= a_re*K_MUL; p_im <= a_im*K_MUL; p_last <= a_last;
      y_re <= 18'((37'(p_re) + RND) >>> SHIFT_TX); y_im <= 18'((37'(p_im) + RND) >>> SHIFT_TX); y_last <= p_last;
    end
    if (reset_now) begin
      in_count <= '0; a_valid <= 0; p_valid <= 0; y_valid <= 0; error <= 0;
      wbank <= 0; rbank <= 0; full <= '0; widx <= '0; rpos <= '0; inflight <= 0;
      fifo_head <= '0; fifo_tail <= '0; fifo_count <= '0;
    end else begin
      if (ce) begin a_valid <= take; p_valid <= a_valid; y_valid <= p_valid; end
      if (take) begin
        in_count <= in_count + 1'b1;
        if (s_last != (in_count == LOG2N'(N-1))) error <= 1;
      end
      // The core's own frame flags must agree with the buffer (a self-check).
      if (f_error || write && (f_last != (widx == LOG2N'(N-1)) || !f_inverse)) error <= 1;
      if (write) begin
        widx <= widx + 1'b1;
        if (widx == LOG2N'(N-1)) begin full[wbank] <= 1; wbank <= !wbank; end
      end
      inflight <= read_issue;
      if (read_issue) begin
        inflight_last <= rpos == (LOG2N+1)'(FRAME-1);
        if (rpos == (LOG2N+1)'(FRAME-1)) begin rpos <= '0; full[rbank] <= 0; rbank <= !rbank; end
        else rpos <= rpos + 1'b1;
      end
      if (inflight) begin fifo[fifo_tail] <= {ram_q, inflight_last, 1'b0}; fifo_tail <= fifo_tail + 1'b1; end
      if (pop) fifo_head <= fifo_head + 1'b1;
      fifo_count <= fifo_count + {2'd0,inflight} - {2'd0,pop};
    end
  end
endmodule
