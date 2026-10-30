// Full-code operands deposited directly into actual DUT storage. Individual
// edges exercise the unchanged streaming MAC; configuration FSM is held idle.
`timescale 1ns/1ps
module mmse_n_width_tb;
  parameter int N=4,GRAM_ACC_WIDTH=36+$clog2(N+1),SUM_WIDTH=82+$clog2(N+1);
  parameter bit RESET_ACTIVE=1;
  logic clk=0,rst=!RESET_ACTIVE;
  logic signed [17:0] xr=0,xi=0;
  logic [N*N-1:0] hr_high=0,hi_high=0,wr_high=0,wi_high=0;
  logic [$clog2(N+1)-1:0] cc_control=0,cj_control=0;
  logic signed [GRAM_ACC_WIDTH-1:0] gram_re_control=0,gram_im_control=0;
  logic take_control=0;
  logic [$clog2(N+1)-1:0] index_control=0;
  logic cfg_ready,configured,s_ready,m_valid,m_last,error;
  logic signed [17:0] m_re,m_im;
  int gram_checks=0,sum_checks=0,round_checks=0;
  string inject;
  mmse_n #(.N(N),.RESET_ACTIVE(RESET_ACTIVE),.GRAM_ACC_WIDTH(GRAM_ACC_WIDTH),.SUM_WIDTH(SUM_WIDTH)) dut(
    .clk(clk),.rst(rst),.cfg_valid(1'b0),.cfg_last(1'b0),.cfg_re(18'sd0),.cfg_im(18'sd0),
    .cfg_lambda(34'd0),.cfg_ready(cfg_ready),.configured(configured),
    .s_valid(1'b0),.s_last(1'b0),.s_re(xr),.s_im(xi),.s_ready(s_ready),
    .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(1'b0),.error(error));
  initial begin
    force dut.ci=0;force dut.cj=cj_control;force dut.cc=cc_control;
    force dut.sum_re=gram_re_control;force dut.sum_im=gram_im_control;
    force dut.take=take_control;force dut.index=index_control;force dut.cstate=dut.C_IDLE;
    force dut.p_valid=1'b0;force dut.e_valid=1'b0;
    force dut.lambda=34'h3ffffffff;
    force dut.pending=0;force dut.fifo_count=0;force dut.fifo_tail=0;force dut.fifo_head=0;
  end
  // Constant-index constant-RHS forces avoid simulator dynamic-array deposit
  // bugs. Each bit selects one of the two complete input-code rails.
  // Literal indices as well as literal rails are intentional: Questa 2024.1
  // can crash on unpacked-array force with an elaborated genvar index.
  `define MMSE_N_FORCE_SLOT(I) \
    if(N*N>I) begin : g_force_``I \
      initial begin \
        force dut.hr[I]=18'sh20000; \
        forever begin @(hr_high[I]);if(hr_high[I]) force dut.hr[I]=18'sd131071;else force dut.hr[I]=18'sh20000;end \
      end \
      initial begin \
        force dut.hi[I]=18'sh20000; \
        forever begin @(hi_high[I]);if(hi_high[I]) force dut.hi[I]=18'sd131071;else force dut.hi[I]=18'sh20000;end \
      end \
      initial begin \
        force dut.wr[I]=64'sh8000000000000000; \
        forever begin @(wr_high[I]);if(wr_high[I]) force dut.wr[I]=64'sh7fffffffffffffff;else force dut.wr[I]=64'sh8000000000000000;end \
      end \
      initial begin \
        force dut.wi[I]=64'sh8000000000000000; \
        forever begin @(wi_high[I]);if(wi_high[I]) force dut.wi[I]=64'sh7fffffffffffffff;else force dut.wi[I]=64'sh8000000000000000;end \
      end \
    end
  `MMSE_N_FORCE_SLOT(0)
  `MMSE_N_FORCE_SLOT(1)
  `MMSE_N_FORCE_SLOT(2)
  `MMSE_N_FORCE_SLOT(3)
  `MMSE_N_FORCE_SLOT(4)
  `MMSE_N_FORCE_SLOT(5)
  `MMSE_N_FORCE_SLOT(6)
  `MMSE_N_FORCE_SLOT(7)
  `MMSE_N_FORCE_SLOT(8)
  `MMSE_N_FORCE_SLOT(9)
  `MMSE_N_FORCE_SLOT(10)
  `MMSE_N_FORCE_SLOT(11)
  `MMSE_N_FORCE_SLOT(12)
  `MMSE_N_FORCE_SLOT(13)
  `MMSE_N_FORCE_SLOT(14)
  `MMSE_N_FORCE_SLOT(15)
  `MMSE_N_FORCE_SLOT(16)
  `MMSE_N_FORCE_SLOT(17)
  `MMSE_N_FORCE_SLOT(18)
  `MMSE_N_FORCE_SLOT(19)
  `MMSE_N_FORCE_SLOT(20)
  `MMSE_N_FORCE_SLOT(21)
  `MMSE_N_FORCE_SLOT(22)
  `MMSE_N_FORCE_SLOT(23)
  `MMSE_N_FORCE_SLOT(24)
  `MMSE_N_FORCE_SLOT(25)
  `MMSE_N_FORCE_SLOT(26)
  `MMSE_N_FORCE_SLOT(27)
  `MMSE_N_FORCE_SLOT(28)
  `MMSE_N_FORCE_SLOT(29)
  `MMSE_N_FORCE_SLOT(30)
  `MMSE_N_FORCE_SLOT(31)
  `MMSE_N_FORCE_SLOT(32)
  `MMSE_N_FORCE_SLOT(33)
  `MMSE_N_FORCE_SLOT(34)
  `MMSE_N_FORCE_SLOT(35)
  `MMSE_N_FORCE_SLOT(36)
  `MMSE_N_FORCE_SLOT(37)
  `MMSE_N_FORCE_SLOT(38)
  `MMSE_N_FORCE_SLOT(39)
  `MMSE_N_FORCE_SLOT(40)
  `MMSE_N_FORCE_SLOT(41)
  `MMSE_N_FORCE_SLOT(42)
  `MMSE_N_FORCE_SLOT(43)
  `MMSE_N_FORCE_SLOT(44)
  `MMSE_N_FORCE_SLOT(45)
  `MMSE_N_FORCE_SLOT(46)
  `MMSE_N_FORCE_SLOT(47)
  `MMSE_N_FORCE_SLOT(48)
  `MMSE_N_FORCE_SLOT(49)
  `MMSE_N_FORCE_SLOT(50)
  `MMSE_N_FORCE_SLOT(51)
  `MMSE_N_FORCE_SLOT(52)
  `MMSE_N_FORCE_SLOT(53)
  `MMSE_N_FORCE_SLOT(54)
  `MMSE_N_FORCE_SLOT(55)
  `MMSE_N_FORCE_SLOT(56)
  `MMSE_N_FORCE_SLOT(57)
  `MMSE_N_FORCE_SLOT(58)
  `MMSE_N_FORCE_SLOT(59)
  `MMSE_N_FORCE_SLOT(60)
  `MMSE_N_FORCE_SLOT(61)
  `MMSE_N_FORCE_SLOT(62)
  `MMSE_N_FORCE_SLOT(63)
  `undef MMSE_N_FORCE_SLOT
  function automatic logic signed [17:0] hc(input bit high);
    return high?18'sd131071:18'sh20000;
  endfunction
  function automatic logic signed [63:0] wc(input bit high);
    return high?64'sh7fffffffffffffff:64'sh8000000000000000;
  endfunction
  task automatic check_round(input logic signed [127:0] raw);
    logic signed [127:0] rounded;
    logic signed [17:0] expected,actual;
    rounded=(raw+128'sd8388608)>>>24;
    expected=rounded>131071?18'sd131071:rounded< -131072?18'sh20000:18'(rounded);
    actual=dut.sat18(SUM_WIDTH'(raw));
    if(inject=="ROUND"&&round_checks==0) actual^=18'd1;
    if(actual!==expected) $fatal(1,"[ROUND] directed mmse_n");
    round_checks++;
  endtask
  task automatic check_gram(input int col);
    logic signed [127:0] re,im,actual;
    re=0;im=0;cj_control=$clog2(N+1)'(col);
    for(int k=0;k<N;k++) begin
      cc_control=$clog2(N+1)'(k);gram_re_control=GRAM_ACC_WIDTH'(re);gram_im_control=GRAM_ACC_WIDTH'(im);
      #1;
      re+=128'(dut.hr[N*k])*128'(dut.hr[N*k+col])+128'(dut.hi[N*k])*128'(dut.hi[N*k+col]);
      im+=128'(dut.hr[N*k])*128'(dut.hi[N*k+col])-128'(dut.hi[N*k])*128'(dut.hr[N*k+col]);
      if(k==N-1&&col==0) re+=128'($signed({1'b0,dut.lambda}));
      #1;actual=128'(dut.gram_next_re);
      if(inject=="GRAM"&&gram_checks==0) actual+=1;
      if(actual!==re||128'(dut.gram_next_im)!==im) $fatal(1,"[GRAM] directed mmse_n");
      if(re!=128'(GRAM_ACC_WIDTH'(re))||im!=128'(GRAM_ACC_WIDTH'(im))) $fatal(1,"[GRAM] directed range");
      gram_checks+=2;
    end
  endtask
  task automatic check_sum(input int mask,input bit mixed);
    logic signed [127:0] re[0:N-1],im[0:N-1],actual;
    for(int row=0;row<N;row++) begin re[row]=0;im[row]=0;end
    take_control=1;
    for(int k=0;k<N;k++) begin
      int code;
      code=mixed?((mask>>(k%5))^(mask<<(k%3))):mask;
      index_control=$clog2(N+1)'(k);xr=hc(1'(code));xi=hc(1'(code>>1));
      for(int row=0;row<N;row++) begin
        wr_high[N*row+k]=1'(code>>2);wi_high[N*row+k]=1'(code>>3);
        re[row]+=128'(wc(1'(code>>2)))*128'(xr)-128'(wc(1'(code>>3)))*128'(xi);
        im[row]+=128'(wc(1'(code>>2)))*128'(xi)+128'(wc(1'(code>>3)))*128'(xr);
      end
      #1;clk=1;#1;clk=0;
      for(int row=0;row<N;row++) begin
        actual=128'(dut.yr[row]);
        if(inject=="SUM"&&sum_checks==0) actual+=1;
        if(actual!==re[row]||128'(dut.yi[row])!==im[row]) $fatal(1,"[SUM] directed mmse_n");
        if(re[row]!=128'(SUM_WIDTH'(re[row]))||im[row]!=128'(SUM_WIDTH'(im[row]))) $fatal(1,"[SUM] directed range");
        sum_checks+=2;
      end
    end
    take_control=0;
    for(int row=0;row<N;row++) begin check_round(re[row]);check_round(im[row]);end
  endtask
  task automatic deposit_h(input int mask,input bit mixed);
    for(int k=0;k<N;k++) begin
      int code;
      code=mixed?((mask>>(k%5))^(mask<<(k%3))):mask;
      hr_high[N*k]=1'(code);hi_high[N*k]=1'(code>>1);
      hr_high[N*k+1]=1'(code>>2);hi_high[N*k+1]=1'(code>>3);
    end
  endtask
  initial begin
    if($value$plusargs("INJECT_MMSE_N=%s",inject)) begin
      if(inject!="GRAM"&&inject!="SUM"&&inject!="ROUND") $fatal(1,"[WIDTHS] unknown injection");
    end
    for(int mode=0;mode<2;mode++) for(int mask=0;mask<(mode==0?16:256);mask++) begin
      deposit_h(mask,1'(mode));
      check_gram(0);check_gram(1);check_sum(mask,1'(mode));
    end
    for(int q=-2;q<=2;q++) for(int delta=-1;delta<=1;delta++)
      check_round((128'(q)<<<24)+128'sd8388608+128'(delta));
    for(int delta=-1;delta<=1;delta++) begin
      check_round((128'sd131071<<<24)+128'sd8388608+128'(delta));
      check_round((-128'sd131073<<<24)+128'sd8388608+128'(delta));
    end
    check_round((128'sd1<<<(SUM_WIDTH-1))-1);check_round(-(128'sd1<<<(SUM_WIDTH-1)));
    $display("PASS MMSE_N WIDTH DIRECTED N=%0d GRAM_ACC_WIDTH=%0d SUM_WIDTH=%0d gram=%0d sum=%0d round=%0d",N,GRAM_ACC_WIDTH,SUM_WIDTH,gram_checks,sum_checks,round_checks);
    $finish;
  end
endmodule
