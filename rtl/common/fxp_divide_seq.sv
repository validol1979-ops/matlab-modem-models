// Sequential restoring divider: signed numerator, positive denominator, exact
// nearest-even quotient (bpsk_fixed.divide). One quotient bit per clock;
// rounding and sign restoration take two more clocks. done pulses for one clock.
// A zero denominator is the caller's error; the result is then undefined.
module fxp_divide_seq #(
  parameter int NUM_WIDTH = 64, DEN_WIDTH = 32,
  parameter bit RESET_ACTIVE = 1'b1
)(
  input logic clk, rst, start,
  input logic signed [NUM_WIDTH-1:0] numerator,
  input logic [DEN_WIDTH-1:0] denominator,
  output logic busy, done,
  output logic signed [NUM_WIDTH-1:0] result
);
  localparam int STEP_WIDTH = $clog2(NUM_WIDTH);
  localparam logic [STEP_WIDTH-1:0] LAST_STEP = STEP_WIDTH'(NUM_WIDTH-1);
  logic negative, finish_round, finish_sign;
  logic [NUM_WIDTH-1:0] bits_left, quotient, rounded;
  logic [DEN_WIDTH-1:0] remainder, divisor;
  logic [STEP_WIDTH-1:0] step;
  wire [DEN_WIDTH:0] trial = {remainder, bits_left[NUM_WIDTH-1]};
  // Invariant remainder < divisor keeps the difference within DEN_WIDTH+1 bits.
  wire [DEN_WIDTH:0] difference = trial - {1'b0, divisor};
  wire subtract = !difference[DEN_WIDTH];
  wire [DEN_WIDTH-1:0] next_rem = subtract ? difference[DEN_WIDTH-1:0] : trial[DEN_WIDTH-1:0];
  wire round_up = {remainder, 1'b0} > {1'b0, divisor} || ({remainder, 1'b0} == {1'b0, divisor} && quotient[0]);
  always_ff @(posedge clk) begin
    if (rst == RESET_ACTIVE) begin busy <= 1'b0; done <= 1'b0; end
    else begin
      done <= 1'b0;
      if (start && !busy) begin
        busy <= 1'b1; negative <= numerator < 0;
        bits_left <= numerator < 0 ? $unsigned(-numerator) : $unsigned(numerator);
        quotient <= '0; remainder <= '0; divisor <= denominator; step <= '0;
        finish_round <= 1'b0; finish_sign <= 1'b0;
      end else if (busy) begin
        if (!finish_round && !finish_sign) begin
          bits_left <= {bits_left[NUM_WIDTH-2:0], 1'b0}; remainder <= next_rem;
          quotient <= {quotient[NUM_WIDTH-2:0], subtract}; step <= step + 1'b1;
          if (step == LAST_STEP) finish_round <= 1'b1;
        end else if (finish_round) begin
          rounded <= quotient + {{(NUM_WIDTH-1){1'b0}}, round_up}; finish_round <= 1'b0; finish_sign <= 1'b1;
        end else begin
          busy <= 1'b0; done <= 1'b1; result <= negative ? -$signed(rounded) : $signed(rounded);
        end
      end
    end
  end
endmodule
