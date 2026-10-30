`timescale 1ns/1ps
module sat_event_tb;
  parameter bit RESET_ACTIVE=1;
  parameter int OUT_WIDTH=18;
  logic clk=0,rst=RESET_ACTIVE,scoring=0,sample_valid=0,done=0;
  logic signed [71:0] rounded [0:1];
  localparam logic signed [71:0] HIGH=(72'sd1<<(OUT_WIDTH-1))-1;
  localparam logic signed [71:0] LOW=-(72'sd1<<(OUT_WIDTH-1));
  always #5 clk=!clk;
  sat_event_check #(.FIELDS(2),.RAW_WIDTH(72),.OUT_WIDTH(OUT_WIDTH),.RESET_ACTIVE(RESET_ACTIVE),
                     .NAME("unit"),.EXPECTED_FILE("expected.txt")) checker_inst
    (.clk(clk),.rst(rst),.scoring(scoring),.sample_valid(sample_valid),.done(done),.rounded(rounded));
  initial begin
    rounded[0]=0;rounded[1]=0;
    repeat(3) @(negedge clk);rst=!RESET_ACTIVE;
    // Warm-up and paused arithmetic must not count as real scored evaluations.
    sample_valid=1;rounded[0]=72'sd1<<69;rounded[1]=-(72'sd1<<69);
    repeat(3) @(negedge clk);rst=RESET_ACTIVE;sample_valid=0;
    repeat(2) @(negedge clk);rst=!RESET_ACTIVE;scoring=1;
    repeat(2) @(negedge clk);
    sample_valid=1;rounded[0]=HIGH;rounded[1]=LOW;
    @(negedge clk);rounded[0]=HIGH+1;rounded[1]=LOW-1;
    @(negedge clk);rounded[0]=72'sd1<<65;rounded[1]=-(72'sd1<<65);
    if ($test$plusargs("INJECT_SAT_X")) rounded[0]='x;
    @(negedge clk);sample_valid=0;
    repeat(3) @(negedge clk);
    sample_valid=1;rounded[0]=0;rounded[1]=0;
    @(negedge clk);rounded[0]=LOW;rounded[1]=HIGH;
    @(negedge clk);sample_valid=0;done=1;
    repeat(4) @(negedge clk);
    $display("PASS SAT EVENT UNIT");$finish;
  end
  initial begin #2000;$fatal(1,"[TIMEOUT] saturation checker unit");end
endmodule
