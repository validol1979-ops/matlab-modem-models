// Positive and deliberately broken transfers through the shared protocol checker.
`timescale 1ns/1ps
module axis_contract_tb;
  parameter bit RESET_ACTIVE = 1;
  logic clk = 0, rst = RESET_ACTIVE;
  logic valid = 0, ready = 0, last = 0;
  logic [7:0] data = 0;
  int fault;
  always #5 clk = !clk;
  axis_check #(.WIDTH(8), .RESET_ACTIVE(RESET_ACTIVE), .NAME("contract")) checker_inst
    (.clk(clk), .rst(rst), .valid(valid), .ready(ready), .last(last), .data(data));
  initial begin
    if (!$value$plusargs("FAULT=%d", fault)) fault = 0;
    repeat (3) @(negedge clk);
    rst = !RESET_ACTIVE;
    valid = 1; data = 8'h5a; last = 1;
    repeat (3) @(negedge clk);
    case (fault)
      1: valid = 0;
      2: data = 8'ha5;
      3: last = 0;
      4: valid = 1'bx;
      5: ready = 1'bx;
      6: last = 1'bx;
      7: data = 8'hxx;
      default: ready = 1;
    endcase
    @(negedge clk);
    if (fault != 0) $fatal(1, "[MISSED_FAULT] checker accepted fault %0d", fault);
    // Accept a different beat immediately after the held beat's handshake.
    data = 8'h31; last = 0;
    @(negedge clk);
    valid = 0; ready = 0;
    @(negedge clk);
    // Reset may cancel a pending beat; the next transfer has different data.
    valid = 1; data = 8'h42;
    @(negedge clk);
    rst = RESET_ACTIVE; valid = 0; data = 8'hxx;
    repeat (2) @(negedge clk);
    rst = !RESET_ACTIVE; valid = 1; ready = 1; data = 8'h99; last = 1;
    @(negedge clk);
    valid = 0;
    @(negedge clk);
    $display("PASS AXIS CONTRACT reset=%0d", RESET_ACTIVE);
    $finish;
  end
  initial begin #2000; $fatal(1, "[TIMEOUT] axis contract"); end
endmodule
