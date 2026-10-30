`timescale 1ns/1ps
// Прямой численный тест захвата на произвольных отсчётах после FIR.
module bpsk_acquire_tb;
 import uvm_pkg::*;
 `include "uvm_macros.svh"
 parameter bit RESET_ACTIVE=1;
 parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
 parameter integer ORDER=2,AMPLITUDE=16384;
 parameter bit BLOCK_FIT=0;
 // Mirror enum encodings from bpsk_acquire: hierarchical enum-item references
 // trigger a Verilator 5.050 internal error. The live DUT state is still read.
 localparam logic [4:0] FIT_SEND_STATE=5'd7,FIT_WAIT_STATE=5'd8;
 localparam logic [2:0] DIV_WAIT_STATE=3'd1,SCORE_SEND_STATE=3'd1;
 localparam integer BITS=ORDER==64?6:ORDER==16?4:ORDER==8?3:ORDER==4?2:1;
 logic clk=0;always #5 clk=~clk;
 logic rst=RESET_ACTIVE,start=0,we=0;
 logic [14:0] wi=0;
 logic signed [17:0] wr,wm;
 logic [335:0] energies;
 logic [128*BITS-1:0] training;
 wire busy,done,confidence,qv,av;
 wire signed [31:0] delay,frequency,phase,qp;
 wire [24:0] gain;
 wire [63:0] score;
 wire [31:0] qt,at;
 wire signed [17:0] ar,ai;
 bpsk_acquire #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.ORDER(ORDER),.AMPLITUDE(AMPLITUDE),.BLOCK_FIT(BLOCK_FIT)) dut(
  clk,rst,start,energies,training,busy,done,confidence,delay,frequency,phase,gain,score,qv,qp,qt,av,ar,ai,at);
 bpsk_samples #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) samples(clk,rst,we,2'd0,wi,wr,wm,1'b1,qv,2'd0,qp[31:8],15'd1536,qt,av,ar,ai,at);
 integer fd,rc,count,cycles;
 longint signed re,im,label,energy,expected[0:5];
 string directory,scenario="baseline";
 integer reached=0,exact_results=0,divisor_checks=0;
 integer busy_prefix=0,busy_latency=0;
 bit inject;
 // DIV/SCORE/replay overlap FIT in the accelerated core. Check the actual
 // parent state AND the active sub-schedule, with live work in its pipeline.
 function automatic bit target_reached;
  case(scenario)
   "reset_fit":return dut.state==FIT_SEND_STATE&&dut.send_index>=8;
   "reset_div","busy_start":return (dut.state==FIT_SEND_STATE||dut.state==FIT_WAIT_STATE)&&dut.divide_state==DIV_WAIT_STATE&&dut.divider_busy;
   "reset_score":return (dut.state==FIT_SEND_STATE||dut.state==FIT_WAIT_STATE)&&dut.score_state==SCORE_SEND_STATE&&dut.score_index>=2;
   "reset_replay":return (dut.state==FIT_SEND_STATE||dut.state==FIT_WAIT_STATE)&&dut.replay_active&&dut.replay_index>=2&&dut.gain_valid_pipe!=0;
   default:return 0;
  endcase
 endfunction
 task automatic idle_guard(input integer clocks);
  repeat(clocks) begin
   @(negedge clk);
   if(done||busy||qv||av) $fatal(1,"[PROTOCOL] unexpected work/done while idle");
  end
 endtask
 always @(posedge clk) if(rst!=RESET_ACTIVE&&dut.divider_start) begin
  assert(!$isunknown(dut.divider_denominator)&&dut.divider_denominator!=0)
   else $fatal(1,"[DIVISOR] acquire issued zero/unknown denominator");
  divisor_checks++;
 end
 initial begin
  inject=$test$plusargs("INJECT_MISMATCH");
  rc=$value$plusargs("ACQUIRE_SCENARIO=%s",scenario);
  if(scenario!="baseline"&&scenario!="reset_fit"&&scenario!="reset_div"&&scenario!="reset_score"&&scenario!="reset_replay"&&scenario!="busy_start")
   $fatal(1,"[SCENARIO] unknown acquisition scenario");
  if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"[VECTOR] directory missing");
  fd=$fopen({directory,"/acquire_direct.txt"},"r");rc=$fscanf(fd,"%d",count);
  repeat(4) @(negedge clk);rst=!RESET_ACTIVE;
  for(integer j=0;j<count;j=j+1) begin
   for(integer k=0;k<6;k=k+1) rc=$fscanf(fd,"%d",expected[k]);
   for(integer k=0;k<8;k=k+1) begin rc=$fscanf(fd,"%d",energy);energies[k*42+:42]=42'(energy);end
   for(integer k=0;k<128;k=k+1) begin rc=$fscanf(fd,"%d",label);training[k*BITS+:BITS]=BITS'(label);end
   for(integer k=0;k<1536;k=k+1) begin
    @(negedge clk);rc=$fscanf(fd,"%d %d",re,im);we=1;wi=15'(k);wr=18'(re);wm=18'(im);
   end
   @(negedge clk);we=0;
   if(scenario!="baseline") begin
    start=1;@(negedge clk);start=0;cycles=0;
    while(!target_reached()&&cycles<2000) begin
     if(done) $fatal(1,"[COVERAGE] done before target state");
     @(negedge clk);cycles++;
    end
    if(!target_reached()||!busy||done) $fatal(1,"[COVERAGE] target state not reached while busy");
    reached++;
    $display("ACQUIRE TARGET scenario=%s case=%0d state=%0d div=%0d score=%0d replay=%0d",scenario,j,dut.state,dut.divide_state,dut.score_state,dut.replay_active);
    if(scenario=="busy_start") begin
     busy_prefix=cycles+1;
     start=1;@(negedge clk);start=0;
     if(done||!busy) $fatal(1,"[PROTOCOL] busy start cancelled acquisition");
    end else begin
     rst=RESET_ACTIVE;repeat(4) @(negedge clk);rst=!RESET_ACTIVE;
     idle_guard(80);
    end
   end
   // Повторный start сразу на первом доступном фронте после done.
   for(integer repeat_case=0;repeat_case<2;repeat_case=repeat_case+1) begin
   if(scenario!="busy_start"||repeat_case!=0) begin
    start=1;@(negedge clk);start=0;
   end
   cycles=0;
   while(!done&&cycles<2000) begin @(negedge clk);cycles++;end
   if(!done) $fatal(1,"[TIMEOUT] direct acquisition");
   if(64'(delay)!==(expected[0]+64'(inject&&j==0&&repeat_case==0))||64'(frequency)!==expected[1]||64'(phase)!==expected[2]||64'(gain)!==expected[3]||score!==expected[4]||64'(confidence)!==expected[5])
    `uvm_fatal("NUMERIC",$sformatf("direct scenario=%s case=%0d got d=%0d f=%0d p=%0d g=%0d s=%0d c=%0d expected %0d %0d %0d %0d %0d %0d",scenario,j,delay,frequency,phase,gain,score,confidence,expected[0],expected[1],expected[2],expected[3],expected[4],expected[5]))
   exact_results++;
   if(scenario=="busy_start") begin
    if(repeat_case==0) busy_latency=busy_prefix+cycles;
    else begin
     if(cycles!=busy_latency) $fatal(1,"[PROTOCOL] busy start changed completion latency: %0d vs %0d",busy_latency,cycles);
     $display("ACQUIRE BUSY START case=%0d pulsed_latency=%0d clean_latency=%0d",j,busy_latency,cycles);
    end
   end
   $display("PASS DIRECT ACQUISITION case=%0d repeat=%0d A=%0d",j,repeat_case,cycles+1);
   end
   // Longer than an entire acquisition: no queued start or extra done.
   idle_guard(2100);
  end
  if(reached!=(scenario=="baseline"?0:count)||exact_results!=2*count||divisor_checks==0)
   $fatal(1,"[COVERAGE] incomplete acquisition scenario");
  $display("PASS ACQUIRE SCENARIO %s: reached=%0d exact=%0d divisor_checks=%0d",scenario,reached,exact_results,divisor_checks);
  $display("PASS BPSK direct acquisition: %0d exact results",count);$finish;
 end
 initial begin #10000000;$fatal(1,"[TIMEOUT] direct bench");end
endmodule
