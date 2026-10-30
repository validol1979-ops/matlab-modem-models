`timescale 1ns/1ps
// fxp_divide_seq (64/52 bits) and fxp_mrc2 against mrc_fixed vectors: weights or
// error per configuration, exact outputs under random input gaps and output stalls,
// sticky saturation, full throughput without stalls, no samples before configuration.
module mrc_blocks_tb;
 import uvm_pkg::*;
 `include "uvm_macros.svh"
 parameter bit RESET_ACTIVE=1;
 logic clk=0;always #5 clk=~clk;
 logic rst=RESET_ACTIVE;
 bit inject=0;
 string directory;
 integer fd,rc,random_state=4242,checked_divide=0,checked_samples=0,configs=0,stalls=0;
 // Divider
 logic div_start=0;
 logic signed [63:0] div_n=0,div_q;
 logic [51:0] div_d=1;
 wire div_busy,div_done;
 fxp_divide_seq #(.NUM_WIDTH(64),.DEN_WIDTH(52),.RESET_ACTIVE(RESET_ACTIVE)) divider(clk,rst,div_start,div_n,div_d,div_busy,div_done,div_q);
 // Combiner
 logic cv=0,sv=0,sl=0,mr=1,stall_mode=0,gap_mode=0;
 logic signed [17:0] gar=0,gai=0,gbr=0,gbi=0,ar=0,ai=0,br=0,bi=0;
 logic [15:0] va=1,vb=1;
 wire cr,configured,error,saturated,sr,mv,ml;
 wire signed [17:0] mre,mim;
 fxp_mrc2 #(.RESET_ACTIVE(RESET_ACTIVE)) dut(clk,rst,cv,gar,gai,gbr,gbi,va,vb,cr,configured,error,saturated,sv,sl,ar,ai,br,bi,sr,mv,ml,mr,mre,mim,1'b1);
 longint signed expected[$];
 always @(negedge clk) if(stall_mode) begin random_state=random_state*1664525+1013904223;mr=(random_state&3)!=0;end
 always @(posedge clk) if(rst!=RESET_ACTIVE&&mv&&mr) begin
  longint signed er,ei,el;
  if(expected.size()<3) `uvm_fatal("NUMERIC","Unexpected combiner output")
  er=expected.pop_front();ei=expected.pop_front();el=expected.pop_front();
  if(64'(mre)!==er+longint'(inject&&checked_samples==100)||64'(mim)!==ei||64'(ml)!==el)
   `uvm_fatal("NUMERIC",$sformatf("sample=%0d got %0d %0d last=%0d expected %0d %0d last=%0d",checked_samples,mre,mim,ml,er,ei,el))
  checked_samples=checked_samples+1;
 end
 property output_hold;@(posedge clk) disable iff(rst==RESET_ACTIVE) mv&&!mr |=> mv&&$stable({mre,mim,ml});endproperty
 assert property(output_hold) else `uvm_fatal("STALL","Combiner output changed under backpressure")
 property unconfigured_blocks;@(posedge clk) disable iff(rst==RESET_ACTIVE) !configured |-> !sr;endproperty
 assert property(unconfigured_blocks) else `uvm_fatal("PROTOCOL","Samples accepted without configuration")
 initial begin:tests
  longint signed n,d,q,v[0:12],s[0:6];
  integer total,samples,count;
  if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"Missing VECTORS");
  inject=$test$plusargs("INJECT_MISMATCH");
  repeat(4) @(negedge clk);rst=!RESET_ACTIVE;
  fd=$fopen({directory,"/divide.txt"},"r");rc=$fscanf(fd,"%d",total);
  for(integer j=0;j<total;j=j+1) begin
   rc=$fscanf(fd,"%d %d %d",n,d,q);
   @(negedge clk);div_n=n;div_d=52'(d);div_start=1;@(negedge clk);div_start=0;
   wait(div_done);@(negedge clk);
   if(64'(div_q)!==q+longint'(inject&&j==7)) `uvm_fatal("NUMERIC",$sformatf("divide %0d/%0d got %0d expected %0d",n,d,div_q,q))
   checked_divide=checked_divide+1;
  end
  $fclose(fd);
  $display("PASS MRC divider: %0d exact quotients",checked_divide);
  fd=$fopen({directory,"/mrc.txt"},"r");rc=$fscanf(fd,"%d %d",total,samples);
  for(integer c=0;c<total;c=c+1) begin
   for(integer k=0;k<13;k=k+1) rc=$fscanf(fd,"%d",v[k]);
   wait(cr);@(negedge clk);
   if(c==6) begin
    // Reset during weight computation must leave the combiner unconfigured.
    cv=1;gar=18'(v[0]);gai=18'(v[1]);gbr=18'(v[2]);gbi=18'(v[3]);va=16'(v[4]);vb=16'(v[5]);@(negedge clk);cv=0;
    repeat(50) @(negedge clk);rst=RESET_ACTIVE;repeat(3) @(negedge clk);rst=!RESET_ACTIVE;@(negedge clk);
    if(configured||error||!cr) `uvm_fatal("RESET","Reset did not clear the weight computation")
   end
   cv=1;gar=18'(v[0]);gai=18'(v[1]);gbr=18'(v[2]);gbi=18'(v[3]);va=16'(v[4]);vb=16'(v[5]);
   @(negedge clk);cv=0;
   count=0;while(!configured&&!error) begin @(negedge clk);count=count+1;if(count>400) `uvm_fatal("CONFIG","Weight computation did not finish") end
   if(error!==(v[6]==0)) `uvm_fatal("CONFIG",$sformatf("config %0d error=%0d expected ok=%0d",c,error,v[6]))
   if(v[6]!=0&&(64'(dut.weight[0])!==v[7]||64'(dut.weight[1])!==v[8]||64'(dut.weight[2])!==v[9]||64'(dut.weight[3])!==v[10]))
    `uvm_fatal("NUMERIC",$sformatf("config %0d weights %0d %0d %0d %0d expected %0d %0d %0d %0d",c,dut.weight[0],dut.weight[1],dut.weight[2],dut.weight[3],v[7],v[8],v[9],v[10]))
   // Config 0 checks full throughput; others use random gaps and stalls.
   stall_mode=c!=0;gap_mode=c!=0;if(c==0) mr=1;
   for(integer j=0;j<v[11];j=j+1) begin
    for(integer k=0;k<7;k=k+1) rc=$fscanf(fd,"%d",s[k]);
    expected.push_back(s[5]);expected.push_back(s[6]);expected.push_back(s[4]);
    if(gap_mode) begin random_state=random_state*1664525+1013904223;if((random_state&7)==0) begin sv=0;@(negedge clk);end end
    sv=1;ar=18'(s[0]);ai=18'(s[1]);br=18'(s[2]);bi=18'(s[3]);sl=1'(s[4]);
    do begin @(posedge clk);if(sr) break;stalls=stalls+1;if(c==0) `uvm_fatal("THROUGHPUT","Input stalled without output backpressure") end while(1);
    @(negedge clk);
   end
   sv=0;stall_mode=0;mr=1;wait(expected.size()==0);repeat(3) @(negedge clk);
   if(saturated!==1'(v[12])) `uvm_fatal("NUMERIC",$sformatf("config %0d saturated=%0d expected %0d",c,saturated,v[12]))
   configs=configs+1;
  end
  $fclose(fd);
  if(checked_samples!=samples) `uvm_fatal("NUMERIC","Incomplete combiner coverage")
  $display("PASS MRC combiner: %0d configurations, %0d exact outputs, %0d input stalls",configs,checked_samples,stalls);
  $display("PASS MRC blocks");$finish;
 end
 initial begin #20000000;`uvm_fatal("TIMEOUT","MRC blocks did not finish") end
endmodule
