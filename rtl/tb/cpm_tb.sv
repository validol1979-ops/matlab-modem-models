// MSK/GMSK RTL against the integer model (tools/cpm_cases.py vectors): cpm_tx samples,
// cpm_rx symbol sums, decisions, frame ends and acquisitions, all bit-exact.
// +STALL_OUTPUT: random m_ready on both outputs. +INJECT_MISMATCH: negative control.
// The receiver input must not wait more than 32 clocks in a row (throughput).
`timescale 1ns/1ps
module cpm_tb;
 parameter bit RESET_ACTIVE=1,GMSK=0;
 parameter integer SYMBOLS=768;
 parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
 logic clk=0,rst=RESET_ACTIVE;
 always #5 clk=!clk;
 string directory;
 integer fd,rc,n,stall,inject;
 // Receiver.
 logic cfg_valid=0,cfg_bit=0,cfg_last=0,cfg_ready,configured,error;
 logic s_valid=0,s_last=0,s_ready;
 logic signed [17:0] s_re=0,s_im=0;
 logic m_valid,m_last,m_bit,m_ready=1,acq_valid;
 logic signed [35:0] m_value;
 logic signed [31:0] acq_delay,acq_frequency,acq_phase;
 cpm_rx #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.GMSK(GMSK)) dut(clk,rst,cfg_valid,cfg_bit,cfg_last,12'(SYMBOLS),cfg_ready,configured,error,
  s_valid,s_last,s_re,s_im,s_ready,m_valid,m_last,m_bit,m_ready,m_value,acq_valid,acq_delay,acq_frequency,acq_phase);
 // Transmitter.
 logic t_valid=0,t_bit=0,t_last=0,t_ready,tm_ready=1,tm_valid,tm_last;
 logic signed [17:0] tm_re,tm_im;
 cpm_tx #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.GMSK(GMSK)) transmitter(clk,rst,t_valid,t_bit,t_last,t_ready,tm_ready,tm_valid,tm_last,tm_re,tm_im);
 integer out_fd,out_total,checked=0,acq_fd,acq_total,acquired=0,tx_fd,tx_total,tx_checked=0,errors=0;
 longint cycle=0;
 always @(posedge clk) cycle<=cycle+1;
 always @(negedge clk) if(stall) begin m_ready<=$urandom%3!=0;tm_ready<=$urandom%3!=0;end
 // Receiver output and acquisition scoreboards.
 always @(posedge clk) if(rst!=RESET_ACTIVE) begin
  if(m_valid&&m_ready) begin
   longint value;integer bit_value,last;
   rc=$fscanf(out_fd,"%d %d %d",value,bit_value,last);
   if(inject&&checked==100) value=value+1;
   if(m_value!==36'(value)||m_bit!==1'(bit_value)||m_last!==1'(last)) begin
    $display("MISMATCH symbol %0d: value %0d/%0d bit %0d/%0d last %0d/%0d",checked,m_value,value,m_bit,bit_value,m_last,last);
    $fatal(1,"[NUMERIC] receiver output");
   end
   checked=checked+1;
  end
  if(acq_valid) begin
   longint delay,frequency,phase;
   rc=$fscanf(acq_fd,"%d %d %d",delay,frequency,phase);
   if(acq_delay!==32'(delay)||acq_frequency!==32'(frequency)||acq_phase!==32'(phase)) begin
    $display("MISMATCH acquisition %0d: delay %0d/%0d frequency %0d/%0d phase %0d/%0d",acquired,acq_delay,delay,acq_frequency,frequency,acq_phase,phase);
    $fatal(1,"[NUMERIC] acquisition");
   end
   acquired=acquired+1;
  end
  if(tm_valid&&tm_ready) begin
   integer re,im,last;
   rc=$fscanf(tx_fd,"%d %d %d",re,im,last);
   if(tm_re!==18'(re)||tm_im!==18'(im)||tm_last!==1'(last)) begin
    $display("MISMATCH tx sample %0d: %0d,%0d/%0d,%0d last %0d/%0d",tx_checked,tm_re,tm_im,re,im,tm_last,last);
    $fatal(1,"[NUMERIC] transmitter output");
   end
   tx_checked=tx_checked+1;
  end
 end
 // +TRACE: times of acquisitions and frame ends.
 always @(posedge clk) if($test$plusargs("TRACE")&&rst!=RESET_ACTIVE) begin
  if(acq_valid) $display("TRACE acquisition at cycle %0d",cycle);
  if(m_valid&&m_ready&&m_last) $display("TRACE frame end at cycle %0d, symbols %0d",cycle,checked);
 end
 // Transmitter driver (independent of the receiver).
 initial begin
  integer bfd,total,bit_value,last;
  wait(rst!=RESET_ACTIVE);
  bfd=$fopen({directory,"/tx_bits.txt"},"r");rc=$fscanf(bfd,"%d",total);
  for(integer j=0;j<total;j=j+1) begin
   rc=$fscanf(bfd,"%d %d",bit_value,last);
   @(negedge clk);t_valid=1;t_bit=1'(bit_value);t_last=1'(last);
   do @(posedge clk); while(!t_ready);
  end
  @(negedge clk);t_valid=0;
 end
 initial begin
  integer pfd,bit_value,blocked,re,im,last;
  stall=$test$plusargs("STALL_OUTPUT");inject=$test$plusargs("INJECT_MISMATCH");
  if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
  out_fd=$fopen({directory,"/rx_out.txt"},"r");rc=$fscanf(out_fd,"%d",out_total);
  acq_fd=$fopen({directory,"/rx_acquire.txt"},"r");rc=$fscanf(acq_fd,"%d",acq_total);
  tx_fd=$fopen({directory,"/tx_out.txt"},"r");rc=$fscanf(tx_fd,"%d",tx_total);
  repeat(5) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
  pfd=$fopen({directory,"/preamble.txt"},"r");rc=$fscanf(pfd,"%d",n);
  for(integer j=0;j<192;j=j+1) begin
   rc=$fscanf(pfd,"%d",bit_value);
   @(negedge clk);cfg_valid=1;cfg_bit=1'(bit_value);cfg_last=j==191;
   do @(posedge clk); while(!cfg_ready);
  end
  @(negedge clk);cfg_valid=0;cfg_last=0;
  @(negedge clk);if(!configured||error) $fatal(1,"Receiver did not accept the configuration");
  fd=$fopen({directory,"/rx_wave.txt"},"r");rc=$fscanf(fd,"%d",n);blocked=0;
  for(integer j=0;j<n;j=j+1) begin
   rc=$fscanf(fd,"%d %d %d",re,im,last);
   @(negedge clk);s_valid=1;s_re=18'(re);s_im=18'(im);s_last=1'(last);
   do begin
    @(posedge clk);
    if(s_ready) break;
    blocked=blocked+1;
    if(!stall&&blocked>32) $fatal(1,"[THROUGHPUT] receiver input stalled beyond 32 clocks");
   end while(1);
   blocked=0;
  end
  @(negedge clk);s_valid=0;
  wait(checked==out_total&&tx_checked==tx_total);repeat(20) @(negedge clk);
  if(acquired!=acq_total||error) $fatal(1,"Incomplete acquisitions or receiver error");
  $display("PASS CPM receiver: %0d symbols, %0d acquisitions, %0d tx samples, %0d cycles",checked,acquired,tx_checked,cycle);
  $finish;
 end
 initial begin #20000000;$fatal(1,"CPM testbench did not drain"); end
endmodule
