// Streaming radix-2 SDF FFT (rtl/common/fft_r2sdf.sv) against the integer model
// (tools/fft_cases.py vectors): frames of N=2^LOG2N samples in, natural-order frames
// out, every re/im/inverse/last bit-exact (in.txt drives, out.txt scores).
// +STALL_INPUT adds random input gaps before offering a transfer (never while awaiting ready), +STALL_OUTPUT random m_ready (~2/3 high),
// +INJECT_MISMATCH corrupts the first expected output re (negative control, [NUMERIC]),
// +BAD_LAST drives s_last one sample early on the first frame only and requires the
// sticky error flag (prints PASS FFT BAD_LAST, does not score the data). Without
// +STALL_*, without file gaps and without +BAD_LAST every sample must be accepted at
// the first posedge, otherwise [THROUGHPUT]. +MID_RESET drives half of the first frame,
// resets the DUT in the middle of it and requires it to come back silent (no output valid,
// no error) before the whole stream is driven again from the start (nothing is scored
// during that warm-up phase). +OUT_RESET is the same block, but the warm-up drives the
// WHOLE first transaction and the reset lands as soon as the DUT has delivered at least
// one accepted output (otherwise [TIMEOUT] no output before OUT_RESET).
`timescale 1ns/1ps
module fft_tb;
 parameter integer LOG2N=6;
 parameter integer IN_WIDTH=18;
 parameter integer WIDTH=20;
 parameter bit RESET_ACTIVE=1;
 parameter string TWIDDLE_FILE="rtl/common/mem/fft_twiddle_64.mem";
 localparam integer N=1<<LOG2N;
 logic clk=0,rst=RESET_ACTIVE;
 always #5 clk=!clk;
 string directory;
 integer fd,ofd,rc,stall_in,stall_out,inject,bad_last;
 logic s_valid=0,s_last=0,s_inverse=0,s_ready;
 logic signed [IN_WIDTH-1:0] s_re=0,s_im=0;
 logic m_valid,m_last,m_inverse,m_ready=1;
 logic signed [WIDTH-1:0] m_re,m_im;
 logic error;
 fft_r2sdf #(.LOG2N(LOG2N),.IN_WIDTH(IN_WIDTH),.WIDTH(WIDTH),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) dut
  (.clk(clk),.rst(rst),.s_valid(s_valid),.s_last(s_last),.s_inverse(s_inverse),.s_re(s_re),.s_im(s_im),.s_ready(s_ready),
   .m_valid(m_valid),.m_last(m_last),.m_inverse(m_inverse),.m_re(m_re),.m_im(m_im),.m_ready(m_ready),.error(error));
 axis_check #(.WIDTH(2*WIDTH+1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("fft m")) check_m
  (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im,m_inverse}));
 axis_check #(.WIDTH(2*IN_WIDTH+1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("fft s")) check_s
   (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im,s_inverse}));
 stream_cover #(.FIELDS(2),.FW(WIDTH),.MODES(2),.RESET_ACTIVE(RESET_ACTIVE),.NAME("fft m")) cover_m
  (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}),.mode(int'(m_inverse)));
 int in_re[],in_im[],in_inv[],in_last[],in_gap[],in_total,out_total;
 int checked=0,outputs=0,frames=0,quiet=0,blocked=0;
 bit has_gaps,strict,scoring=1;
 `include "fft_saturation_check.svh"
 `include "fft_bounds_check.svh"
 int mid_reset,out_reset,warm_out=0;
 longint cycle=0;
 always @(posedge clk) cycle<=cycle+1;
 always @(negedge clk) if(stall_out) m_ready<=(($urandom%3)!=0);
 always @(posedge clk) begin
  if(m_valid&&m_ready) begin quiet<=0;outputs<=outputs+1;end
  else quiet<=quiet+1;
 end
 // Scoreboard: every accepted output must equal fft_fixed.transform exactly.
 always @(posedge clk) if(rst!=RESET_ACTIVE) begin
  if(scoring&&m_valid&&m_ready&&!bad_last) begin
   integer re,im,inv,last;
   rc=$fscanf(ofd,"%d %d %d %d",re,im,inv,last);
   if(inject&&checked==0) re=re+1;
   if(m_re!==WIDTH'(re)||m_im!==WIDTH'(im)||m_inverse!==1'(inv)||m_last!==1'(last)) begin
    $display("MISMATCH output %0d: %0d,%0d/%0d,%0d inverse %0d/%0d last %0d/%0d",
     checked,m_re,m_im,re,im,m_inverse,inv,m_last,last);
    $fatal(1,"[NUMERIC] fft output");
   end
   checked=checked+1;
  end
  if(scoring&&m_valid&&m_ready&&m_last) frames=frames+1;
 end
 // +OUT_RESET: count the accepted outputs delivered while nothing is scored yet.
 always @(posedge clk) if(!scoring&&m_valid&&m_ready) warm_out=warm_out+1;
 // Driver: gap idle clocks, then hold the sample until s_ready on a posedge.
 task automatic drive_sample(input int re,input int im,input int inv,input int last,
                             input int gap,input bit oneshot);
  if(stall_in&&(($urandom%8)==0)) gap=gap+1+($urandom%4); // extra random input gaps
  // Inputs change only on a negedge (no race with the DUT's posedge sampling).
  if(gap>0) begin
   @(negedge clk);s_valid=0;
   repeat(gap) @(negedge clk);
  end else @(negedge clk);
  s_valid=1;s_re=IN_WIDTH'(re);s_im=IN_WIDTH'(im);s_inverse=1'(inv);s_last=1'(last);
  @(posedge clk);
  if(s_valid&&s_ready) return;
  if(oneshot) begin
   $display("Input sample waited for s_ready at cycle %0d",cycle);
   $fatal(1,"[THROUGHPUT] input not accepted at the first posedge");
  end
  for(blocked=1;blocked<8*N+400;blocked=blocked+1) begin
   @(posedge clk);
   if(s_valid&&s_ready) return;
  end
  $fatal(1,"[THROUGHPUT] input sample never accepted (cycle %0d)",cycle);
 endtask
 initial begin
  int re,im,inv,last,gap,l,n0;
  if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
  stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
  inject=$test$plusargs("INJECT_MISMATCH");bad_last=$test$plusargs("BAD_LAST");
  mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
  fd=$fopen({directory,"/in.txt"},"r");
  rc=$fscanf(fd,"%d",in_total);
  in_re=new[in_total];in_im=new[in_total];in_inv=new[in_total];in_last=new[in_total];in_gap=new[in_total];
  for(int j=0;j<in_total;j=j+1) begin
   rc=$fscanf(fd,"%d %d %d %d %d",re,im,inv,last,gap);
   in_re[j]=re;in_im[j]=im;in_inv[j]=inv;in_last[j]=last;in_gap[j]=gap;
   if(gap>0) has_gaps=1;
  end
  $fclose(fd);
  ofd=$fopen({directory,"/out.txt"},"r");
  rc=$fscanf(ofd,"%d",out_total);
  strict=!stall_in&&!stall_out&&!has_gaps&&!bad_last;
  repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
  if(mid_reset||out_reset) begin
   scoring=0;
   n0=in_total;
   for(int j=0;j<in_total;j=j+1) if(in_last[j]) begin n0=j+1;break; end
   if(out_reset) begin
    // the WHOLE first transaction (with its real last flag), then wait for the first accepted output
    for(int j=0;j<n0;j=j+1) drive_sample(in_re[j],in_im[j],in_inv[j],in_last[j],in_gap[j],0);
    @(negedge clk);s_valid=0;s_last=0;s_inverse=0;
    for(int t=0;warm_out==0&&t<200000;t=t+1) @(negedge clk);
    if(warm_out==0) $fatal(1,"[TIMEOUT] no output before OUT_RESET");
   end else begin
    // half of the first transaction (n0 = its length = index of the first in_last plus one), never its last sample
    for(int j=0;j<((n0/2>0)?n0/2:1)&&j<n0-1;j=j+1) drive_sample(in_re[j],in_im[j],in_inv[j],0,in_gap[j],0);
   end
   @(negedge clk);s_valid=0;s_last=0;s_inverse=0;rst=RESET_ACTIVE;
   repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
   @(negedge clk);
   if(m_valid!==1'b0) $fatal(1,"[RESET] output valid after mid-frame reset");
   if(error!==1'b0) $fatal(1,"[RESET] error after mid-frame reset");
   repeat(2) @(negedge clk);
   scoring=1;
  end
  for(int j=0;j<in_total;j=j+1) begin
   l=in_last[j];
   if(bad_last&&j==N-2) l=1;
   else if(bad_last&&j==N-1) l=0;
   drive_sample(in_re[j],in_im[j],in_inv[j],l,in_gap[j],strict&&in_gap[j]==0);
  end
  @(negedge clk);s_valid=0;s_last=0;s_inverse=0;
  if(bad_last) begin
   // The frame lengths were illegal: the data is not scored, only the sticky error.
   wait(outputs>0);
   @(negedge clk);
   while(quiet<=8*N+200) @(negedge clk);
   if(error!==1'b1) $fatal(1,"[NUMERIC] BAD_LAST: error did not assert");
   $display("PASS FFT BAD_LAST: %0d outputs, %0d cycles",outputs,cycle);
   $finish;
  end
  wait(checked==out_total);
  repeat(20) @(negedge clk);
  if(error!==1'b0) $fatal(1,"[NUMERIC] error asserted although every frame ended on sample %0d",N);
  check_fft_saturation();
  check_fft_bounds();
  $display("PASS FFT: %0d outputs, %0d frames, %0d cycles",checked,frames,cycle);
  $finish;
 end
 initial begin #60000000;$fatal(1,"FFT testbench did not drain"); end
endmodule
