// Fibonacci PRBS / additive / self-synchronising scrambler and descrambler.
// Bit 0 of each word is first on the wire. See docs/RTL_PRBS.md.
module prbs_scrambler #(
  parameter int ORDER = 7,
  parameter int WORD_WIDTH = 1,
  parameter bit RESET_ACTIVE = 1'b1
)(
  input  logic clk, rst,
  input  logic cfg_valid,
  output logic cfg_ready,
  input  logic [1:0] cfg_mode, // 0 PRBS, 1 additive, 2 self-sync TX, 3 self-sync RX
  input  logic [ORDER-1:0] cfg_seed,
  input  logic cfg_restart,
  output logic configured, error,
  input  logic s_valid,
  output logic s_ready,
  input  logic [WORD_WIDTH-1:0] s_data,
  input  logic s_last,
  output logic m_valid,
  input  logic m_ready,
  output logic [WORD_WIDTH-1:0] m_data,
  output logic m_last,
  output logic [ORDER-1:0] m_state
);
  localparam int K = ORDER == 7 ? 6 : ORDER == 9 ? 5 : ORDER == 15 ? 14 : 28;
  initial begin
    if (ORDER != 7 && ORDER != 9 && ORDER != 15 && ORDER != 31)
      $fatal(1, "ORDER must be 7, 9, 15 or 31");
    if (WORD_WIDTH < 1 || WORD_WIDTH > 64)
      $fatal(1, "WORD_WIDTH must be 1..64");
  end

  logic [1:0] mode;
  logic restart, frame_open, out_valid;
  logic [ORDER-1:0] state, seed, next_state;
  logic [WORD_WIDTH-1:0] next_data;
  logic feedback;
  wire reset_now = rst == RESET_ACTIVE;
  wire cfg_take = cfg_valid && cfg_ready;
  wire take = s_valid && s_ready;
  assign cfg_ready = !reset_now && !error && !frame_open && !out_valid;
  assign s_ready = !reset_now && !error && configured && !cfg_take && (!out_valid || m_ready);
  assign m_valid = !reset_now && out_valid;

  // A word is the exact composition of WORD_WIDTH binary transitions.
  // All state/intermediate values lie in [0, 2**ORDER-1]; XOR is modulo 2.
  always_comb begin
    next_state = state;
    next_data = '0;
    feedback = 1'b0;
    for (int i = 0; i < WORD_WIDTH; i = i + 1) begin
      if (!mode[1]) begin
        next_data[i] = next_state[0] ^ (mode[0] && s_data[i]);
        feedback = next_state[0] ^ next_state[ORDER-K];
        next_state = {feedback, next_state[ORDER-1:1]};
      end else begin
        next_data[i] = s_data[i] ^ next_state[K-1] ^ next_state[ORDER-1];
        feedback = mode[0] ? s_data[i] : next_data[i];
        next_state = {next_state[ORDER-2:0], feedback};
      end
    end
  end

  always_ff @(posedge clk) begin
    if (reset_now) begin
      configured <= 1'b0;
      error <= 1'b0;
      mode <= '0;
      restart <= 1'b0;
      seed <= '0;
      state <= '0;
      frame_open <= 1'b0;
      out_valid <= 1'b0;
    end else begin
      if (cfg_take) begin
        // PRBS/additive require nonzero seed; self-sync has zero history in Python.
        // Bad configuration locks both inputs until synchronous reset.
        if ((!cfg_mode[1] && cfg_seed == '0) || (cfg_mode[1] && cfg_seed != '0)) begin
          error <= 1'b1;
          configured <= 1'b0;
        end else begin
          configured <= 1'b1;
          mode <= cfg_mode;
          seed <= cfg_seed;
          state <= cfg_seed;
          restart <= cfg_restart;
        end
      end
      if (!out_valid || m_ready) begin
        out_valid <= take;
        if (take) begin
          m_data <= next_data;
          m_last <= s_last;
          m_state <= next_state; // State after this word, before optional restart.
          state <= s_last && restart ? seed : next_state;
          frame_open <= !s_last;
        end
      end
    end
  end
endmodule
