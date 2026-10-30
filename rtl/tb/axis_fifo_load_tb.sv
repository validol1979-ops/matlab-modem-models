// Deterministic offered-load integration: production RAM FIFO and II8 Costas.
`timescale 1ns/1ps
module axis_fifo_load_tb;
  parameter int DEPTH=16;
  parameter bit RESET_ACTIVE=1;
  parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
  localparam int CW=$clog2(DEPTH+1);
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  logic s_valid=0,s_last=0,s_ready,f_valid,f_last,f_ready,m_valid,m_last,m_ready=0;
  logic [35:0] s_data=0,f_data;
  logic [CW-1:0] level;
  logic cfg_valid=0,cfg_ready,configured;
  logic [31:0] cfg_k1,cfg_k2;
  logic signed [17:0] m_re,m_im;
  logic signed [31:0] m_phase;
  axis_fifo #(.WIDTH(36),.DEPTH(DEPTH),.RESET_ACTIVE(RESET_ACTIVE)) fifo(
    .clk(clk),.rst(rst),.s_valid(s_valid),.s_last(s_last),.s_data(s_data),.s_ready(s_ready),
    .m_valid(f_valid),.m_last(f_last),.m_data(f_data),.m_ready(f_ready),.level(level));
  costas_loop #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) core(
    .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_ready(cfg_ready),.cfg_k1(cfg_k1),.cfg_k2(cfg_k2),.configured(configured),
    .s_valid(f_valid),.s_last(f_last),.s_re($signed(f_data[35:18])),.s_im($signed(f_data[17:0])),.s_ready(f_ready),
    .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_phase(m_phase),.m_ready(m_ready));
  bit inject_hold=0,hold_corrupted=0;
  wire [67:0] checked_output={m_re,m_im,m_phase}^{67'd0,hold_corrupted};
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("load input")) source_check(
    .clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data(s_data));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("load FIFO output")) fifo_check(
    .clk(clk),.rst(rst),.valid(f_valid),.ready(f_ready),.last(f_last),.data(f_data));
  axis_check #(.WIDTH(68),.RESET_ACTIVE(RESET_ACTIVE),.NAME("load Costas output")) output_check(
    .clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data(checked_output));
  string vectors,trace_file;
  int fd,trace_fd,rc,total,horizon,expected_total;
  int arrivals[],ready_mask[],in_re[],in_im[],in_last[],ex_re[],ex_im[],ex_phase[],ex_last[];
  int cycle=-1,sent=0,consumed=0,seen=0,waits=0,peak=0,held_outputs=0,held_fifo=0;
  bit scoring=0,inject_numeric,inject_phase,require_unblocked;
  always @(posedge clk) if(scoring&&rst!=RESET_ACTIVE) begin
    cycle++;
    if(cycle>=horizon) $fatal(1,"[TIMEOUT] load schedule exhausted");
    if(int'(level)!=sent-consumed) $fatal(1,"[CONSERVATION] FIFO level mismatch");
    if(int'(level)>peak) peak=int'(level);
    $fdisplay(trace_fd,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
      cycle,s_valid,s_ready,s_valid?s_last:0,s_valid?$signed(s_data[35:18]):0,s_valid?$signed(s_data[17:0]):0,
      f_valid,f_ready,f_valid?f_last:0,f_valid?$signed(f_data[35:18]):0,f_valid?$signed(f_data[17:0]):0,
      m_valid,m_ready,m_valid?m_last:0,m_valid?m_re:0,m_valid?m_im:0,m_valid?m_phase:0,level,configured);
    if(s_valid&&s_ready) sent++;
    if(s_valid&&!s_ready) begin
      waits++;
      if(require_unblocked) begin
        $display("LOAD CAPACITY TARGET cycle=%0d depth=%0d level=%0d",cycle,DEPTH,level);
        $fatal(1,"[CAPACITY] due word blocked at short depth");
      end
    end
    if(f_valid&&!f_ready) held_fifo++;
    if(f_valid&&f_ready) begin
      if(consumed>=total||f_data!=={18'(in_re[consumed]),18'(in_im[consumed])}||f_last!==1'(in_last[consumed]))
        $fatal(1,"[FIFO_DATA] FIFO transfer changed word/order/TLAST");
      consumed++;
    end
    if(m_valid&&!m_ready) begin
      held_outputs++;
      if(inject_hold&&!hold_corrupted) $display("LOAD HOLD TARGET cycle=%0d valid=1 ready=0",cycle);
    end
    if(m_valid&&m_ready) begin
      if(seen>=total) $fatal(1,"[NUMERIC] extra load output");
      if((inject_numeric||inject_phase)&&seen==0) $display("LOAD OUTPUT TARGET cycle=%0d index=%0d",cycle,seen);
      if(m_re!==18'(ex_re[seen]+(inject_numeric?1:0))||m_im!==18'(ex_im[seen])||m_last!==1'(ex_last[seen]))
        $fatal(1,"[NUMERIC] load output data/TLAST mismatch");
      if(m_phase!==32'(ex_phase[seen]+(inject_phase?1:0))) $fatal(1,"[PHASE] load output phase mismatch");
      seen++;
    end
  end
  initial begin
    if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("TRACE=%s",trace_file)) $fatal(1,"missing load paths");
    inject_numeric=$test$plusargs("INJECT_NUMERIC");inject_phase=$test$plusargs("INJECT_PHASE");
    inject_hold=$test$plusargs("INJECT_HOLD");require_unblocked=$test$plusargs("REQUIRE_UNBLOCKED");
    fd=$fopen({vectors,"/load.txt"},"r");if(!fd) $fatal(1,"missing load schedule");
    rc=$fscanf(fd,"%d %d",total,horizon);if(rc!=2||total<1||horizon<1) $fatal(1,"invalid load header");
    arrivals=new[total];ready_mask=new[horizon];
    for(int j=0;j<total;j++) begin rc=$fscanf(fd,"%d",arrivals[j]);if(rc!=1) $fatal(1,"truncated arrivals");end
    for(int j=0;j<horizon;j++) begin rc=$fscanf(fd,"%d",ready_mask[j]);if(rc!=1) $fatal(1,"truncated readiness");end
    $fclose(fd);
    in_re=new[total];in_im=new[total];in_last=new[total];
    ex_re=new[total];ex_im=new[total];ex_phase=new[total];ex_last=new[total];
    fd=$fopen({vectors,"/input.txt"},"r");rc=$fscanf(fd,"%d",expected_total);if(rc!=1||expected_total!=total) $fatal(1,"input count");
    for(int j=0;j<total;j++) begin rc=$fscanf(fd,"%d %d %d",in_re[j],in_im[j],in_last[j]);if(rc!=3) $fatal(1,"truncated input");end
    $fclose(fd);
    fd=$fopen({vectors,"/expected.txt"},"r");rc=$fscanf(fd,"%d",expected_total);if(rc!=1||expected_total!=total) $fatal(1,"expected count");
    for(int j=0;j<total;j++) begin rc=$fscanf(fd,"%d %d %d %d",ex_re[j],ex_im[j],ex_phase[j],ex_last[j]);if(rc!=4) $fatal(1,"truncated expected");end
    $fclose(fd);
    fd=$fopen({vectors,"/config.txt"},"r");rc=$fscanf(fd,"%d %d",cfg_k1,cfg_k2);if(rc!=2) $fatal(1,"configuration count");$fclose(fd);
    trace_fd=$fopen(trace_file,"w");if(!trace_fd) $fatal(1,"missing trace output");
    $fdisplay(trace_fd,"cycle,s_valid,s_ready,s_last,s_re,s_im,f_valid,f_ready,f_last,f_re,f_im,m_valid,m_ready,m_last,m_re,m_im,m_phase,level,configured");
    repeat(4) @(negedge clk);rst=!RESET_ACTIVE;
    @(negedge clk);cfg_valid=1;
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
    if(!configured) $fatal(1,"[CONFIG] load configuration not accepted");
    @(negedge clk);scoring=1;m_ready=1'(ready_mask[0]);
    fork
      begin
        for(int j=0;j<total;j++) begin
          while(cycle+1<arrivals[j]) begin s_valid=0;@(negedge clk);end
          s_valid=1;s_last=1'(in_last[j]);s_data={18'(in_re[j]),18'(in_im[j])};
          do begin @(posedge clk);if(s_ready) break;@(negedge clk);end while(1);
          @(negedge clk);
        end
        s_valid=0;s_last=0;
      end
      begin
        int quiet=0;
        while(quiet<5) begin
          @(negedge clk);
          if(seen==total) quiet++;
          if(cycle+1<horizon) m_ready=1'(ready_mask[cycle+1]);
          if(inject_hold&&held_outputs>0&&!hold_corrupted) hold_corrupted=1;
        end
      end
    join
    if(sent!=total||consumed!=total||seen!=total||level!=0||m_valid) $fatal(1,"[COVERAGE] incomplete load drain");
    $fclose(trace_fd);
    $display("PASS FIFO LOAD depth=%0d words=%0d wait=%0d peak=%0d held_outputs=%0d held_fifo=%0d",DEPTH,total,waits,peak,held_outputs,held_fifo);
    $finish;
  end
  initial begin #5000000;$fatal(1,"[TIMEOUT] load test did not finish");end
endmodule
