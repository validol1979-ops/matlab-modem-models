// Independent interface probes: legal concurrent configuration/data offers,
// a legal pause inside a multi-pair frame, and rejection of malformed singleton TLAST.
`timescale 1ns/1ps
module mmse_protocol_tb;
  parameter bit RESET_ACTIVE=1;
  parameter int CASE_ID=1;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  logic cfg_valid=0,cfg_last=0,cfg_ready,configured,error;
  logic signed [17:0] cfg_re=0,cfg_im=0;
  logic [33:0] cfg_lambda=0;
  logic s_valid=0,s_last=0,s_ready,m_valid,m_last,m_ready=1;
  logic signed [17:0] s_re=0,s_im=0,m_re,m_im;
  mmse2 #(.RESET_ACTIVE(RESET_ACTIVE)) dut(.*);
  int output_count=0;
  int output_re[0:7],output_im[0:7];
  bit output_last[0:7];
  always @(posedge clk) begin
    if(rst==RESET_ACTIVE) output_count=0;
    else if(m_valid&&m_ready) begin
      if(output_count>=8) $fatal(1,"[PROTOCOL] unexpected extra output");
      output_re[output_count]=int'(m_re);output_im[output_count]=int'(m_im);
      output_last[output_count]=m_last;output_count++;
    end
  end
  task automatic reset_dut;
    @(negedge clk);s_valid=0;cfg_valid=0;rst=RESET_ACTIVE;
    repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
    repeat(2) @(negedge clk);
  endtask
  task automatic cfg_entry(input int index);
    @(negedge clk);cfg_valid=1;cfg_last=index==3;cfg_re=(index==0||index==3)?18'sd32768:18'sd0;
    for(int guard=0;guard<1024;guard++) begin
      @(posedge clk);
      if(cfg_ready) begin @(negedge clk);cfg_valid=0;cfg_last=0;return;end
    end
    $fatal(1,"[PROTOCOL] configuration entry blocked");
  endtask
  task automatic raw_cfg_entry(input int re,im,last);
    @(negedge clk);cfg_valid=1;cfg_re=18'(re);cfg_im=18'(im);cfg_last=1'(last);
    for(int guard=0;guard<1024;guard++) begin
      @(posedge clk);
      if(cfg_ready) begin @(negedge clk);cfg_valid=0;cfg_last=0;return;end
    end
    $fatal(1,"[PROTOCOL] raw configuration word blocked");
  endtask
  task automatic await_configuration;
    for(int guard=0;guard<1024;guard++) begin
      @(negedge clk);
      if(error) $fatal(1,"[PROTOCOL] valid identity configuration failed");
      if(configured) return;
    end
    $fatal(1,"[PROTOCOL] configuration never completed");
  endtask
  task automatic configure_identity;
    for(int index=0;index<4;index++) cfg_entry(index);
    await_configuration;
  endtask
  task automatic data_entry(input int re,im,last);
    @(negedge clk);s_valid=1;s_re=18'(re);s_im=18'(im);s_last=1'(last);
    for(int guard=0;guard<1024;guard++) begin
      @(posedge clk);
      if(s_ready) begin @(negedge clk);s_valid=0;s_last=0;return;end
    end
    $fatal(1,"[PROTOCOL] data input blocked");
  endtask
  task automatic await_outputs(input int expected);
    for(int guard=0;guard<1024;guard++) begin
      @(negedge clk);
      if(output_count==expected) return;
    end
    $fatal(1,"[PROTOCOL] outputs did not drain");
  endtask
  task automatic reject_extra_cfg(input bit last_on_extra);
    reset_dut;
    for(int index=0;index<4;index++) raw_cfg_entry((index==0||index==3)?16384:0,0,0);
    if(configured||error||dut.count!=4) $fatal(1,"[PROTOCOL] incomplete four-word config state");
    raw_cfg_entry(11111,22222,int'(last_on_extra));
    repeat(2) @(negedge clk);
    $display("PROBE extra_cfg last=%0d count=%0d error=%0d configured=%0d cfg_ready=%0d s_ready=%0d",
             last_on_extra,dut.count,error,configured,cfg_ready,s_ready);
    if(!error||configured||dut.count!=4||cfg_ready||s_ready)
      $fatal(1,"[PROTOCOL] first excess configuration word was not rejected/saturated");
    if(dut.hr[0]!=16384||dut.hr[1]!=0||dut.hr[2]!=0||dut.hr[3]!=16384
       ||dut.hi[0]!=0||dut.hi[1]!=0||dut.hi[2]!=0||dut.hi[3]!=0)
      $fatal(1,"[PROTOCOL] excess configuration word changed H");
    @(negedge clk);cfg_valid=1;cfg_re=32768;cfg_last=1;s_valid=1;s_re=1;s_im=0;s_last=1;
    repeat(32) begin
      @(negedge clk);
      if(!error||configured||cfg_ready||s_ready||m_valid||output_count||dut.count!=4)
        $fatal(1,"[PROTOCOL] malformed configuration admitted continuation/data");
    end
    reset_dut;
  endtask
  initial begin
    reset_dut;configure_identity;
    if(CASE_ID==1) begin
      bit cfg_accepted,data_accepted;
      // Both interfaces may offer a transfer while no input frame is open.
      @(negedge clk);cfg_valid=1;cfg_re=32768;cfg_last=0;
      s_valid=1;s_re=1;s_im=0;s_last=0;
      @(posedge clk);cfg_accepted=cfg_ready;data_accepted=s_ready;
      #1;
      $display("PROBE concurrent cfg_take=%0d data_take=%0d configured=%0d second=%0d cfg_ready=%0d s_ready=%0d",
               cfg_accepted,data_accepted,configured,dut.second,cfg_ready,s_ready);
      if(cfg_accepted&&data_accepted) begin
        @(negedge clk);cfg_valid=0;s_valid=0;
        repeat(20) @(negedge clk);
        $display("PROBE concurrent after20 configured=%0d second=%0d cfg_ready=%0d s_ready=%0d",
                 configured,dut.second,cfg_ready,s_ready);
        $fatal(1,"[PROTOCOL] concurrent acceptance stranded the partial pair/configuration");
      end
      if(!cfg_accepted||data_accepted) $fatal(1,"[PROTOCOL] expected configuration priority at idle boundary");
      // The unaccepted first observation remains valid and stable until ready returns.
      @(negedge clk);cfg_valid=0;
      fork
        begin
          for(int index=1;index<4;index++) cfg_entry(index);
          await_configuration;
        end
        begin
          do @(posedge clk);while(!s_ready);
          @(negedge clk);s_valid=0;
          data_entry(0,1,1);
        end
      join
      await_outputs(2);
      if(output_re[0]!=1||output_im[0]!=0||output_re[1]!=0||output_im[1]!=1||!output_last[1])
        $fatal(1,"[PROTOCOL] held observations did not survive configuration priority");
    end else if(CASE_ID==2) begin
      bit offered_inside,offered_before_drain;
      data_entry(1,0,0);data_entry(0,1,0);await_outputs(2);
      repeat(5) @(negedge clk);
      $display("PROBE open_frame after_pair cfg_ready=%0d second=%0d pending=%0d fifo=%0d",
               cfg_ready,dut.second,dut.pending,dut.fifo_count);
      offered_inside=cfg_ready;
      m_ready=0;
      data_entry(2,0,0);data_entry(0,2,1);
      for(int guard=0;guard<1024&&!m_valid;guard++) @(negedge clk);
      if(!m_valid) $fatal(1,"[PROTOCOL] final pair did not reach stalled output");
      repeat(5) @(negedge clk);
      $display("PROBE ended_frame with_output cfg_ready=%0d pending=%0d fifo=%0d",
               cfg_ready,dut.pending,dut.fifo_count);
      offered_before_drain=cfg_ready;
      m_ready=1;await_outputs(4);
      repeat(2) @(negedge clk);
      if(!cfg_ready||error||!output_last[3]) $fatal(1,"[PROTOCOL] final TLAST did not release configuration boundary");
      if(offered_inside||offered_before_drain)
        $fatal(1,"[PROTOCOL] configuration admitted inside frame or before output drain");
    end else if(CASE_ID==3) begin
      // This deliberately violates the documented pair/TLAST contract.
      data_entry(1,0,1);
      repeat(2) @(negedge clk);
      $display("PROBE singleton error=%0d configured=%0d second=%0d s_ready=%0d",error,configured,dut.second,s_ready);
      if(!error) $fatal(1,"[PROTOCOL] malformed singleton TLAST was not detected");
      if(s_ready) begin
        data_entry(0,1,0);await_outputs(2);
        $display("PROBE singleton accepted continuation; output_count=%0d",output_count);
        $fatal(1,"[PROTOCOL] malformed singleton still admitted continuation/outputs");
      end
      if(configured||dut.second||cfg_ready) $fatal(1,"[PROTOCOL] malformed pair not aborted until reset");
      @(negedge clk);s_valid=1;s_re=0;s_im=1;s_last=1;
      repeat(32) begin
        @(negedge clk);
        if(s_ready||m_valid||output_count) $fatal(1,"[PROTOCOL] rejected partial pair produced output");
      end
      reset_dut;configure_identity;
      data_entry(1,0,0);data_entry(0,1,1);await_outputs(2);
      if(error||!output_last[1]) $fatal(1,"[PROTOCOL] reset did not recover from malformed TLAST");
    end else if(CASE_ID==4) begin
      reject_extra_cfg(0);reject_extra_cfg(1);
      configure_identity;
      data_entry(1,0,0);data_entry(0,1,1);await_outputs(2);
      if(error||!output_last[1]) $fatal(1,"[PROTOCOL] reset did not recover from excess config");
    end else if(CASE_ID==5) begin
      // Reproduction only: a missing last permits the legacy three-bit count to wrap.
      for(int word=1;word<=12;word++) begin
        raw_cfg_entry((word%4==1||word%4==0)?32768:0,0,word==12);
        if(word==8) $display("PROBE wrap12 after8 count=%0d error=%0d",dut.count,error);
      end
      await_configuration;
      $display("PROBE wrap12 configured=%0d error=%0d count=%0d",configured,error,dut.count);
      $fatal(1,"[PROTOCOL] twelve-word invalid configuration was accepted");
    end else $fatal(1,"Unknown CASE_ID");
    $display("PASS MMSE PROTOCOL case=%0d reset=%0d",CASE_ID,RESET_ACTIVE);
    $finish;
  end
  initial begin #200000;$fatal(1,"[PROTOCOL] probe timeout");end
endmodule
