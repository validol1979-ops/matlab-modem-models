// Legal concurrent configuration/data offers are held until their own handshakes.
// Independent directed checks: arbitration, open frame, unread FIFO and overflow.
`timescale 1ns/1ps
module fir_protocol_tb;
  parameter bit RESET_ACTIVE=1;
  parameter int SCENARIO=0;
  localparam int LOG2LANES=2,LOG2TMAX=2;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  logic cfg_valid=0,cfg_last=0,cfg_ready,configured;
  logic signed[17:0] cfg_re=0,cfg_im=0;
  logic s_valid=0,s_last=0,s_ready;
  logic signed[17:0] s_re=0,s_im=0;
  logic m_valid,m_last,m_ready=0,error;
  logic signed[17:0] m_re,m_im;
  fir_runtime #(.LOG2LANES(2),.LOG2TMAX(2),.RESET_ACTIVE(RESET_ACTIVE)) dut(.*);
  int cfg_checked=0,in_checked=0,out_checked=0;
  bit scoring=1;
  `include "fir_bounds_check.svh"
  for(genvar bank=0;bank<4;bank++)begin : g_bad_configuration_write
    always @(posedge clk)if(rst!=RESET_ACTIVE&&dut.tap_count>=4)
      if(dut.g_bank[bank].tap_bank.wr_en!==1'b0)
        $fatal(1,"[PROTOCOL] FIR unsupported tap wrote coefficient RAM");
  end
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    if(cfg_valid&&cfg_ready)cfg_checked++;
    if(s_valid&&s_ready)in_checked++;
    if(m_valid&&m_ready)out_checked++;
  end
  task automatic coefficient(input int value,input bit final_word);
    @(negedge clk);cfg_valid=1;cfg_re=18'(value);cfg_im=0;cfg_last=final_word;
    for(int guard=0;guard<100;guard++)begin
      @(posedge clk);if(cfg_ready)return;
    end
    $fatal(1,"[PROTOCOL] FIR configuration deadlocked");
  endtask
  task automatic sample(input int value,input bit final_word);
    @(negedge clk);s_valid=1;s_re=18'(value);s_im=0;s_last=final_word;
    for(int guard=0;guard<100;guard++)begin
      @(posedge clk);if(s_ready)return;
    end
    $fatal(1,"[PROTOCOL] FIR input deadlocked by held configuration offer");
  endtask
  task automatic initial_configuration;
    coefficient(65536,1);
    @(negedge clk);cfg_valid=0;cfg_last=0;
    if(!configured||error)$fatal(1,"[PROTOCOL] FIR valid configuration rejected");
  endtask
  task automatic wait_output;
    for(int guard=0;guard<100&&!m_valid;guard++)@(negedge clk);
    if(!m_valid)$fatal(1,"[PROTOCOL] FIR output failed to arrive");
  endtask
  initial begin
    repeat(5)@(negedge clk);rst=!RESET_ACTIVE;
    initial_configuration;
    case(SCENARIO)
    0:begin
      // Old taps are configured; both first offers are legal at the idle boundary.
      @(negedge clk);cfg_valid=1;cfg_last=0;cfg_re=65536;
      s_valid=1;s_last=1;s_re=32768;
      @(posedge clk);
      if(!cfg_ready||s_ready)begin
        @(negedge clk);cfg_last=1;cfg_re=0;
        repeat(8)@(negedge clk);
        $fatal(1,"[PROTOCOL] FIR concurrent offers deadlocked: cfg_ready%0d configured%0d wcount%0d",cfg_ready,configured,dut.wcount);
      end
      @(negedge clk);cfg_last=1;cfg_re=0;
      @(posedge clk);if(!cfg_ready||s_ready)$fatal(1,"[PROTOCOL] FIR configuration could not complete");
      @(negedge clk);cfg_valid=0;cfg_last=0;
      // The original data offer has remained stable throughout configuration.
      @(posedge clk);if(!s_ready)$fatal(1,"[PROTOCOL] FIR held data offer not accepted after configuration");
      @(negedge clk);s_valid=0;s_last=0;
      wait_output;
      if(m_re!==18'sd16384||m_im!==0||m_last!==0)$fatal(1,"[PROTOCOL] FIR new-tap output0 mismatch");
      m_ready=1;@(posedge clk);@(negedge clk);m_ready=0;
      wait_output;
      if(m_re!==0||m_im!==0||m_last!==1)$fatal(1,"[PROTOCOL] FIR new-tap output1 mismatch");
      m_ready=1;@(posedge clk);@(negedge clk);
      if(cfg_checked!=3||in_checked!=1||out_checked!=2||error)$fatal(1,"[PROTOCOL] FIR arbitration transfer counts");
    end
    1:begin
      sample(32768,1);@(negedge clk);s_valid=0;s_last=0;
      wait_output;repeat(20)@(negedge clk);
      if(!m_valid||cfg_ready)$fatal(1,"[PROTOCOL] FIR configuration ready with unread output");
      cfg_valid=1;cfg_last=1;cfg_re=65536;
      repeat(4)begin @(posedge clk);if(cfg_ready)$fatal(1,"[PROTOCOL] FIR configuration accepted before output drain");end
      @(negedge clk);m_ready=1;
      @(posedge clk);@(negedge clk);
      @(posedge clk);if(!cfg_ready)$fatal(1,"[PROTOCOL] FIR configuration blocked after output drain");
      @(negedge clk);cfg_valid=0;
    end
    2:begin
      sample(32768,0);@(negedge clk);s_valid=0;
      wait_output; m_ready=1;@(posedge clk);@(negedge clk);
      // FIFO empty, but input frame is still open. A held cfg offer must not block it.
      if(cfg_ready)$fatal(1,"[PROTOCOL] FIR configuration ready inside input frame");
      cfg_valid=1;cfg_last=1;cfg_re=65536;
      sample(16384,1);@(negedge clk);s_valid=0;s_last=0;
      for(int guard=0;guard<100&&out_checked<2;guard++)@(negedge clk);
      if(out_checked!=2)$fatal(1,"[PROTOCOL] FIR open frame failed to drain");
      @(posedge clk);@(negedge clk);cfg_valid=0;
      if(in_checked!=2||error)$fatal(1,"[PROTOCOL] FIR open frame transfer counts");
    end
    3:begin
      // Four valid taps with no cfg_last, then the first unsupported fifth tap.
      for(int k=0;k<4;k++)coefficient(65536,0);
      coefficient(65536,0);
      @(negedge clk);cfg_valid=0;
      if(!error||configured||s_ready||cfg_ready||dut.tap_count!=4)
        $fatal(1,"[PROTOCOL] FIR malformed configuration did not stop/saturate");
      repeat(12)@(negedge clk);
      if(!error||configured||dut.tap_count!=4)$fatal(1,"[PROTOCOL] FIR malformed configuration escaped sticky error");
    end
    default:$fatal(1,"[PROTOCOL] unknown FIR probe scenario");
    endcase
    $display("PASS FIR PROTOCOL scenario%0d: cfg%0d input%0d output%0d",SCENARIO,cfg_checked,in_checked,out_checked);
    $finish;
  end
  initial begin #100000;$fatal(1,"[PROTOCOL] FIR probe timeout");end
endmodule
