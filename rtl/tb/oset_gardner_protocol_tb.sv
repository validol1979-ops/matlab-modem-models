// Pin-only configuration boundaries and an independent external numeric trace.
`timescale 1ns/1ps
module oset_gardner_protocol_tb;
  parameter int KIND=0,MODE=0,OFFSET=400;
  parameter bit RESET_ACTIVE=1;
  parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
  logic clk=0,rst=RESET_ACTIVE;always #5 clk=!clk;
  logic cfg_valid=0,cfg_ready,configured,s_valid=0,s_ready,s_last=0,m_valid,m_ready=1,m_last,error;
  logic signed [17:0] s_re=0,s_im=0,m_re,m_im;
  logic signed [31:0] m_position;
  longint cfg[0:4],ca[0:4],cb[0:4];
  logic [135:0] cfg_data;
  if(KIND==0)begin:g_notch
    notch_iir #(.RESET_ACTIVE(RESET_ACTIVE)) dut(.clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_b1(18'(cfg[0])),.cfg_a1(18'(cfg[1])),.cfg_a2(18'(cfg[2])),
      .cfg_ready(cfg_ready),.configured(configured),.s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_ready(s_ready),
      .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(m_ready));
    assign error=0;assign m_position=0;assign cfg_data={82'd0,18'(cfg[0]),18'(cfg[1]),18'(cfg[2])};
  end else if(KIND==1)begin:g_kalman
    kalman_scalar #(.RESET_ACTIVE(RESET_ACTIVE)) dut(.clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_q(32'(cfg[0])),.cfg_r(32'(cfg[1])),.cfg_p0(32'(cfg[2])),
      .cfg_ready(cfg_ready),.configured(configured),.s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_ready(s_ready),
      .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(m_ready),.error(error));
    assign m_position=0;assign cfg_data={40'd0,32'(cfg[0]),32'(cfg[1]),32'(cfg[2])};
  end else begin:g_gardner
    gardner_timing #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(.clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_sps(8'(cfg[0])),.cfg_count(16'(cfg[1])),
      .cfg_position(48'(cfg[2])),.cfg_k3(32'(cfg[3])),.cfg_k4(32'(cfg[4])),.cfg_ready(cfg_ready),.configured(configured),
      .s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_ready(s_ready),.m_valid(m_valid),.m_last(m_last),
      .m_re(m_re),.m_im(m_im),.m_position(m_position),.m_ready(m_ready),.error(error));
    assign cfg_data={8'(cfg[0]),16'(cfg[1]),48'(cfg[2]),32'(cfg[3]),32'(cfg[4])};
  end
  axis_check #(.WIDTH(136),.RESET_ACTIVE(RESET_ACTIVE),.NAME("cfg boundary")) cc(.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(1'b0),.data(cfg_data));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("data boundary")) cs(.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im}));
  axis_check #(.WIDTH(68),.RESET_ACTIVE(RESET_ACTIVE),.NAME("output boundary")) cm(.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im,m_position}));
  int xr[],xi[],xl[],yr[],yi[],yp[],yl[],ni,no,fd,rc,inputs=0,outputs=0,configs=0,ignored_outputs=0;
  bit checking=1,frame_open=0;
  string path;
  always @(posedge clk)if(rst!=RESET_ACTIVE)begin
    if($isunknown({cfg_valid,cfg_ready,configured,s_valid,s_ready,m_valid,m_ready,error}))$fatal(1,"[PROTOCOL] unknown controls");
    if(cfg_valid&&cfg_ready)begin
      if(frame_open&&MODE==2)$fatal(1,"[PROTOCOL] configuration inside open frame");
      configs++;
    end
    if(s_valid&&s_ready)begin inputs++;frame_open=1;end
    if(m_valid&&m_ready)begin
      if(checking)begin
        if(outputs>=no)$fatal(1,"[PROTOCOL] extra output");
        if(m_re!==18'(yr[outputs])||m_im!==18'(yi[outputs])||m_position!==32'(yp[outputs])||m_last!==1'(yl[outputs]))
          $fatal(1,"[NUMERIC] output%0d got(%0d,%0d,%0d,%0d) want(%0d,%0d,%0d,%0d)",outputs,m_re,m_im,m_position,m_last,yr[outputs],yi[outputs],yp[outputs],yl[outputs]);
        outputs++;
      end else ignored_outputs++;
      if(m_last)frame_open=0;
    end
  end
  task automatic configure(input bit initial_config,input bit invalid_config);
    @(negedge clk);
    for(int i=0;i<5;i++)cfg[i]=initial_config?ca[i]:cb[i];
    if(invalid_config)begin
      if(KIND==2&&MODE==4)cfg[1]=0;
      else cfg[KIND==1?1:0]=KIND==1?0:1;
    end
    cfg_valid=1;
    for(int guard=0;guard<2500;guard++)begin
      @(posedge clk);if(cfg_ready)break;
      if(guard==2499)$fatal(1,"[PROTOCOL] recovery cfg timeout accepted_inputs=%0d ignored_outputs=%0d configured=%0d",inputs,ignored_outputs,configured);
    end
    @(negedge clk);cfg_valid=0;
  endtask
  initial begin
    if(!$value$plusargs("DATA=%s",path))$fatal(1,"[PROTOCOL] DATA required");
    fd=$fopen(path,"r");if(!fd)$fatal(1,"[PROTOCOL] input file");
    for(int i=0;i<5;i++)if($fscanf(fd,"%d",ca[i])!=1)$fatal(1,"[PROTOCOL] cfgA");
    for(int i=0;i<5;i++)if($fscanf(fd,"%d",cb[i])!=1)$fatal(1,"[PROTOCOL] cfgB");
    if($fscanf(fd,"%d %d",ni,no)!=2||ni<1||no<1)$fatal(1,"[PROTOCOL] sizes");
    xr=new[ni];xi=new[ni];xl=new[ni];yr=new[no];yi=new[no];yp=new[no];yl=new[no];
    for(int i=0;i<ni;i++)if($fscanf(fd,"%d %d %d",xr[i],xi[i],xl[i])!=3)$fatal(1,"[PROTOCOL] input row");
    for(int i=0;i<no;i++)if($fscanf(fd,"%d %d %d %d",yr[i],yi[i],yp[i],yl[i])!=4)$fatal(1,"[PROTOCOL] expected row");
    $fclose(fd);repeat(5)@(negedge clk);rst=!RESET_ACTIVE;configure(1,0);
    if(KIND==1)repeat(OFFSET)@(negedge clk);
    if(MODE==1||MODE==4)checking=0;
    fork
      begin
        if(MODE==2)wait(inputs==1);
        configure(0,MODE==1||MODE==4);
        if(MODE==1||MODE==4)begin
          if(configured)$fatal(1,"[PROTOCOL] invalid configuration remained enabled");
          repeat(8)@(negedge clk);configure(0,0);checking=1;
        end
      end
      begin
        if(MODE==3)wait(configs==2);
        for(int i=0;i<ni;i++)begin
          @(negedge clk);s_valid=1;s_re=18'(xr[i]);s_im=18'(xi[i]);s_last=1'(xl[i]);
          do @(posedge clk);while(!s_ready);
          if(MODE==2&&i==0)begin @(negedge clk);s_valid=0;repeat(15)@(negedge clk);end
        end
        @(negedge clk);s_valid=0;s_last=0;
      end
    join
    wait(outputs==no);repeat(20)@(negedge clk);
    if(inputs!=ni||outputs!=no||ignored_outputs!=0||configs!=((MODE==1||MODE==4)?3:2)||error!==1'(MODE==1))
      $fatal(1,"[PROTOCOL] incomplete recovery/counts inputs%0d outputs%0d ignored%0d cfg%0d error%0d",inputs,outputs,ignored_outputs,configs,error);
    $display("PASS CONFIG BOUNDARY kind=%0d mode=%0d inputs=%0d outputs=%0d cfg=%0d",KIND,MODE,inputs,outputs,configs);$finish;
  end
  initial begin #500000;$fatal(1,"[PROTOCOL] bounded completion timeout");end
endmodule
