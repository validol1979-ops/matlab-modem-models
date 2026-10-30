// Stream protocol checker for testbenches (not synthesised): while valid is high and ready low,
// valid must stay high and data/last must stay unchanged; valid, ready and last are never X
// outside reset; data must be known while valid. Any violation is fatal ([PROTOCOL]).
// Bind one instance per data/configuration stream, bundling all payload sidebands.
module axis_check #(parameter int WIDTH = 36, parameter bit RESET_ACTIVE = 1, parameter string NAME = "stream")(
  input logic clk, rst,
  input logic valid, ready, last,
  input logic [WIDTH-1:0] data
);
  logic held;
  logic [WIDTH-1:0] held_data;
  logic held_last;
  always @(posedge clk) begin
    if (rst == RESET_ACTIVE) held <= 0;
    else begin
      if ($isunknown(valid) || $isunknown(ready) || valid && $isunknown(last))
        $fatal(1, "[PROTOCOL] %s: X on valid/ready/last", NAME);
      if (valid && $isunknown(data))
        $fatal(1, "[PROTOCOL] %s: X on data", NAME);
      if (held) begin
        if (!valid) $fatal(1, "[PROTOCOL] %s: valid dropped before ready", NAME);
        if (data !== held_data || last !== held_last) $fatal(1, "[PROTOCOL] %s: data changed while stalled", NAME);
      end
      held <= valid && !ready; held_data <= data; held_last <= last;
    end
  end
endmodule
