// Parameterised N x N MMSE / zero-forcing solver (rtl/common/mmse_n.sv) against the integer model
// common/python/mmse_n_fixed.py (vectors from tools/mmse_n_cases.py). The bench drives the N*N Q15
// entries of H in row-major order (cfg_last and cfg_lambda on the last one), waits for configured,
// compares every internal weight with weights.txt ([WEIGHTS]) and streams the observation N-tuples
// of in.txt. Every accepted output must equal out.txt exactly ([NUMERIC]), including m_last.
// +STALL_INPUT random input gaps, +STALL_OUTPUT random m_ready (~2/3 high). Without stalls the
// configured block must accept a sample on every clock ([THROUGHPUT]).
// +MID_RESET: half of the first transaction, then reset; +OUT_RESET: the whole first transaction,
// reset after the first accepted output; +CFG_RESET: reset after the first half of the
// configuration. After each reset the DUT must be silent, then everything runs again and is scored.
// +REJECT=<file>: drive the configuration of that file (same format as cfg.txt) and require
// error=1, configured=0, no output and no input ready ("PASS MMSE_N CONFIG REJECT").
// +BAD_CFG_LAST: cfg_last on the first entry; +BAD_CFG_COUNT: N*N+1 entries (both rejected).
// +BAD_DATA_LAST / +BAD_DATA_LAST_SECOND: s_last on the first / on sample N-2 of a tuple (N >= 3,
// after a reservation was made); the reservation must be released ("PASS MMSE_N DATA REJECT").
// Negative controls: +INJECT_MISMATCH, +INJECT_WEIGHT_MISMATCH, +INJECT_BOUND_MISMATCH and the
// sat_event_check +INJECT_SAT_MISMATCH / +INJECT_SAT_EVAL_MISMATCH must end in $fatal.
`timescale 1ns/1ps
module mmse_n_tb;
  parameter int N=4;
  parameter bit RESET_ACTIVE=1;
  parameter int GRAM_ACC_WIDTH=36+$clog2(N+1),SUM_WIDTH=82+$clog2(N+1);
  parameter int A_PRODUCT_WIDTH=83,B_PRODUCT_WIDTH=121,A_UPDATE_WIDTH=53,B_UPDATE_WIDTH=91;
  parameter int NORM_WIDTH=70,WEIGHT_WIDTH=87,MULT_NUM_WIDTH=65,BACK_PRODUCT_WIDTH=107,BACK_ACC_WIDTH=106+$clog2(N);
  localparam int NN=N*N;
  localparam int YW=SUM_WIDTH;
  localparam int DEPTH=1<<$clog2(4*N);
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  string directory,reject_file;
  integer fd,cfd,ofd,rc,stall_in,stall_out,inject;
  logic cfg_valid=0,cfg_last=0,cfg_ready,configured;
  logic signed [17:0] cfg_re=0,cfg_im=0;
  logic [33:0] cfg_lambda='0;
  logic s_valid=0,s_last=0,s_ready;
  logic signed [17:0] s_re=0,s_im=0;
  logic m_valid,m_last,m_ready=1,dut_error;
  logic signed [17:0] m_re,m_im;
  mmse_n #(.N(N),.RESET_ACTIVE(RESET_ACTIVE),.GRAM_ACC_WIDTH(GRAM_ACC_WIDTH),.SUM_WIDTH(SUM_WIDTH),
    .A_PRODUCT_WIDTH(A_PRODUCT_WIDTH),.B_PRODUCT_WIDTH(B_PRODUCT_WIDTH),.A_UPDATE_WIDTH(A_UPDATE_WIDTH),.B_UPDATE_WIDTH(B_UPDATE_WIDTH),
    .NORM_WIDTH(NORM_WIDTH),.WEIGHT_WIDTH(WEIGHT_WIDTH),.MULT_NUM_WIDTH(MULT_NUM_WIDTH),
    .BACK_PRODUCT_WIDTH(BACK_PRODUCT_WIDTH),.BACK_ACC_WIDTH(BACK_ACC_WIDTH)) dut
   (.clk(clk),.rst(rst),
    .cfg_valid(cfg_valid),.cfg_last(cfg_last),.cfg_re(cfg_re),.cfg_im(cfg_im),
    .cfg_lambda(cfg_lambda),.cfg_ready(cfg_ready),.configured(configured),
    .s_valid(s_valid),.s_last(s_last),.s_re(s_re),.s_im(s_im),.s_ready(s_ready),
    .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(m_ready),
    .error(dut_error));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("mmse_n m")) check_m
   (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}));
  axis_check #(.WIDTH(36+34),.RESET_ACTIVE(RESET_ACTIVE),.NAME("mmse_n cfg")) check_cfg
   (.clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(cfg_last),.data({cfg_re,cfg_im,cfg_lambda}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("mmse_n s")) check_s
   (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im}));
  stream_cover #(.FIELDS(2),.FW(18),.MODES(1),.RESET_ACTIVE(RESET_ACTIVE),.NAME("mmse_n m")) cover_m
   (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}),.mode(0));
  int cfg_re_v[NN],cfg_im_v[NN];
  longint cfg_lambda_v;
  int rd_re,rd_im,rd_last;
  int in_total,in_re[],in_im[],in_last[];
  int out_total,out_checked=0;
  bit scoring=1,rejecting=0;
  wire signed [YW+2:0] mmse_rounded [0:2*N-1];
  for(genvar row=0;row<N;row++) begin : g_observer
    assign mmse_rounded[2*row]=((YW+3)'(dut.yr[row])+(YW+3)'(8388608))>>>24;
    assign mmse_rounded[2*row+1]=((YW+3)'(dut.yi[row])+(YW+3)'(8388608))>>>24;
  end
  sat_event_check #(.FIELDS(2*N),.RAW_WIDTH(YW+3),.OUT_WIDTH(18),.RESET_ACTIVE(RESET_ACTIVE),
                     .NAME("mmse_n"),.EXPECTED_FILE("mmse_n_expected.txt")) saturation_check
    (.clk(clk),.rst(rst),.scoring(scoring&&!rejecting),.sample_valid(dut.p_valid),
     .done(!rejecting&&out_total>0&&out_checked==out_total),.rounded(mmse_rounded));
  longint weight_re_v[NN],weight_im_v[NN];
  int mid_reset,out_reset,cfg_reset,warm_out=0,n0,config_cycles=0;
  longint cycle=0;
  always @(posedge clk) cycle<=cycle+1;
  always @(negedge clk) if(stall_out) m_ready<=(($urandom%3)!=0);
  always @(posedge clk) if(rst!=RESET_ACTIVE&&scoring&&!stall_in&&!stall_out&&configured&&s_valid)
    if(!s_ready) $fatal(1,"[THROUGHPUT] MMSE_N did not sustain consecutive input samples/frames");
  always @(posedge clk) if(rst!=RESET_ACTIVE&&dut.cstate!=dut.C_IDLE) config_cycles++;

  // FIFO/reservation monitor: actual occupancy and N-sample reservations before every edge.
  int bounds_checks=0,simultaneous=0;
  int expected_fifo=0,expected_pending=0,expected_head=0,expected_tail=0;
  always @(posedge clk) begin
    if(rst==RESET_ACTIVE) begin
      bounds_checks=0;simultaneous=0;expected_fifo=0;expected_pending=0;expected_head=0;expected_tail=0;
    end else begin
      int next_fifo,next_pending;
      if($isunknown({dut.count,dut.index,dut.fifo_count,dut.pending,dut.fifo_head,dut.fifo_tail,
                     dut.take,dut.pop,dut.e_valid,dut.reserve,dut.cancel,dut.cstate}))
        $fatal(1,"[BOUNDS] MMSE_N unknown active controls");
      if(int'(dut.fifo_count)!=expected_fifo||int'(dut.pending)!=expected_pending
         ||int'(dut.fifo_head)!=expected_head||int'(dut.fifo_tail)!=expected_tail)
        $fatal(1,"[BOUNDS] MMSE_N FIFO/reservation transition");
      next_fifo=int'(dut.fifo_count)+N*int'(dut.e_valid)-int'(dut.pop);
      next_pending=int'(dut.pending)+int'(dut.reserve)-int'(dut.e_valid)-int'(dut.cancel);
      if(next_fifo<0||next_fifo>DEPTH||next_pending<0||next_fifo+N*next_pending>DEPTH)
        $fatal(1,"[BOUNDS] MMSE_N FIFO reservation capacity");
      if(dut.pop&&dut.fifo_count==0) $fatal(1,"[BOUNDS] MMSE_N empty read");
      if(dut.e_valid&&dut.pending==0) $fatal(1,"[BOUNDS] MMSE_N unreserved write");
      if(int'(dut.index)>=N||int'(dut.count)>NN) $fatal(1,"[BOUNDS] MMSE_N matrix/input index");
      if(dut.take&&scoring) begin
        int observed;
        observed=int'(dut.index);
        if($test$plusargs("INJECT_BOUND_MISMATCH")) observed=N;
        if(observed<0||observed>=N) $fatal(1,"[BOUNDS] MMSE_N active observation index");
      end
      expected_fifo=next_fifo;expected_pending=next_pending;
      expected_head=(int'(dut.fifo_head)+int'(dut.pop))%DEPTH;
      expected_tail=(int'(dut.fifo_tail)+N*int'(dut.e_valid))%DEPTH;
      if(scoring&&(dut.take||dut.pop||dut.e_valid||dut.cfg_take)) bounds_checks++;
      if(scoring&&dut.e_valid&&dut.pop) simultaneous++;
    end
  end

  // Scoreboard: every accepted output must equal mmse_n_fixed.solve exactly.
  always @(posedge clk) if(rst!=RESET_ACTIVE) begin
    int re,im,last;
    if(scoring&&m_valid&&m_ready) begin
      rc=$fscanf(ofd,"%d %d %d",re,im,last);
      if(rc!=3) $fatal(1,"[VECTOR] incomplete expected MMSE_N output");
      if(inject&&out_checked==0) re=re+1;
      if(m_re!==18'(re)||m_im!==18'(im)||m_last!==1'(last)) begin
        $display("MISMATCH output %0d: %0d,%0d/%0d,%0d last %0d/%0d",out_checked,m_re,m_im,re,im,m_last,last);
        $fatal(1,"[NUMERIC] mmse_n output");
      end
      out_checked=out_checked+1;
    end
  end
  always @(posedge clk) if(!scoring&&m_valid&&m_ready) warm_out=warm_out+1;
  task automatic drive_cfg(input int re,input int im,input int last,input longint lam);
    @(negedge clk);
    cfg_valid=1;cfg_last=1'(last);cfg_re=18'(re);cfg_im=18'(im);cfg_lambda=34'(lam);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(cfg_valid&&cfg_ready) return;
    end
    $fatal(1,"[THROUGHPUT] configuration entry never accepted (cycle %0d)",cycle);
  endtask
  task automatic drive_in(input int re,input int im,input int last);
    if(stall_in&&(($urandom%8)==0)) begin
      @(negedge clk);s_valid=0;repeat(1+$urandom%3) @(negedge clk);
    end else @(negedge clk);
    s_valid=1;s_re=18'(re);s_im=18'(im);s_last=1'(last);
    for(int guard=0;guard<65536;guard++) begin
      @(posedge clk);
      if(s_valid&&s_ready) return;
    end
    $fatal(1,"[THROUGHPUT] observation never accepted (cycle %0d)",cycle);
  endtask
  task automatic wait_config;
    for(int guard=0;guard<200000;guard++) begin
      @(posedge clk);
      if(configured||dut_error) break;
    end
  endtask
  task automatic configure;
    for(int j=0;j<NN;j++) drive_cfg(cfg_re_v[j],cfg_im_v[j],j==NN-1,cfg_lambda_v);
    @(negedge clk);cfg_valid=0;
    wait_config;
    if(dut_error!==1'b0) $fatal(1,"[NUMERIC] error asserted on an accepted H");
    if(configured!==1'b1) $fatal(1,"[TIMEOUT] DUT never configured");
    for(int j=0;j<NN;j++) begin
      longint expected_re;
      expected_re=weight_re_v[j];
      if(j==0&&$test$plusargs("INJECT_WEIGHT_MISMATCH")) expected_re+=1;
      if(dut.wr[j]!==expected_re||dut.wi[j]!==weight_im_v[j])
        $fatal(1,"[WEIGHTS] MMSE_N coefficient %0d differs from integer model",j);
    end
  endtask
  task automatic read_cfg(input string path);
    cfd=$fopen(path,"r");
    if(!cfd) $fatal(1,"[VECTOR] missing %s",path);
    for(int j=0;j<NN;j++) if($fscanf(cfd,"%d %d",cfg_re_v[j],cfg_im_v[j])!=2) $fatal(1,"[VECTOR] short cfg");
    if($fscanf(cfd,"%d",cfg_lambda_v)!=1) $fatal(1,"[VECTOR] missing lambda");
    $fclose(cfd);
  endtask
  task automatic require_rejected(input string marker);
    @(negedge clk);cfg_valid=0;s_valid=0;s_last=0;
    wait_config;
    repeat(20) @(negedge clk);
    if(dut_error!==1'b1||configured!==1'b0||m_valid!==1'b0||s_ready!==1'b0||cfg_ready!==1'b0
       ||dut.pending!=='0||dut.index!=='0)
      $fatal(1,"[REJECTION] MMSE_N accepted an invalid %s or leaked a reservation",marker);
    $display("PASS MMSE_N %s REJECT",marker);
  endtask
  function automatic void load_vectors;
    fd=$fopen({directory,"/in.txt"},"r");
    while($fscanf(fd,"%d %d %d",rd_re,rd_im,rd_last)==3) in_total=in_total+1;
    rc=$fseek(fd,0,0);
    in_re=new[in_total];in_im=new[in_total];in_last=new[in_total];
    for(int j=0;j<in_total;j=j+1) begin
      rc=$fscanf(fd,"%d %d %d",rd_re,rd_im,rd_last);
      in_re[j]=rd_re;in_im[j]=rd_im;in_last[j]=rd_last;
    end
    $fclose(fd);
    ofd=$fopen({directory,"/out.txt"},"r");
    while($fscanf(ofd,"%d %d %d",rd_re,rd_im,rd_last)==3) out_total=out_total+1;
    rc=$fseek(ofd,0,0);
  endfunction
  initial begin
    if(!$value$plusargs("VECTORS=%s",directory)) $fatal(1,"VECTORS is required");
    stall_in=$test$plusargs("STALL_INPUT");stall_out=$test$plusargs("STALL_OUTPUT");
    inject=$test$plusargs("INJECT_MISMATCH");
    mid_reset=$test$plusargs("MID_RESET");out_reset=$test$plusargs("OUT_RESET");
    cfg_reset=$test$plusargs("CFG_RESET");
    read_cfg({directory,"/cfg.txt"});
    load_vectors;
    cfd=$fopen({directory,"/weights.txt"},"r");
    if(!cfd) $fatal(1,"[VECTOR] missing weights");
    for(int j=0;j<NN;j++) if($fscanf(cfd,"%d %d",weight_re_v[j],weight_im_v[j])!=2) $fatal(1,"[VECTOR] incomplete weights");
    $fclose(cfd);
    repeat(10) @(negedge clk);rst=!RESET_ACTIVE;repeat(3) @(negedge clk);
    if($value$plusargs("REJECT=%s",reject_file)||$test$plusargs("BAD_CFG_LAST")||$test$plusargs("BAD_CFG_COUNT")) begin
      rejecting=1;
      if($test$plusargs("BAD_CFG_LAST")) drive_cfg(32768,0,1,0);
      else if($test$plusargs("BAD_CFG_COUNT")) for(int j=0;j<=NN;j++) drive_cfg(32768,0,j==NN,0);
      else begin
        read_cfg(reject_file);
        for(int j=0;j<NN;j++) drive_cfg(cfg_re_v[j],cfg_im_v[j],j==NN-1,cfg_lambda_v);
      end
      require_rejected("CONFIG");$finish;
    end
    if(!cfg_reset) configure;
    if($test$plusargs("BAD_DATA_LAST")||$test$plusargs("BAD_DATA_LAST_SECOND")) begin
      rejecting=1;
      if($test$plusargs("BAD_DATA_LAST_SECOND")) begin
        if(N<3) $fatal(1,"[VECTOR] BAD_DATA_LAST_SECOND needs N >= 3");
        for(int j=0;j<N-2;j++) drive_in(1,0,0);
      end
      drive_in(1,0,1);
      require_rejected("DATA");$finish;
    end
    if(mid_reset||out_reset||cfg_reset) begin
      scoring=0;
      if(cfg_reset) begin
        for(int j=0;j<NN/2;j=j+1) drive_cfg(cfg_re_v[j],cfg_im_v[j],0,0);
        if(configured) $fatal(1,"[CFG_RESET] already configured");
      end else begin
        n0=in_total;
        for(int j=0;j<in_total;j=j+1) if(in_last[j]) begin n0=j+1;break; end
        if(out_reset) begin
          for(int j=0;j<n0;j=j+1) drive_in(in_re[j],in_im[j],in_last[j]);
          @(negedge clk);s_valid=0;s_last=0;
          for(int t=0;warm_out==0&&t<200000;t=t+1) @(negedge clk);
          if(warm_out==0) $fatal(1,"[TIMEOUT] no output before OUT_RESET");
        end else begin
          for(int j=0;j<((n0/2>0)?n0/2:1)&&j<n0-1;j=j+1) drive_in(in_re[j],in_im[j],0);
        end
      end
      @(negedge clk);cfg_valid=0;s_valid=0;s_last=0;rst=RESET_ACTIVE;
      repeat(5) @(negedge clk);rst=!RESET_ACTIVE;
      @(negedge clk);
      if(m_valid!==1'b0) $fatal(1,"[RESET] output valid after reset");
      if(configured!==1'b0) $fatal(1,"[RESET] configured survived the reset");
      if(dut_error!==1'b0) $fatal(1,"[RESET] error after reset");
      repeat(2) @(negedge clk);
      scoring=1;config_cycles=0;
      configure;
    end
    for(int j=0;j<in_total;j=j+1) drive_in(in_re[j],in_im[j],in_last[j]);
    @(negedge clk);s_valid=0;s_last=0;
    wait(out_checked==out_total);
    repeat(20) @(negedge clk);
    if(dut_error!==1'b0) $fatal(1,"[NUMERIC] error asserted although every transaction was complete");
    if(bounds_checks<1||dut.fifo_count!=0||dut.pending!=0)
      $fatal(1,"[BOUNDS] MMSE_N monitor not exercised or FIFO not drained");
    check_mmse_n_widths();
    $display("PASS BOUNDS mmse_n: %0d checks, %0d simultaneous",bounds_checks,simultaneous);
    check_scale_updates();
    check_norm_back();
    $display("PASS MMSE_N: %0d outputs, %0d cycles, %0d config cycles",out_checked,cycle,config_cycles);
    $finish;
  end
  `include "mmse_n_width_check.svh"
  `include "mmse_n_update_check.svh"
  `include "mmse_n_norm_back_check.svh"
  initial begin #400000000;$fatal(1,"MMSE_N testbench did not drain"); end
endmodule
