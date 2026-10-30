// Configuration admissibility is checked without presenting any input waveform.
// A rejected configuration is sticky; reset must recover to a zero-tap FIR.
`timescale 1ns/1ps
module fir_width_guard_tb;
  parameter int LOG2LANES=2,LOG2TMAX=6,ACC_WIDTH=35;
  parameter bit RESET_ACTIVE=1,EXPECT_REJECT=1;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  logic cfg_valid=0,cfg_last=0,cfg_ready,configured;
  logic signed [17:0] cfg_re=0,cfg_im=0;
  logic s_valid=0,s_last=0,s_ready;
  logic signed [17:0] s_re=0,s_im=0;
  logic m_valid,m_last,m_ready=1,error;
  logic signed [17:0] m_re,m_im;
  fir_runtime #(.LOG2LANES(LOG2LANES),.LOG2TMAX(LOG2TMAX),.RESET_ACTIVE(RESET_ACTIVE),.ACC_WIDTH(ACC_WIDTH)) dut(.*);
  int taps_re[],taps_im[],count,fd,rc;
  string directory;
  task automatic tap(input int re,input int im,input bit final_word);
    @(negedge clk);cfg_valid=1;cfg_last=final_word;cfg_re=18'(re);cfg_im=18'(im);
    for(int guard=0;guard<100;guard++) begin
      @(posedge clk);if(cfg_ready)return;
    end
    $fatal(1,"[WIDTH_GUARD] FIR configuration deadlocked");
  endtask
  task automatic reset_dut;
    @(negedge clk);rst=RESET_ACTIVE;cfg_valid=0;cfg_last=0;s_valid=0;s_last=0;
    repeat(3)@(negedge clk);rst=!RESET_ACTIVE;
    @(negedge clk);
    if(error||configured||m_valid||!cfg_ready)$fatal(1,"[WIDTH_GUARD] reset did not recover");
  endtask
  initial begin
    if(!$value$plusargs("VECTORS=%s",directory))$fatal(1,"[WIDTH_GUARD] missing vectors");
    fd=$fopen({directory,"/cfg.txt"},"r");rc=$fscanf(fd,"%d",count);
    taps_re=new[count];taps_im=new[count];
    for(int j=0;j<count;j++)rc=$fscanf(fd,"%d %d",taps_re[j],taps_im[j]);
    $fclose(fd);reset_dut;
    // Reset halfway through a coefficient sequence must clear its running bounds.
    for(int j=0;j<(count+1)/2;j++)tap(taps_re[j],taps_im[j],0);
    reset_dut;
    for(int attempt=0;attempt<(EXPECT_REJECT?1:2);attempt++) begin
      for(int j=0;j<count;j++)tap(taps_re[j],taps_im[j],j==count-1);
      @(negedge clk);cfg_valid=0;cfg_last=0;
      if(EXPECT_REJECT) begin
        if(!error||configured||s_ready||cfg_ready||m_valid)
          $fatal(1,"[WIDTH_GUARD] unsafe coefficients admitted");
        cfg_valid=1;cfg_last=1;cfg_re=0;cfg_im=0;
        s_valid=1;s_last=1;s_re=18'sh20000;s_im=18'sd131071;
        repeat(8) begin
          @(negedge clk);
          if(!error||configured||s_ready||cfg_ready||m_valid)
            $fatal(1,"[WIDTH_GUARD] rejection is not sticky");
        end
      end else if(error||!configured||!cfg_ready)
        $fatal(1,"[WIDTH_GUARD] safe reconfiguration rejected");
    end
    reset_dut;
    tap(0,0,1);@(negedge clk);cfg_valid=0;cfg_last=0;
    if(error||!configured)$fatal(1,"[WIDTH_GUARD] zero coefficient recovery rejected");
    s_valid=1;s_last=1;s_re=18'sh20000;s_im=18'sd131071;
    @(posedge clk);if(!s_ready)$fatal(1,"[WIDTH_GUARD] recovery input blocked");
    @(negedge clk);s_valid=0;s_last=0;
    for(int guard=0;guard<200&&!m_valid;guard++)@(negedge clk);
    if(!m_valid||m_re!==18'sd0||m_im!==18'sd0||!m_last||error)
      $fatal(1,"[WIDTH_GUARD] recovery output invalid");
    @(posedge clk);repeat(5)@(negedge clk);
    if(m_valid||error)$fatal(1,"[WIDTH_GUARD] recovery did not drain");
    $display("PASS FIR WIDTH GUARD: %0d %0d %0d",ACC_WIDTH,EXPECT_REJECT,count);
    $finish;
  end
  initial begin #2000000;$fatal(1,"[WIDTH_GUARD] timeout");end
endmodule
