// Independent interface assertions and an external fixed numeric trace, no hierarchy.
`timescale 1ns/1ps
module costas_protocol_tb;
  parameter bit RESET_ACTIVE=1;
  parameter int MODE=0;
  parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
  logic clk=0,rst=RESET_ACTIVE;always #5 clk=!clk;
  logic cfg_valid=0,cfg_ready,configured;
  logic [31:0] cfg_k1=0,cfg_k2=0,gain_a1,gain_a2,gain_b1,gain_b2;
  logic s_valid=0,s_ready,s_last=0,m_valid,m_ready=1,m_last;
  logic signed [17:0] s_re=0,s_im=0,m_re,m_im;
  logic signed [31:0] m_phase;
  int xr[0:9],xi[0:9],yr[0:9],yi[0:9],ph[0:9],lasts[0:9];
  int accepted_inputs=0,accepted_outputs=0,accepted_cfg=0,fd,rc;
  string path;
  costas_loop #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(.*);
  axis_check #(.WIDTH(64),.RESET_ACTIVE(RESET_ACTIVE),.NAME("costas cfg")) cfg_check
    (.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(1'b0),.data({cfg_k1,cfg_k2}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("costas input")) s_check
    (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im}));
  axis_check #(.WIDTH(68),.RESET_ACTIVE(RESET_ACTIVE),.NAME("costas output")) m_check
    (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im,m_phase}));
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    if($isunknown({cfg_valid,cfg_ready,s_valid,s_ready,m_valid,m_ready,configured}))$fatal(1,"[PROTOCOL] unknown controls");
    if(cfg_valid&&cfg_ready) begin
      if(s_valid&&s_ready)$fatal(1,"[PROTOCOL] concurrent configuration/data accepted");
      if(accepted_inputs>0&&accepted_outputs<5&&!(accepted_outputs==4&&m_valid&&m_ready&&m_last))
        $fatal(1,"[PROTOCOL] configuration accepted inside first frame");
      accepted_cfg++;
    end
    if(s_valid&&s_ready)accepted_inputs++;
    if(m_valid&&m_ready) begin
      if(accepted_outputs>=10)$fatal(1,"[PROTOCOL] extra outputs");
      if(m_re!==18'(yr[accepted_outputs])||m_im!==18'(yi[accepted_outputs])||
         m_phase!==32'(ph[accepted_outputs])||m_last!==1'(lasts[accepted_outputs]))
        $fatal(1,"[NUMERIC] output%0d actual(%0d,%0d,%0d,%0d) expected(%0d,%0d,%0d,%0d)",accepted_outputs,m_re,m_im,m_phase,m_last,
          yr[accepted_outputs],yi[accepted_outputs],ph[accepted_outputs],lasts[accepted_outputs]);
      accepted_outputs++;
    end
  end
  task automatic configure(input logic [31:0] a,b);
    @(negedge clk);cfg_k1=a;cfg_k2=b;cfg_valid=1;
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
  endtask
  initial begin
    if(!$value$plusargs("DATA=%s",path))$fatal(1,"[PROTOCOL] DATA required");
    fd=$fopen(path,"r");
    if(!fd||$fscanf(fd,"%d %d %d %d",gain_a1,gain_a2,gain_b1,gain_b2)!=4)$fatal(1,"[PROTOCOL] configuration file");
    for(int i=0;i<10;i++)
      if($fscanf(fd,"%d %d %d %d %d %d",xr[i],xi[i],yr[i],yi[i],ph[i],lasts[i])!=6)$fatal(1,"[PROTOCOL] trace row");
    $fclose(fd);repeat(5)@(negedge clk);rst=!RESET_ACTIVE;
    // MODE1 first sets an intentionally different old gain, then concurrently offers A/data.
    configure(MODE==1?32'd410139166:gain_a1,MODE==1?32'd13671306:gain_a2);
    fork
      begin
        if(MODE<4)begin
        if(MODE==1)configure(gain_a1,gain_a2);
        if(MODE==0)wait(accepted_outputs==1);
        else if(MODE==2)wait(accepted_inputs==4);
        else if(MODE==3)begin
          wait(accepted_outputs==4);@(negedge clk);m_ready=0;
          wait(m_valid&&m_last);
          @(negedge clk);cfg_k1=gain_b1;cfg_k2=gain_b2;cfg_valid=1;
          repeat(3)begin @(negedge clk);if(cfg_ready)$fatal(1,"[PROTOCOL] configuration while final output blocked");end
          m_ready=1;
          do @(posedge clk);while(!cfg_ready);
          @(negedge clk);cfg_valid=0;
        end
        else wait(accepted_inputs==4);
        if(MODE!=3)configure(gain_b1,gain_b2);
        end
      end
      begin
        for(int i=0;i<10;i++)begin
          @(negedge clk);s_valid=1;s_re=18'(xr[i]);s_im=18'(xi[i]);s_last=1'(lasts[i]);
          do @(posedge clk);while(!s_ready);
          // MODE0 makes an actual input pause inside a transaction.
          if(MODE==0&&i==0)begin @(negedge clk);s_valid=0;repeat(15)@(negedge clk);end
          // Sink thread must have time to close ready before the fifth sample arrives.
          if(MODE==3&&i==3)begin @(negedge clk);s_valid=0;wait(accepted_outputs==4);repeat(2)@(negedge clk);end
        end
        @(negedge clk);s_valid=0;s_last=0;
      end
    join
    wait(accepted_outputs==10);repeat(20)@(negedge clk);
    if(accepted_inputs!=10||accepted_outputs!=10||accepted_cfg!=(MODE==1?3:MODE<4?2:1))$fatal(1,"[PROTOCOL] incomplete queues/configuration");
    $display("PASS COSTAS PROTOCOL mode=%0d inputs=%0d outputs=%0d cfg=%0d",MODE,accepted_inputs,accepted_outputs,accepted_cfg);$finish;
  end
  initial begin #200000;$fatal(1,"[PROTOCOL] bounded completion timeout");end
endmodule
