`timescale 1ns/1ps
module sat_group_tb;
  parameter bit RESET_ACTIVE=1;
  parameter int OUT_WIDTH=34;
  parameter int RANGE_STYLE=0;
  logic clk=0,rst=RESET_ACTIVE,scoring=0,done=0;
  logic valid [0:5];
  logic signed [127:0] rounded [0:5];
  localparam logic signed [127:0] HIGH=RANGE_STYLE==1 ? 128'sd65536 : (128'sd1<<(OUT_WIDTH-1))-1;
  localparam logic signed [127:0] LOW=RANGE_STYLE==1 ? 128'sd3277 : RANGE_STYLE==2 ? -HIGH : -(128'sd1<<(OUT_WIDTH-1));
  always #5 clk=!clk;
  sat_group_check #(.VALUES(6),.FIELDS(2),.RAW_WIDTH(128),.OUT_WIDTH(OUT_WIDTH),
    .RESET_ACTIVE(RESET_ACTIVE),.LOW_BOUND(LOW),.HIGH_BOUND(HIGH),.NAME("group_unit"),.EXPECTED_FILE("expected.txt")) observer
    (.clk(clk),.rst(rst),.scoring(scoring),.done(done),.valid(valid),.rounded(rounded));
  initial begin
    for(int i=0;i<6;i++) begin valid[i]=0;rounded[i]='x;end
    repeat(3) @(negedge clk);rst=!RESET_ACTIVE;
    valid[0]=1;rounded[0]=128'sd1<<100;
    repeat(3) @(negedge clk);rst=RESET_ACTIVE;valid[0]=0;
    repeat(2) @(negedge clk);rst=!RESET_ACTIVE;scoring=1;
    repeat(2) @(negedge clk);
    valid[0]=1;valid[1]=1;rounded[0]=HIGH;rounded[1]=LOW;
    @(negedge clk);
    valid[2]=1;valid[3]=1;rounded[0]=HIGH+1;rounded[1]=LOW-1;
    rounded[2]=128'sd1<<100;rounded[3]=-(128'sd1<<100);
    if($test$plusargs("INJECT_SAT_X")) rounded[2]='x;
    if($test$plusargs("INJECT_ENABLE_X")) valid[2]='x;
    @(negedge clk);
    for(int i=0;i<6;i++) begin valid[i]=0;rounded[i]='x;end
    repeat(3) @(negedge clk);
    valid[4]=1;rounded[4]=LOW;
    @(negedge clk);valid[4]=0;valid[5]=1;rounded[5]=HIGH;
    @(negedge clk);valid[5]=0;done=1;
    repeat(4) @(negedge clk);
    $display("PASS SAT GROUP UNIT");$finish;
  end
  initial begin #2000;$fatal(1,"[TIMEOUT] grouped saturation checker unit");end
endmodule
