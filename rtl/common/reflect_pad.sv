// Reflect padding by N = 2^LOG2N samples on both sides (numpy pad mode 'reflect', as
// omlsa_fixed.pad): a signal x[0..L-1] (s_last on its last sample, L >= N+1) becomes
// x[N], x[N-1], .., x[1], x[0], .., x[L-1], x[L-2], .., x[L-1-N] (m_last on the last).
// The samples live in a ring of 8N words (one sync_ram); the input may run ahead of the read
// index by the ring size minus N+1 (the tail of the signal is read again for the end pad).
// After s_last the input waits until the padded signal has been read; a 4-entry output FIFO
// gives m_ready backpressure. error is sticky: a signal shorter than N+1 samples (it is dropped).
module reflect_pad #(
  parameter int LOG2N = 5,
  parameter bit RESET_ACTIVE = 1
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
  localparam int RW = LOG2N + 3;                // ring address
  wire reset_now = rst == RESET_ACTIVE;
  typedef enum logic [1:0] {PRE, MAIN, POST, DONE} phase_t;
  phase_t phase;
  logic [23:0] wcount, index, length;           // length: L of the current signal
  logic last_seen;
  logic [2:0] fifo_count;
  logic [1:0] inflight;
  logic [36:0] fifo [0:3];
  logic [1:0] fifo_head, fifo_tail;
  logic r_valid, r_last;
  wire [35:0] ram_q;
  // Oldest sample still needed: the main index minus the end pad.
  assign s_ready = !reset_now && !last_seen && wcount < index + 24'(8*N - N - 2);
  wire take = s_valid && s_ready;
  wire available = phase == PRE ? wcount > 24'(N) :
                   phase == MAIN ? wcount > index : phase == POST;
  wire room = {1'b0, fifo_count} + {2'd0, inflight} < 4'd4;
  wire issue = phase != DONE && available && room && !(phase == PRE && last_seen && length < 24'(N + 1));
  wire issue_last = phase == POST && index == length - 24'(N + 1);
  sync_ram #(.WIDTH(36),.ADDR_WIDTH(RW)) ring(
    .clk(clk),.wr_en(take),.rd_en(issue),.wr_addr(RW'(wcount)),.rd_addr(RW'(index)),.wr_data({s_re,s_im}),.rd_data(ram_q));
  assign m_valid = fifo_count != 3'd0;
  assign m_re = fifo[fifo_head][36:19]; assign m_im = fifo[fifo_head][18:1]; assign m_last = fifo[fifo_head][0];
  wire pop = m_valid && m_ready;
  always_ff @(posedge clk) begin
    if (reset_now) begin
      phase <= PRE; wcount <= '0; index <= 24'(N); last_seen <= 0; error <= 0; length <= '0;
      fifo_count <= '0; inflight <= '0; fifo_head <= '0; fifo_tail <= '0; r_valid <= 0;
    end else begin
      if (take) begin
        wcount <= wcount + 1'b1;
        if (s_last) begin last_seen <= 1; length <= wcount + 1'b1; end
      end
      // A too short signal: drop it and restart.
      if (last_seen && length < 24'(N + 1) && phase == PRE) begin
        error <= 1; last_seen <= 0; wcount <= '0; index <= 24'(N);
      end
      r_valid <= issue; r_last <= issue_last;
      inflight <= inflight + {1'b0, issue} - {1'b0, r_valid};
      if (issue) begin
        case (phase)
          PRE: if (index == 24'd1) begin phase <= MAIN; index <= '0; end else index <= index - 1'b1;
          MAIN: if (last_seen && index == length - 1'b1) begin phase <= POST; index <= length - 24'd2; end
                else index <= index + 1'b1;
          POST: if (issue_last) phase <= DONE; else index <= index - 1'b1;
          default: begin end
        endcase
      end
      if (r_valid) begin fifo[fifo_tail] <= {ram_q, r_last}; fifo_tail <= fifo_tail + 1'b1; end
      if (pop) fifo_head <= fifo_head + 1'b1;
      fifo_count <= fifo_count + {2'd0, r_valid} - {2'd0, pop};
      // The padded signal has been read: the next signal starts.
      if (phase == DONE && inflight == '0 && !r_valid) begin phase <= PRE; wcount <= '0; index <= 24'(N); last_seen <= 0; end
    end
  end
endmodule
