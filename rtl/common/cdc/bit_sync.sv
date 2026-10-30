module bit_sync #(
  parameter bit RESET_ACTIVE=1'b1
)(
  input logic clk, rst, async_bit,
  output logic sync_bit
);
  // Only individual control bits; multibit data must use a handshake or FIFO.
  (* ASYNC_REG="TRUE" *) logic first_stage;
  (* ASYNC_REG="TRUE" *) logic second_stage;
  always_ff @(posedge clk) begin
    if (rst==RESET_ACTIVE) begin first_stage<=1'b0; second_stage<=1'b0; end
    else begin first_stage<=async_bit; second_stage<=first_stage; end
  end
  assign sync_bit=second_stage;
endmodule
