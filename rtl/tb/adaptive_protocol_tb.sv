// Independent black-box source agents hold each interface until its handshake.
// No hierarchy/state peeking and no required order between cfg and data offers.
`timescale 1ns/1ps
module adaptive_protocol_tb;
  parameter bit RLS=0,RESET_ACTIVE=1;
  parameter string SCENARIO="mid_frame";
  parameter string RECIP_FILE="rtl/common/mem/lms_reciprocal.mem";
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  logic cfg_valid=0,cfg_ready,configured;
  logic [2:0] cfg_taps=2;
  logic s_valid=0,s_last=0,s_ready;
  logic signed [17:0] s_re=8192,s_im=0,s_dre=4096,s_dim=0;
  logic m_valid,m_last,w_valid,w_last,error;
  logic signed [17:0] m_pre,m_pim,m_ere,m_eim,w_re,w_im;
  logic m_ready=1,w_ready=1;
  int cfg_count=0,input_count=0,output_count=0,weight_count=0,last_weights=0,weight_stalls=0;
  bit frame_open=0;
  if(RLS) begin : g_rls
    rls_filter #(.LOG2N(2),.RESET_ACTIVE(RESET_ACTIVE)) dut(
      .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_taps(cfg_taps),
      .cfg_p0(44'd2684354560),.cfg_lambda(30'd268435456),.cfg_invl(32'd1073741824),
      .cfg_ready(cfg_ready),.configured(configured),.s_valid(s_valid),.s_last(s_last),
      .s_re(s_re),.s_im(s_im),.s_dre(s_dre),.s_dim(s_dim),.s_ready(s_ready),
      .m_valid(m_valid),.m_last(m_last),.m_pre(m_pre),.m_pim(m_pim),.m_ere(m_ere),.m_eim(m_eim),.m_ready(m_ready),
      .w_valid(w_valid),.w_last(w_last),.w_re(w_re),.w_im(w_im),.w_ready(w_ready),.error(error));
  end else begin : g_lms
    lms_filter #(.LOG2N(2),.RESET_ACTIVE(RESET_ACTIVE),.RECIP_FILE(RECIP_FILE)) dut(
      .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_nlms(1'b0),.cfg_taps(cfg_taps),
      .cfg_mu(18'd32768),.cfg_eps(34'd107374182),.cfg_ready(cfg_ready),.configured(configured),
      .s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_dre(s_dre),.s_dim(s_dim),.s_ready(s_ready),
      .m_valid(m_valid),.m_last(m_last),.m_pre(m_pre),.m_pim(m_pim),.m_ere(m_ere),.m_eim(m_eim),.m_ready(m_ready),
      .w_valid(w_valid),.w_last(w_last),.w_re(w_re),.w_im(w_im),.w_ready(w_ready),.error(error));
  end
  axis_check #(.WIDTH(3),.RESET_ACTIVE(RESET_ACTIVE),.NAME("protocol cfg")) cfg_stability
    (.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(1'b0),.data(cfg_taps));
  axis_check #(.WIDTH(72),.RESET_ACTIVE(RESET_ACTIVE),.NAME("protocol data")) data_stability
    (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im,s_dre,s_dim}));
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    if(cfg_valid&&cfg_ready) begin
      if(SCENARIO=="mid_frame"&&frame_open) $fatal(1,"[PROTOCOL] config accepted before transaction weights drained");
      cfg_count++;
    end
    if(s_valid&&s_ready) begin input_count++;frame_open=1;end
    if(m_valid&&m_ready) output_count++;
    if(w_valid&&w_ready) begin weight_count++;if(w_last) begin last_weights++;frame_open=0;end end
    if(w_valid&&!w_ready) weight_stalls++;
  end
  task automatic configure(input int taps);
    bit accepted;
    accepted=0;
    @(negedge clk);cfg_valid=1;cfg_taps=3'(taps);
    for(int wait_cycle=0;wait_cycle<100&&!accepted;wait_cycle++) begin
      @(posedge clk);accepted=cfg_valid&&cfg_ready;
    end
    if(!accepted) $fatal(1,"[PROTOCOL] initial configuration did not complete");
    @(negedge clk);cfg_valid=0;
  endtask
  task automatic sample(input bit last);
    bit accepted;
    accepted=0;
    @(negedge clk);s_valid=1;s_last=last;
    for(int wait_cycle=0;wait_cycle<3000&&!accepted;wait_cycle++) begin
      @(posedge clk);accepted=s_valid&&s_ready;
    end
    if(!accepted) $fatal(1,"[PROTOCOL] data source did not complete");
    @(negedge clk);s_valid=0;
  endtask
  initial begin
    bit cfg_done,data_done;
    int blocked_cycles;
    repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
    configure(2);
    if(SCENARIO=="mid_frame") begin
      sample(0);
      for(int t=0;t<3000&&(output_count<1||!s_ready);t++) @(negedge clk);
      if(output_count<1||!s_ready) $fatal(1,"[PROTOCOL] first nonlast sample did not finish");
      // Pending config is held while the independent data source ends its frame.
      @(negedge clk);cfg_valid=1;cfg_taps=1;s_valid=1;s_last=1;w_ready=0;
      cfg_done=0;data_done=0;blocked_cycles=0;
      for(int t=0;t<3000&&!(cfg_done&&data_done);t++) begin
        @(posedge clk);
        if(cfg_valid&&cfg_ready) cfg_done=1;
        if(s_valid&&s_ready) data_done=1;
        @(negedge clk);
        if(data_done) s_valid=0;
        if(cfg_done) cfg_valid=0;
        if(w_valid&&!w_ready) begin blocked_cycles++;if(blocked_cycles>=5) w_ready=1;end
      end
      if(!cfg_done||!data_done||last_weights!=1||weight_count!=2||weight_stalls<4)
        $fatal(1,"[PROTOCOL] pending config/data or stalled transaction did not complete");
      sample(1);
      for(int t=0;t<3000&&last_weights<2;t++) @(negedge clk);
      if(last_weights!=2||weight_count!=3||output_count!=3||error!==1'b0)
        $fatal(1,"[PROTOCOL] reconfigured transaction failed");
    end else if(SCENARIO=="invalid_boundary") begin
      // A bad cfg offer and a valid data offer are independent. A rejected cfg
      // may delay data, but an accepted sample must not block cfg recovery/loss.
      @(negedge clk);cfg_valid=1;cfg_taps=0;s_valid=1;s_last=1;
      @(posedge clk);cfg_done=cfg_valid&&cfg_ready;data_done=s_valid&&s_ready;
      if(!cfg_done) $fatal(1,"[PROTOCOL] idle bad configuration not accepted");
      @(negedge clk);cfg_valid=0;if(data_done) s_valid=0;
      @(negedge clk);cfg_valid=1;cfg_taps=2;cfg_done=0;
      for(int t=0;t<3000&&!(cfg_done&&data_done&&last_weights==1);t++) begin
        @(posedge clk);
        if(cfg_valid&&cfg_ready) cfg_done=1;
        if(s_valid&&s_ready) data_done=1;
        @(negedge clk);
        if(cfg_done) cfg_valid=0;
        if(data_done) s_valid=0;
      end
      if(!cfg_done||!data_done||last_weights!=1||output_count!=1||weight_count!=2)
        $fatal(1,"[PROTOCOL] accepted data blocked recovery/lost weight dump: cfg=%0d data=%0d outputs=%0d weights=%0d",cfg_done,data_done,output_count,weight_count);
      if(error!==1'b1) $fatal(1,"[PROTOCOL] invalid configuration did not set sticky error");
    end else if(SCENARIO=="valid_boundary") begin
      // This control permits simultaneous acceptance if the core implements it
      // coherently; the probe imposes no arbitrary configuration/data ordering.
      @(negedge clk);cfg_valid=1;cfg_taps=1;s_valid=1;s_last=1;
      cfg_done=0;data_done=0;
      for(int t=0;t<3000&&!(cfg_done&&data_done&&last_weights==1);t++) begin
        @(posedge clk);
        if(cfg_valid&&cfg_ready) cfg_done=1;
        if(s_valid&&s_ready) data_done=1;
        @(negedge clk);if(cfg_done) cfg_valid=0;if(data_done) s_valid=0;
      end
      if(!cfg_done||!data_done||output_count!=1||weight_count!=1||last_weights!=1||error!==1'b0)
        $fatal(1,"[PROTOCOL] valid boundary control failed");
    end else $fatal(1,"Unknown SCENARIO");
    $display("PASS ADAPTIVE PROTOCOL rls=%0d reset=%0d scenario=%s cfg=%0d input=%0d outputs=%0d weights=%0d stalls=%0d",
             RLS,RESET_ACTIVE,SCENARIO,cfg_count,input_count,output_count,weight_count,weight_stalls);
    $finish;
  end
  initial begin #500000;$fatal(1,"[PROTOCOL] probe timed out");end
endmodule
