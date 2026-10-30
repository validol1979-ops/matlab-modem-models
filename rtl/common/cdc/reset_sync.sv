module reset_sync #(
  parameter bit RESET_ACTIVE=1'b1
)(
  input logic clk, async_rst,
  output logic rst
);
  // Hold external reset for >=3 clock edges. Assertion reaches the core at its
  // next edge; release waits for two synchronizer stages. Core resets stay sync.
  (* ASYNC_REG="TRUE" *) logic [1:0] synchronizer;
  logic active_reset;
  assign active_reset=async_rst==RESET_ACTIVE;
  always_ff @(posedge clk) synchronizer<={synchronizer[0],active_reset};
  assign rst=RESET_ACTIVE ? (active_reset || synchronizer[1]) : !(active_reset || synchronizer[1]);
endmodule
