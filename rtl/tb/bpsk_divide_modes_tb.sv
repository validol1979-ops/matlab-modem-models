`timescale 1ns/1ps
// Общие операнды, независимый Python-эталон и точная задержка обоих режимов.
module bpsk_divide_modes_tb;
 import uvm_pkg::*;
 `include "uvm_macros.svh"
 parameter bit RESET_ACTIVE=1;
 logic clk=0;always #5 clk=~clk;
 logic rst=RESET_ACTIVE,start=0;
 logic signed [63:0] numerator;
 logic [31:0] denominator;
 wire [1:0] busy,done;
 wire signed [63:0] result_one,result_two;
 bpsk_divide #(.RESET_ACTIVE(RESET_ACTIVE),.STEPS_PER_CYCLE(1)) one(clk,rst,start,numerator,denominator,busy[0],done[0],result_one);
 bpsk_divide #(.RESET_ACTIVE(RESET_ACTIVE),.STEPS_PER_CYCLE(2)) two(clk,rst,start,numerator,denominator,busy[1],done[1],result_two);
 integer fd,rc,count;
 longint signed n,d,expected;
 string directory,scenario="all";
 integer checked=0,ones=0,maxes=0;
 bit inject;
 integer inject_mode=2;
 initial begin
  inject=$test$plusargs("INJECT_MISMATCH");
  rc=$value$plusargs("INJECT_STEP_MODE=%d",inject_mode);
  if(inject_mode!=1&&inject_mode!=2) $fatal(1,"[SCENARIO] invalid injection mode");
  rc=$value$plusargs("DIVIDE_SCENARIO=%s",scenario);
  if(scenario!="all"&&scenario!="one"&&scenario!="max") $fatal(1,"[SCENARIO] divider scenario");
  if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"[VECTOR] missing directory");
  fd=$fopen({directory,"/divide.txt"},"r");rc=$fscanf(fd,"%d",count);
  repeat(4) @(negedge clk);rst=!RESET_ACTIVE;
  for(integer j=0;j<count;j=j+1) begin
   rc=$fscanf(fd,"%d %d %d",n,d,expected);
   // Zero is outside the bpsk_divide contract; acquire must never issue it.
   if(d<=0||d>64'hffffffff) $fatal(1,"[VECTOR] denominator outside 1..0xffffffff");
   if((scenario=="one"&&d!=1)||(scenario=="max"&&d!=64'hffffffff)) continue;
   if(d==1) ones++;
   if(d==64'hffffffff) maxes++;
   @(negedge clk);numerator=n;denominator=32'(d);start=1;
   if(checked==0) $display("DIVIDE TARGET scenario=%s denominator=%0d modes=1,2",scenario,denominator);
   @(negedge clk);start=0;
   @(negedge clk);
   for(integer age=1;age<=67;age=age+1) begin
    if(done[0] !== (age==66) || done[1] !== (age==34)) $fatal(1,"[DIVIDE] latency age=%0d done=%b",age,done);
    if((done[0]&&result_one!==(expected+64'(inject&&checked==0&&inject_mode==1)))||(done[1]&&result_two!==(expected+64'(inject&&checked==0&&inject_mode==2))))
     `uvm_fatal("NUMERIC",$sformatf("divider scenario=%s row=%0d d=%0d mode=%0d",scenario,j,d,inject_mode))
    @(negedge clk);
   end
   checked++;
  end
  if(checked==0||(scenario!="max"&&ones==0)||(scenario!="one"&&maxes==0)) $fatal(1,"[COVERAGE] missing divider boundaries");
  $display("PASS DIVIDE BOUNDARIES scenario=%s one=%0d max=%0d modes=1,2",scenario,ones,maxes);
  $display("PASS BPSK divider modes: %0d exact results, latency=66/34",checked);$finish;
 end
 initial begin #10000000;$fatal(1,"[TIMEOUT] divider modes");end
endmodule
