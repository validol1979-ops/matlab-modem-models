// Actual pin handshakes and read-only FIFO observations. No fixed model is used.
`timescale 1ns/1ps
module mmse3_rate_tb;
  parameter bit RESET_ACTIVE=1, BACKPRESSURE=0;
  parameter int PROFILE=0, LENGTH=3072, FRAMES=32;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  logic cfg_valid=0,cfg_last=0,cfg_ready,configured,error;
  logic signed [17:0] cfg_re=0,cfg_im=0;
  logic [33:0] cfg_lambda=0;
  logic s_valid=0,s_last=0,s_ready;
  logic signed [17:0] s_re=0,s_im=0;
  logic m_valid,m_last,m_ready=1;
  logic signed [17:0] m_re,m_im;
  mmse3 #(.RESET_ACTIVE(RESET_ACTIVE)) dut
    (.clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_last(cfg_last),.cfg_re(cfg_re),.cfg_im(cfg_im),
     .cfg_lambda(cfg_lambda),.cfg_ready(cfg_ready),.configured(configured),.error(error),
     .s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_ready(s_ready),
     .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(m_ready));
  axis_check #(.WIDTH(70),.RESET_ACTIVE(RESET_ACTIVE),.NAME("MMSE3 rate cfg")) check_cfg
    (.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(cfg_last),.data({cfg_re,cfg_im,cfg_lambda}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("MMSE3 rate input")) check_s
    (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("MMSE3 rate output")) check_m
    (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}));
  longint cycle=0;
  int fd,accepted_cfg=0,accepted_in=0,accepted_out=0,input_frames=0,output_frames=0;
  string trace;
  bit finished=0;
  always @(posedge clk) begin
    cycle++;
    // Edge1 precedes the first reset update and contains uninitialised DUT registers.
    // Trace begins at edge2 and retains four actual reset edges, then every edge.
    if(cycle>1&&!finished) begin
      if($isunknown({rst,cfg_valid,cfg_ready,configured,error,s_valid,s_ready,m_valid,m_ready,
                     dut.index,dut.fifo_count,dut.pending,dut.p_valid,dut.e_valid,dut.frame_active,dut.count,dut.cstate}))
        $fatal(1,"[RATE] unknown active controls");
      $fdisplay(fd,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",cycle,rst,
        cfg_valid,cfg_ready,(cfg_valid?cfg_last:1'b0),(cfg_valid?int'(cfg_re):0),(cfg_valid?int'(cfg_im):0),(cfg_valid?cfg_lambda:34'd0),
        configured,error,s_valid,s_ready,(s_valid?s_last:1'b0),(s_valid?int'(s_re):0),(s_valid?int'(s_im):0),
        m_valid,m_ready,(m_valid?m_last:1'b0),(m_valid?int'(m_re):0),(m_valid?int'(m_im):0),
        int'(dut.fifo_count),int'(dut.pending),int'(dut.index),dut.p_valid,dut.e_valid,dut.frame_active,int'(dut.count),int'(dut.cstate),$size(dut.fifo));
      if(rst!=RESET_ACTIVE) begin
        if(error)$fatal(1,"[RATE] unexpected DUT error");
        if(cfg_valid&&cfg_ready)accepted_cfg++;
        if(s_valid&&s_ready) begin accepted_in++;if(s_last)input_frames++;end
        if(m_valid&&m_ready) begin accepted_out++;if(m_last)output_frames++;end
        if(int'(dut.fifo_count)+3*int'(dut.pending)>$size(dut.fifo))$fatal(1,"[RATE] FIFO reservation overflow");
      end else if(configured||error||m_valid||s_ready||cfg_ready||dut.fifo_count||dut.pending||dut.index||dut.p_valid||dut.e_valid)
        $fatal(1,"[RATE] reset fence");
    end
  end
  always @(negedge clk)m_ready=!BACKPRESSURE||(cycle%8)<5;
  task automatic offer_cfg(input int index);
    @(negedge clk);
    cfg_valid=1;cfg_last=index==8;cfg_re=0;cfg_im=0;
    if(PROFILE==0)begin if(index==0||index==4||index==8)cfg_re=18'sd32768;end
    else begin
      // Unitary H=[[0,0,j],[1,0,0],[0,-1,0]], so W=H^H exactly.
      if(index==2)cfg_im=18'sd32768;
      if(index==3)cfg_re=18'sd32768;
      if(index==7)cfg_re=-18'sd32768;
    end
    for(int guard=0;guard<200000;guard++) begin
      @(posedge clk);if(cfg_ready)return;
    end
    $fatal(1,"[RATE] configuration timeout");
  endtask
  initial begin
    if(PROFILE<0||PROFILE>1||LENGTH<12||LENGTH%3!=0||FRAMES<8||FRAMES*LENGTH>131071)
      $fatal(1,"[RATE] invalid rate parameters");
    if(!$value$plusargs("TRACE=%s",trace))$fatal(1,"[RATE] TRACE required");
    fd=$fopen(trace,"w");if(!fd)$fatal(1,"[RATE] cannot open trace");
    $fdisplay(fd,"cycle,rst,cfg_valid,cfg_ready,cfg_last,cfg_re,cfg_im,cfg_lambda,configured,error,s_valid,s_ready,s_last,s_re,s_im,m_valid,m_ready,m_last,m_re,m_im,fifo,pending,index,p_valid,e_valid,frame_active,cfg_count,cstate,capacity");
    repeat(5)@(negedge clk);rst=!RESET_ACTIVE;
    for(int j=0;j<9;j++)offer_cfg(j);
    @(negedge clk);cfg_valid=0;cfg_last=0;
    for(int guard=0;guard<200000&&!configured&&!error;guard++)@(negedge clk);
    if(!configured||error)$fatal(1,"[RATE] configuration did not complete");
    for(int frame=0;frame<FRAMES;frame++) begin
      for(int sample=0;sample<LENGTH;sample++) begin
        int serial;
        @(negedge clk);serial=frame*LENGTH+sample;
        s_valid=1;s_re=18'(serial);s_im=18'(-serial);s_last=sample==LENGTH-1;
        for(int guard=0;guard<200000;guard++) begin
          @(posedge clk);if(s_ready)break;
          if(guard==199999)$fatal(1,"[RATE] input timeout");
        end
      end
    end
    @(negedge clk);s_valid=0;s_last=0;
    for(int guard=0;guard<200000&&accepted_out<FRAMES*LENGTH;guard++)@(negedge clk);
    repeat(20)@(negedge clk);
    if(accepted_cfg!=9||accepted_in!=FRAMES*LENGTH||accepted_out!=FRAMES*LENGTH||input_frames!=FRAMES||output_frames!=FRAMES||error)
      $fatal(1,"[RATE] incomplete cfg%0d/in%0d/out%0d frames%0d/%0d",accepted_cfg,accepted_in,accepted_out,input_frames,output_frames);
    finished=1;$fclose(fd);
    $display("PASS MMSE3 RATES: %0d cfg, %0d inputs, %0d outputs, %0d frames",accepted_cfg,accepted_in,accepted_out,FRAMES);
    $finish;
  end
  initial begin #50000000;$fatal(1,"[RATE] global timeout");end
endmodule
