// Normalised reciprocal of a positive energy (bit-exact with beam_fixed.reciprocal): with Z =
// 22 + bit length of E, R = divide(2^Z, E) (nearest-even, fxp_divide_seq), 2^22 <= R <= 2^23,
// and a result x/E is formed as round(x*R, Z - 15) for Q15 output. start takes E; done pulses
// with r and shift = Z - 15 about WIDTH + 28 clocks later. zero is set instead when E = 0.
module norm_reciprocal #(
  parameter int WIDTH = 40,
  parameter bit RESET_ACTIVE = 1,
  parameter int SHIFT_WIDTH = $clog2(WIDTH + 23) > 7 ? $clog2(WIDTH + 23) : 7
)(
  input logic clk, rst, start,
  input logic [WIDTH-1:0] energy,
  output logic done, zero,
  output logic [23:0] r,
  output logic [SHIFT_WIDTH-1:0] shift
);
  localparam int NW = WIDTH + 25;              // 2^Z with Z <= 22 + WIDTH, plus the sign
  wire reset_now = rst == RESET_ACTIVE;
  logic [SHIFT_WIDTH-1:0] z;
  logic div_start, waiting;
  logic [WIDTH-1:0] denominator;
  wire div_busy, div_done;
  wire signed [NW-1:0] div_result;
  fxp_divide_seq #(.NUM_WIDTH(NW),.DEN_WIDTH(WIDTH),.RESET_ACTIVE(RESET_ACTIVE)) divider(
    .clk(clk),.rst(rst),.start(div_start),.numerator(NW'(1) <<< z),.denominator(denominator),
    .busy(div_busy),.done(div_done),.result(div_result));
  always_ff @(posedge clk) begin
    if (reset_now) begin done <= 0; zero <= 0; div_start <= 0; waiting <= 0; end
    else begin
      done <= 0; div_start <= 0;
      // A start while a division is running is ignored (the caller waits for done).
      if (start && !div_busy) begin
        zero <= energy == '0; denominator <= energy;
        z <= SHIFT_WIDTH'(22);
        for (int b = 0; b < WIDTH; b++) if (energy[b]) z <= SHIFT_WIDTH'(23 + b);
        if (energy != '0) begin div_start <= 1; waiting <= 1; end
      end
      if (waiting && div_done) begin
        waiting <= 0; done <= 1; r <= div_result[23:0]; shift <= z - SHIFT_WIDTH'(15);
        // 2^22 <= R <= 2^23: any upper quotient bit would be a divider fault.
        if (div_result[NW-1:24] != '0) zero <= 1;
      end
    end
  end
endmodule
