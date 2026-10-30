// ISTFT: normalised overlap-add synthesis (bit-exact reference stft_fixed.synthesize).
// One transaction is F frames of N spectra (24-bit, X/N in Q19 as stft_analysis produces;
// s_last on the very last bin) and gives (F-1)*HOP + N Q15 samples (m_last on the last).
// N = 2^LOG2N (2..8), HOP = 2^LOG2HOP, R = N/HOP in 1, 2, 4.
// Frame f: the spectra are clamped to +-(2^22-1) and go through the unhalved inverse
// fft_r2sdf (IN_WIDTH 23, WIDTH 24), u = the windowed frame in Q19. Accumulation:
// acc[f*HOP + k] += u_k*W_k exactly (ACC_WIDTH bits, W = Q17 window ROM) in a ring of N entries
// (one sync_ram, read-modify-write over three registers). After the frame, emission: the
// samples t = f*HOP .. f*HOP+HOP-1 (for the final frame all N remaining samples) are read,
// cleared (operands registered before scaling products), scaled by RECIP[t mod HOP][mask] (24-bit ROM, F = 24 - 2*LOG2N fraction bits;
// bit m of mask: frame floor(t/HOP) - m exists) and rounded by 17 + 4 + F bits, saturated
// to 18 bits, into an 8-entry output FIFO (m_ready backpressure). Accumulation and
// emission share the RAM ports, so the FFT output waits during emission: a frame takes
// about N + HOP + 8 clocks (N + N + 8 for the final one).
// After reset the ring is cleared once (N clocks); emission keeps it clear afterwards.
// After a transaction's s_last the input waits until that final frame has been emitted
// (the final-frame index is a single register).
// error is sticky: s_last not on a frame's last bin, or the core error.
module stft_synthesis #(
  parameter int LOG2N = 6,
  parameter int LOG2HOP = 4,
  parameter bit RESET_ACTIVE = 1,
  parameter TWIDDLE_FILE = "rtl/common/mem/fft_twiddle_64.mem",
  parameter WINDOW_FILE = "rtl/common/mem/stft_window_64.mem",
  parameter RECIP_FILE = "rtl/common/mem/stft_recip_64_16.mem",
  parameter int ACC_WIDTH = 41 + LOG2N - LOG2HOP,
  parameter int PRODUCT_WIDTH = 41
)(
  input logic clk, rst,
  input logic s_valid, s_last,
  input logic signed [23:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  localparam int N = 1 << LOG2N;
  localparam int HOP = 1 << LOG2HOP;
  localparam int R = 1 << (LOG2N - LOG2HOP);
  localparam int RECIP_FRAC = 24 - 2*LOG2N;
  localparam int SHIFT = 17 + 4 + RECIP_FRAC;
  localparam int EW = 69 - SHIFT;             // |acc*RECIP| < 2^67, kept from bit SHIFT-1
  localparam int AW = LOG2HOP + R;            // RECIP address {p, mask}
  localparam int CW = ACC_WIDTH;
  // FFT outputs are symmetric +/- (2^23-1), even after inverse conjugation.
  // Any signed18 window gives |u*W| <= 2^40-2^17. At most R terms live in a cell.
  initial if(ACC_WIDTH<41+LOG2N-LOG2HOP || ACC_WIDTH>44 || PRODUCT_WIDTH<41 || PRODUCT_WIDTH>42)
    $fatal(1,"[PARAMETER] ISTFT requires safe accumulator and product widths");
  localparam logic signed [23:0] CLAMP = 24'sd4194303;
  wire reset_now = rst == RESET_ACTIVE;

  function automatic logic signed [22:0] clamp23(input logic signed [23:0] value);
    if (value > CLAMP) return 23'sd4194303;
    if (value < -CLAMP) return 23'sh400001;
    return value[22:0];
  endfunction
  // Round half up by SHIFT and saturate to 18 bits. The product register keeps bits
  // SHIFT-1 and up only (the lower ones never reach the result), so the rounding is
  // (v + 1) >>> 1 of that value: floor((p + 2^(S-1))/2^S) = floor((floor(p/2^(S-1)) + 1)/2).
  function automatic logic signed [17:0] scale(input logic signed [EW-1:0] value);
    logic signed [EW-1:0] rounded;
    rounded = (value + EW'(1)) >>> 1;
    if (rounded[EW-1:17] != {(EW-17){rounded[EW-1]}}) return rounded[EW-1] ? 18'sh20000 : 18'sd131071;
    return rounded[17:0];
  endfunction

  // Input register (clamp) and frame bookkeeping.
  logic signed [22:0] c_re, c_im;
  logic c_valid, c_last, f_ready;
  logic [LOG2N-1:0] k_in;
  logic final_seen;
  logic [15:0] final_frame, input_frame;
  wire in_ce = !c_valid || f_ready;
  assign s_ready = in_ce && !reset_now && !final_seen;
  wire take = s_valid && s_ready;
  wire u_valid, u_last, u_inverse, u_error;
  wire signed [23:0] u_re, u_im;
  logic u_ready;
  fft_r2sdf #(.LOG2N(LOG2N),.IN_WIDTH(23),.WIDTH(24),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) fft(
    .clk(clk),.rst(rst),.s_valid(c_valid),.s_last(c_last),.s_inverse(1'b1),.s_re(c_re),.s_im(c_im),.s_ready(f_ready),
    .m_valid(u_valid),.m_last(u_last),.m_inverse(u_inverse),.m_re(u_re),.m_im(u_im),.m_ready(u_ready),.error(u_error));

  // Scheduler: clear the ring, accumulate a frame, wait for the last write, emit.
  typedef enum logic [1:0] {INIT, ACC, DRAIN, EMIT} state_t;
  state_t state;
  logic [15:0] frame;                 // frame index within the transaction
  logic [LOG2N-1:0] k, base, clear_index;
  logic [2:0] drain;
  logic is_final;
  // Emission position: block i (0..R-1, only 0 unless final), p = 0..HOP-1.
  logic [LOG2N-LOG2HOP:0] block;
  logic [LOG2N-1:0] p;
  logic [2:0] inflight;
  logic [3:0] fifo_count;
  logic [36:0] fifo [0:7];
  logic [2:0] fifo_head, fifo_tail;
  wire pop = m_valid && m_ready;
  wire [LOG2N-LOG2HOP:0] blocks = is_final ? (LOG2N-LOG2HOP+1)'(R) : (LOG2N-LOG2HOP+1)'(1);
  wire emit = state == EMIT && ({1'b0,fifo_count} + {2'd0,inflight}) < 5'd8;
  wire emit_last = block == blocks - 1'b1 && p == LOG2N'(HOP-1);
  assign u_ready = state == ACC;
  wire acc_take = u_valid && u_ready;

  // Accumulation pipeline: a (read issued), b (acc and product), c (write).
  logic a_valid, b_valid;
  logic [LOG2N-1:0] a_addr, b_addr;
  logic signed [23:0] a_re, a_im;
  // With the legacy 42-bit product and a 41-bit accumulator only the duplicate
  // sign bit is unused. The raw-product scoreboard still checks all 42 bits.
  /* verilator lint_off UNUSEDSIGNAL */
  logic signed [PRODUCT_WIDTH-1:0] b_pre, b_pim;
  /* verilator lint_on UNUSEDSIGNAL */
  logic signed [CW-1:0] acc_q_re, acc_q_im;
  wire [17:0] window_q;
  wire [2*CW-1:0] ram_q;
  wire [LOG2N-1:0] acc_addr = base + k;
  // Emission address and mask: t = (frame + block)*HOP + p.
  wire [LOG2N-1:0] emit_addr = base + (LOG2N'(block) << LOG2HOP) + p;
  logic [R-1:0] mask;
  always_comb for (int m = 0; m < R; m++)
    mask[m] = 16'(block) <= 16'(m) && 16'(m) <= frame + 16'(block);
  wire [23:0] recip_q;
  sync_rom #(.WIDTH(18),.ADDR_WIDTH(LOG2N),.INIT_FILE(WINDOW_FILE)) window(
    .clk(clk),.rd_en(acc_take),.rd_addr(k),.rd_data(window_q));
  sync_rom #(.WIDTH(24),.ADDR_WIDTH(AW),.INIT_FILE(RECIP_FILE)) recip(
    .clk(clk),.rd_en(emit),.rd_addr((AW'(p) << R) | AW'(mask)),.rd_data(recip_q));
  wire write_acc = b_valid;
  wire write_clear = state == INIT || emit;
  sync_ram #(.WIDTH(2*CW),.ADDR_WIDTH(LOG2N)) ring(
    .clk(clk),.wr_en(write_acc || write_clear),.rd_en(acc_take || emit),
    .wr_addr(state == INIT ? clear_index : write_acc ? b_addr : emit_addr),
    .rd_addr(acc_take ? acc_addr : emit_addr),
    .wr_data(write_acc ? {acc_q_re + CW'(b_pre), acc_q_im + CW'(b_pim)} : (2*CW)'(0)),.rd_data(ram_q));

  // Emission pipeline: e1 (acc and RECIP read), o (operand registers), e2 (products),
  // e3 (scaled) -> FIFO.
  logic e1_valid, o_valid, e2_valid, e3_valid, e1_last, o_last, e2_last, e3_last;
  logic signed [CW-1:0] o_re, o_im;
  logic signed [24:0] o_recip;
  logic signed [EW-1:0] e2_re, e2_im;
  logic signed [17:0] e3_re, e3_im;
  assign m_valid = fifo_count != 4'd0;
  assign m_re = fifo[fifo_head][36:19];
  assign m_im = fifo[fifo_head][18:1];
  assign m_last = fifo[fifo_head][0];

  always_ff @(posedge clk) begin
    // Datapath registers.
    if (in_ce) begin c_re <= clamp23(s_re); c_im <= clamp23(s_im); c_last <= k_in == LOG2N'(N-1); end
    if (acc_take) begin a_re <= u_re; a_im <= u_im; a_addr <= acc_addr; end
    // Interpret the Q17 window word as signed18, including custom negative windows.
    b_addr <= a_addr; b_pre <= PRODUCT_WIDTH'(a_re*$signed(window_q)); b_pim <= PRODUCT_WIDTH'(a_im*$signed(window_q));
    acc_q_re <= ram_q[2*CW-1:CW]; acc_q_im <= ram_q[CW-1:0];
    e1_last <= emit_last && emit && is_final;
    o_re <= $signed(ram_q[2*CW-1:CW]); o_im <= $signed(ram_q[CW-1:0]); o_recip <= $signed({1'b0, recip_q}); o_last <= e1_last;
    e2_re <= EW'((68'(o_re)*68'(o_recip)) >>> (SHIFT - 1)); e2_im <= EW'((68'(o_im)*68'(o_recip)) >>> (SHIFT - 1)); e2_last <= o_last;
    e3_re <= scale(e2_re); e3_im <= scale(e2_im); e3_last <= e2_last;
    if (reset_now) begin
      c_valid <= 0; k_in <= '0; final_seen <= 0; error <= 0; state <= INIT; clear_index <= '0;
      frame <= '0; k <= '0; base <= '0; drain <= '0; a_valid <= 0; b_valid <= 0;
      e1_valid <= 0; o_valid <= 0; e2_valid <= 0; e3_valid <= 0; inflight <= '0; fifo_count <= '0; fifo_head <= '0; fifo_tail <= '0;
    end else begin
      // Input side: frames of N, the transaction's last frame is the one s_last ends.
      if (in_ce) c_valid <= take;
      if (take) begin
        k_in <= k_in + 1'b1;
        if (s_last && k_in != LOG2N'(N-1)) error <= 1;
      end
      if (u_error || acc_take && !u_inverse) error <= 1;
      // Accumulation pipeline valid bits (the RAM read data and the window are one clock late).
      a_valid <= acc_take; b_valid <= a_valid;
      // Emission pipeline.
      e1_valid <= emit; o_valid <= e1_valid; e2_valid <= o_valid; e3_valid <= e2_valid;
      inflight <= inflight + {2'd0, emit} - {2'd0, e3_valid};
      if (e3_valid) begin fifo[fifo_tail] <= {e3_re, e3_im, e3_last}; fifo_tail <= fifo_tail + 1'b1; end
      if (pop) fifo_head <= fifo_head + 1'b1;
      fifo_count <= fifo_count + {3'd0, e3_valid} - {3'd0, pop};
      case (state)
        INIT: begin clear_index <= clear_index + 1'b1; if (clear_index == LOG2N'(N-1)) state <= ACC; end
        ACC: if (acc_take) begin
          k <= k + 1'b1;
          if (k == LOG2N'(N-1)) begin
            state <= DRAIN; drain <= 3'd3;
            // The final frame of a transaction: its s_last went in before its output came out.
            is_final <= final_seen && frame == final_frame;
            if (u_last != 1'b1) error <= 1;
          end else if (u_last) error <= 1;
        end
        DRAIN: begin drain <= drain - 1'b1; if (drain == 3'd1) begin state <= EMIT; block <= '0; p <= '0; end end
        EMIT: if (emit) begin
          if (emit_last) begin
            if (is_final) begin frame <= '0; base <= '0; final_seen <= 0; end
            else begin frame <= frame + 1'b1; base <= base + LOG2N'(HOP); end
            state <= ACC;
          end else if (p == LOG2N'(HOP-1)) begin p <= '0; block <= block + 1'b1; end
          else p <= p + 1'b1;
        end
        default: state <= INIT;
      endcase
      // s_last marks the final frame (the input runs ahead of the accumulation).
      if (take && s_last) begin final_seen <= 1; final_frame <= input_frame; end
    end
  end
  // Input frame counter (frames of the current input transaction).
  always_ff @(posedge clk)
    if (reset_now) input_frame <= '0;
    else if (take && k_in == LOG2N'(N-1)) input_frame <= s_last ? '0 : input_frame + 1'b1;
endmodule
