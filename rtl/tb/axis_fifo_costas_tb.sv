// Integration experiment: external input FIFO + unchanged production Costas.
`timescale 1ns/1ps
module axis_fifo_costas_tb;
  parameter int DEPTH=56;
  parameter bit RESET_ACTIVE=1;
  parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
  localparam int CW=DEPTH>1?$clog2(DEPTH+1):1;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  logic s_valid=0,s_last=0,s_ready,m_valid,m_last,m_ready=0;
  logic [35:0] s_data=0,fifo_data;
  logic fifo_valid,fifo_last,fifo_ready;
  logic [CW-1:0] level;
  logic cfg_valid=0,cfg_ready,configured;
  logic [31:0] cfg_k1,cfg_k2;
  logic signed [17:0] m_re,m_im;
  logic signed [31:0] m_phase;
  axis_fifo #(.WIDTH(36),.DEPTH(DEPTH),.RESET_ACTIVE(RESET_ACTIVE)) fifo(
    .clk(clk),.rst(rst),.s_valid(s_valid),.s_last(s_last),.s_data(s_data),.s_ready(s_ready),
    .m_valid(fifo_valid),.m_last(fifo_last),.m_data(fifo_data),.m_ready(fifo_ready),.level(level));
  costas_loop #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) core(
    .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_ready(cfg_ready),.cfg_k1(cfg_k1),.cfg_k2(cfg_k2),.configured(configured),
    .s_valid(fifo_valid),.s_last(fifo_last),.s_re($signed(fifo_data[35:18])),.s_im($signed(fifo_data[17:0])),.s_ready(fifo_ready),
    .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_phase(m_phase),.m_ready(m_ready));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("Buffered Costas input")) input_check(
    .clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data(s_data));
  axis_check #(.WIDTH(68),.RESET_ACTIVE(RESET_ACTIVE),.NAME("Buffered Costas output")) output_check(
    .clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im,m_phase}));
  string vectors,trace_file;
  int fd,logfile,total,rc,scenario,seen=0,sent=0,consumed=0,source_wait=0,peak=0;
  int input_re[],input_im[],input_last[],expected_re[],expected_im[],expected_phase[],expected_last[];
  longint cycle=0,first_arrival=-1,last_arrival=-1,first_consumed=-1,previous_consumed=-1,min_interval=1000000,max_interval=0;
  bit scoring=0,accepted=0,require_burst,inject_numeric,inject_phase;
  always @(posedge clk) begin
    cycle++;accepted=rst!=RESET_ACTIVE&&s_valid&&s_ready;
    if(rst!=RESET_ACTIVE&&scoring) begin
      if(int'(level)>peak) peak=int'(level);
      if(s_valid&&s_ready) begin
        if(first_arrival<0) first_arrival=cycle;
        last_arrival=cycle;sent++;accepted=1;
      end
      if(s_valid&&!s_ready) begin
        source_wait++;
        if(require_burst) $fatal(1,"[CAPACITY] external FIFO cannot accept the finite burst without stalls");
      end
      if(fifo_valid&&fifo_ready) begin
        if(first_consumed<0) first_consumed=cycle;
        if(previous_consumed>=0) begin
          if(cycle-previous_consumed<min_interval) min_interval=cycle-previous_consumed;
          if(cycle-previous_consumed>max_interval) max_interval=cycle-previous_consumed;
        end
        previous_consumed=cycle;consumed++;
      end
      if(m_valid&&m_ready) begin
        if(seen>=total) $fatal(1,"[NUMERIC] extra buffered Costas output");
        if(m_re!==18'(expected_re[seen]+(inject_numeric?1:0))||m_im!==18'(expected_im[seen])||m_last!==1'(expected_last[seen]))
          $fatal(1,"[NUMERIC] buffered Costas data/TLAST");
        if(m_phase!==32'(expected_phase[seen]+(inject_phase?1:0))) $fatal(1,"[PHASE] buffered Costas phase");
        seen++;
      end
      $fdisplay(logfile,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",cycle,s_valid,s_ready,s_last,fifo_valid,fifo_ready,fifo_last,m_valid,m_ready,m_last,level);
    end
  end
  task automatic configure;
    @(negedge clk);cfg_valid=1;
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
    if(!configured) $fatal(1,"[CONFIG] Costas configuration did not finish");
  endtask
  initial begin
    if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("TRACE=%s",trace_file)) $fatal(1,"missing integration paths");
    if(!$value$plusargs("SCENARIO=%d",scenario)) scenario=0;
    require_burst=$test$plusargs("REQUIRE_BURST");inject_numeric=$test$plusargs("INJECT_NUMERIC");inject_phase=$test$plusargs("INJECT_PHASE");
    fd=$fopen({vectors,"/input.txt"},"r");rc=$fscanf(fd,"%d",total);
    input_re=new[total];input_im=new[total];input_last=new[total];
    for(int j=0;j<total;j++) rc=$fscanf(fd,"%d %d %d",input_re[j],input_im[j],input_last[j]);$fclose(fd);
    fd=$fopen({vectors,"/expected.txt"},"r");rc=$fscanf(fd,"%d",total);
    expected_re=new[total];expected_im=new[total];expected_phase=new[total];expected_last=new[total];
    for(int j=0;j<total;j++) rc=$fscanf(fd,"%d %d %d %d",expected_re[j],expected_im[j],expected_phase[j],expected_last[j]);$fclose(fd);
    fd=$fopen({vectors,"/config.txt"},"r");rc=$fscanf(fd,"%d %d",cfg_k1,cfg_k2);$fclose(fd);
    logfile=$fopen(trace_file,"w");$fdisplay(logfile,"cycle,s_valid,s_ready,s_last,f_valid,f_ready,f_last,m_valid,m_ready,m_last,level");
    repeat(4) @(negedge clk);rst=!RESET_ACTIVE;configure();
    if(scenario==2) begin
      // Queue a full burst while the core output is blocked, then reset both.
      for(int j=0;j<DEPTH+16;j++) begin
        @(negedge clk);
        if(!s_valid||accepted) begin s_valid=1;s_last=0;s_data={18'(j),18'(-j)};end
      end
      @(negedge clk);rst=RESET_ACTIVE;s_valid=0;
      repeat(4) @(negedge clk);rst=!RESET_ACTIVE;
      @(negedge clk);
      if(m_valid||level!=0||configured) $fatal(1,"[RESET] stale buffered Costas state");
      configure();
    end
    @(negedge clk);scoring=1;m_ready=1;
    for(int j=0;j<total;j++) begin
      s_valid=1;s_last=1'(input_last[j]);s_data={18'(input_re[j]),18'(input_im[j])};
      do begin
        @(posedge clk);
        // Read the handshake pins directly; monitor scheduling is independent.
        if(s_ready) break;
        @(negedge clk);
      end while(1);
      @(negedge clk);
    end
    s_valid=0;s_last=0;
    wait(seen==total);repeat(5) @(negedge clk);
    if(sent!=total||consumed!=total||level!=0||m_valid) $fatal(1,"[COVERAGE] incomplete buffered Costas stream");
    $fclose(logfile);
    $display("PASS BUFFERED COSTAS depth=%0d words=%0d wait=%0d peak=%0d arrival_span=%0d first_service=%0d min_interval=%0d max_interval=%0d",DEPTH,total,source_wait,peak,last_arrival-first_arrival+1,first_consumed-first_arrival,min_interval,max_interval);
    $finish;
  end
  always @(negedge clk) if(scoring&&scenario==1) m_ready=(cycle%8)<5;
  initial begin #5000000;$fatal(1,"[TIMEOUT] buffered Costas did not finish");end
endmodule
