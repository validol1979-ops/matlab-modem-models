// Actual pin handshakes and external fixed frame values; no internal timing/state reads.
`timescale 1ns/1ps
module fsk_ldpc_protocol_tb;
  parameter int KIND=0,MODE=0,PAUSE_AFTER=0;
  parameter bit RESET_ACTIVE=1;
  parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
  parameter PHI_FILE="rtl/common/mem/ldpc_phi.mem",INV_FILE="rtl/common/mem/ldpc_inv.mem";
  logic clk=0,rst=RESET_ACTIVE;always #5 clk=!clk;
  longint cfg[0:7],ca[0:15][0:7],cb[0:15][0:7];
  logic cfg_valid=0,cfg_ready,configured,s_valid=0,s_ready,s_last=0,m_valid,m_last,m_ready=1,error;
  logic signed [17:0] sv1=0,sv2=0,mv1,mv2;
  wire [255:0] cfg_data={32'(cfg[0]),32'(cfg[1]),32'(cfg[2]),32'(cfg[3]),32'(cfg[4]),32'(cfg[5]),32'(cfg[6]),32'(cfg[7])};
  if(KIND==0)begin:g_tx
    fsk_tx #(.LOG2M(1),.LOG2NMAX(3),.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(
      .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_last(1'(cfg[0])),.cfg_step(32'(cfg[1])),.cfg_n(4'(cfg[2])),.cfg_ready(cfg_ready),.configured(configured),
      .s_valid(s_valid),.s_last(s_last),.s_label(1'(sv1)),.s_ready(s_ready),.m_valid(m_valid),.m_last(m_last),.m_re(mv1),.m_im(mv2),.m_ready(m_ready),.error(error));
  end else if(KIND==1)begin:g_rx
    logic label;
    fsk_rx #(.LOG2M(1),.LOG2NMAX(3),.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(
      .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_last(1'(cfg[0])),.cfg_step(32'(cfg[1])),.cfg_n(4'(cfg[2])),.cfg_ready(cfg_ready),.configured(configured),
      .s_valid(s_valid),.s_last(s_last),.s_re(sv1),.s_im(sv2),.s_ready(s_ready),.m_valid(m_valid),.m_last(m_last),.m_label(label),.m_ready(m_ready),.error(error));
    assign mv1=18'(label);assign mv2=0;
  end else if(KIND==2)begin:g_gf2
    logic bit_out;
    gf2_encoder #(.LOG2KMAX(2),.LOG2MMAX(1),.RESET_ACTIVE(RESET_ACTIVE)) dut(
      .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_last(1'(cfg[0])),.cfg_bit(1'(cfg[1])),.cfg_m(2'(cfg[2])),.cfg_k(3'(cfg[3])),.cfg_ready(cfg_ready),.configured(configured),
      .s_valid(s_valid),.s_last(s_last),.s_bit(1'(sv1)),.s_ready(s_ready),.m_valid(m_valid),.m_last(m_last),.m_bit(bit_out),.m_ready(m_ready),.error(error));
    assign mv1=18'(bit_out);assign mv2=0;
  end else begin:g_ldpc
    logic bit_out;logic signed [15:0] posterior;
    ldpc_decoder #(.LOG2NMAX(2),.LOG2MMAX(2),.LOG2EMAX(2),.RESET_ACTIVE(RESET_ACTIVE),.PHI_FILE(PHI_FILE),.INV_FILE(INV_FILE)) dut(
      .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_last(1'(cfg[0])),.cfg_bit(1'(cfg[1])),.cfg_m(3'(cfg[2])),.cfg_n(3'(cfg[3])),
      .cfg_mode(2'(cfg[4])),.cfg_iterations(8'(cfg[5])),.cfg_alpha(9'(cfg[6])),.cfg_beta(16'(cfg[7])),.cfg_ready(cfg_ready),.configured(configured),
      .s_valid(s_valid),.s_last(s_last),.s_llr(16'(sv1)),.s_ready(s_ready),.m_valid(m_valid),.m_last(m_last),.m_bit(bit_out),.m_posterior(posterior),.m_ready(m_ready),.error(error));
    assign mv1=18'(bit_out);assign mv2=18'(posterior);
  end
  axis_check #(.WIDTH(256),.RESET_ACTIVE(RESET_ACTIVE),.NAME("configuration")) cc(.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(1'(cfg[0])),.data(cfg_data));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("source")) cs(.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({sv1,sv2}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("sink")) cm(.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({mv1,mv2}));
  int ni,no,na,nb,fd,inputs=0,outputs=0,configs=0,ignored_outputs=0,held_tail_inputs=0,bad_config_inputs=0,bad_words;
  int x1[],x2[],xl[],y1[],y2[],yl[];
  bit checking=1,frame_open=0;
  string path;
  always @(posedge clk)if(rst!=RESET_ACTIVE)begin
    if($isunknown({cfg_valid,cfg_ready,configured,s_valid,s_ready,m_valid,m_ready,error}))$fatal(1,"[PROTOCOL] unknown control");
    if(cfg_valid&&cfg_ready)begin
      if(MODE==4&&frame_open&&!(m_valid&&m_ready&&m_last))$fatal(1,"[PROTOCOL] accepted configuration in paused open frame");
      configs++;
    end
    if(s_valid&&s_ready)begin
      inputs++;frame_open=1;
      if(MODE>=9&&!checking)bad_config_inputs++;
      if(MODE==8&&configs==na+nb&&m_valid&&m_last&&!m_ready)held_tail_inputs++;
    end
    if(m_valid&&m_ready)begin
      if(checking)begin
        if(outputs>=no)$fatal(1,"[PROTOCOL] extra accepted outputs");
        if(mv1!==18'(y1[outputs])||mv2!==18'(y2[outputs])||m_last!==1'(yl[outputs]))
          $fatal(1,"[NUMERIC] output%0d got(%0d,%0d,%0d) want(%0d,%0d,%0d)",outputs,mv1,mv2,m_last,y1[outputs],y2[outputs],yl[outputs]);
        outputs++;
      end else ignored_outputs++;
      if(m_last)frame_open=0;
    end
  end
  task automatic send_word;
    cfg_valid=1;
    for(int guard=0;guard<512;guard++)begin
      @(posedge clk);if(cfg_ready)break;
      if(guard==511)$fatal(1,"[PROTOCOL] config recovery blocked accepted_inputs=%0d ignored_outputs=%0d configured=%0d",inputs,ignored_outputs,configured);
    end
    @(negedge clk);cfg_valid=0;
  endtask
  task automatic configure(input bit use_a,input int first_word,input int stop_word);
    for(int word=first_word;word<stop_word;word++)begin
      @(negedge clk);for(int i=0;i<8;i++)cfg[i]=use_a?ca[word][i]:cb[word][i];send_word();
    end
  endtask
  initial begin
    if(!$value$plusargs("DATA=%s",path))$fatal(1,"[PROTOCOL] DATA required");
    fd=$fopen(path,"r");if(!fd||$fscanf(fd,"%d %d %d %d",na,nb,ni,no)!=4||na<1||nb<1||ni<1||no<1||na>16||nb>16)$fatal(1,"[PROTOCOL] input header");
    for(int word=0;word<na;word++)for(int i=0;i<8;i++)if($fscanf(fd,"%d",ca[word][i])!=1)$fatal(1,"[PROTOCOL] cfgA");
    for(int word=0;word<nb;word++)for(int i=0;i<8;i++)if($fscanf(fd,"%d",cb[word][i])!=1)$fatal(1,"[PROTOCOL] cfgB");
    x1=new[ni];x2=new[ni];xl=new[ni];y1=new[no];y2=new[no];yl=new[no];
    for(int i=0;i<ni;i++)if($fscanf(fd,"%d %d %d",x1[i],x2[i],xl[i])!=3)$fatal(1,"[PROTOCOL] source row");
    for(int i=0;i<no;i++)if($fscanf(fd,"%d %d %d",y1[i],y2[i],yl[i])!=3)$fatal(1,"[PROTOCOL] reference row");
    $fclose(fd);repeat(5)@(negedge clk);rst=!RESET_ACTIVE;
    if(MODE!=0)configure(1,0,na);
    if(MODE==7)configure(0,0,nb-1);
    if(MODE>=9)begin
      // Complete illegal H first; then an independent LLR offer precedes replacement.
      bad_words=MODE==11?9:nb;
      for(int word=0;word<bad_words;word++)begin
        @(negedge clk);for(int i=0;i<8;i++)cfg[i]=cb[word][i];
        if(MODE==11)begin cfg[0]=word==8;cfg[1]=1;cfg[2]=3;cfg[3]=3;cfg[4]=1;cfg[5]=2;cfg[6]=256;cfg[7]=0;end
        else cfg[1]=(MODE==9&&word==0)?1:0;
        send_word();
      end
      if(error!==1'b1)$fatal(1,"[PROTOCOL] illegal row did not raise sticky error");
    end
    if(MODE==1||MODE==6||MODE>=9)checking=0;
    fork
      begin
        if(MODE>=9)repeat(2)@(negedge clk);
        if(MODE==4)wait(inputs==PAUSE_AFTER+1);
        if(MODE==5||MODE==8)begin
          wait(m_valid&&m_last);@(negedge clk);m_ready=0;
          fork configure(0,0,nb);begin repeat(MODE==8?12:8)@(negedge clk);m_ready=1;end join
        end else if(MODE==6)begin
          @(negedge clk);for(int i=0;i<8;i++)cfg[i]=cb[0][i];cfg[0]=1;
          if(KIND<2)cfg[2]=0;else begin cfg[2]=0;cfg[3]=0;end
          send_word();repeat(8)@(negedge clk);configure(0,0,nb);checking=1;
        end else begin configure(0,MODE==7?nb-1:0,nb);checking=1;end
      end
      begin
        for(int i=0;i<ni;i++)begin
          if(MODE==8&&i==PAUSE_AFTER)begin @(negedge clk);s_valid=0;s_last=0;wait(configs==na+nb);end
          @(negedge clk);s_valid=1;sv1=18'(x1[i]);sv2=18'(x2[i]);s_last=1'(xl[i]);
          do @(posedge clk);while(!s_ready);
          if(MODE==4&&i==PAUSE_AFTER)begin @(negedge clk);s_valid=0;repeat(20)@(negedge clk);end
          if(MODE>=9&&i==0)begin @(negedge clk);s_valid=0;wait(configs==na+nb+bad_words);end
        end
        @(negedge clk);s_valid=0;s_last=0;
      end
    join
    for(int guard=0;guard<2048&&outputs<no;guard++)@(negedge clk);
    repeat(20)@(negedge clk);
    if(inputs!=ni||outputs!=no||ignored_outputs!=0||bad_config_inputs!=0||configs!=(MODE==0?nb:MODE>=9?na+nb+bad_words:na+nb+(MODE==6?1:0))||error!==1'(MODE==6||MODE>=9))
      $fatal(1,"[PROTOCOL] incomplete/error inputs%0d outputs%0d ignored%0d cfg%0d error%0d",inputs,outputs,ignored_outputs,configs,error);
    if(MODE==8&&KIND>0&&held_tail_inputs==0)$fatal(1,"[PROTOCOL] new frame was not exercised under old blocked output");
    $display("PASS FSK LDPC PROTOCOL kind=%0d mode=%0d inputs=%0d outputs=%0d cfg=%0d held_tail_inputs=%0d bad_config_inputs=%0d",KIND,MODE,inputs,outputs,configs,held_tail_inputs,bad_config_inputs);$finish;
  end
  initial begin #500000;$fatal(1,"[PROTOCOL] bounded completion timeout inputs%0d outputs%0d ignored%0d cfg%0d",inputs,outputs,ignored_outputs,configs);end
endmodule
