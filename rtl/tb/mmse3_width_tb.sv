// Direct arithmetic tests with full-code operands. No configuration or
// free-running clock: output arithmetic is sampled with individual clock edges.
`timescale 1ns/1ps
module mmse3_width_tb;
  parameter bit RESET_ACTIVE=1;
  parameter int GRAM_WIDTH=38,SUM_WIDTH=84;
  logic clk=0,rst=!RESET_ACTIVE;
  logic signed [17:0] h_re[0:8],h_im[0:8];
  logic signed [63:0] w_re[0:8],w_im[0:8];
  logic signed [17:0] x_re[0:2],x_im[0:2];
  logic [33:0] lam;
  logic cfg_ready,configured,s_ready,m_valid,m_last,error;
  logic signed [17:0] m_re,m_im;
  int gram_checks=0,sum_checks=0,round_checks=0;
  string inject;
  mmse3 #(.RESET_ACTIVE(RESET_ACTIVE),.GRAM_WIDTH(GRAM_WIDTH),.SUM_WIDTH(SUM_WIDTH)) dut(
    .clk(clk),.rst(rst),.cfg_valid(1'b0),.cfg_last(1'b0),.cfg_re(18'sd0),.cfg_im(18'sd0),
    .cfg_lambda(34'd0),.cfg_ready(cfg_ready),.configured(configured),
    .s_valid(1'b0),.s_last(1'b0),.s_re(x_re[2]),.s_im(x_im[2]),.s_ready(s_ready),
    .m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(1'b0),.error(error));
  initial begin
    force dut.lambda=lam;
    force dut.take=1'b1;force dut.index=2;force dut.cstate=dut.C_IDLE;
  end
  // Deposits avoid a Verilator unpacked-array force internal error. With cfg
  // disabled and index forced to 2, the DUT never writes H/W/history arrays.
  task automatic deposit_operands;
    for(int j=0;j<9;j++) begin
      dut.hr[j]=h_re[j];dut.hi[j]=h_im[j];
      dut.wr[j]=w_re[j];dut.wi[j]=w_im[j];
    end
    for(int k=0;k<2;k++) begin
      dut.obs_re[k]=x_re[k];dut.obs_im[k]=x_im[k];
    end
  endtask
  function automatic logic signed [17:0] hcorner(input bit high);
    return high?18'sd131071:18'sh20000;
  endfunction
  function automatic logic signed [63:0] wcorner(input bit high);
    return high?64'sh7fffffffffffffff:64'sh8000000000000000;
  endfunction
  task automatic check_gram(input int row,col);
    logic signed [127:0] re,im,actual;
    re=0;im=0;
    for(int k=0;k<3;k++) begin
      re+=128'(h_re[3*k+row])*128'(h_re[3*k+col])+128'(h_im[3*k+row])*128'(h_im[3*k+col]);
      im+=128'(h_re[3*k+row])*128'(h_im[3*k+col])-128'(h_im[3*k+row])*128'(h_re[3*k+col]);
      if(re!=128'(GRAM_WIDTH'(re))||im!=128'(GRAM_WIDTH'(im)))
        $fatal(1,"[GRAM] directed partial range");
    end
    if(row==col) re+=128'($signed({1'b0,lam}));
    actual=128'(dut.gram(row,col,0));
    if(inject=="GRAM"&&gram_checks==0) actual+=1;
    if(actual!==re||128'(dut.gram(row,col,1))!==im)
      $fatal(1,"[GRAM] directed actual=%0d expected=%0d",actual,re);
    if(re!=128'(GRAM_WIDTH'(re))||im!=128'(GRAM_WIDTH'(im)))
      $fatal(1,"[GRAM] directed final range");
    gram_checks+=2;
  endtask
  task automatic check_sum;
    logic signed [127:0] re,im,actual;
    #1;clk=1;#1;clk=0;
    for(int row=0;row<3;row++) begin
      re=0;im=0;
      for(int k=0;k<3;k++) begin
        re+=128'(w_re[3*row+k])*128'(x_re[k])-128'(w_im[3*row+k])*128'(x_im[k]);
        im+=128'(w_re[3*row+k])*128'(x_im[k])+128'(w_im[3*row+k])*128'(x_re[k]);
      end
      actual=128'(dut.yr[row]);
      if(inject=="SUM"&&sum_checks==0) actual+=1;
      if(actual!==re||128'(dut.yi[row])!==im)
        $fatal(1,"[SUM] directed row=%0d",row);
      if(re!=128'(SUM_WIDTH'(re))||im!=128'(SUM_WIDTH'(im)))
        $fatal(1,"[SUM] directed range");
      sum_checks+=2;
    end
  endtask
  task automatic check_round(input logic signed [127:0] raw);
    logic signed [127:0] rounded;
    logic signed [17:0] expected,actual;
    rounded=(raw+128'sd8388608)>>>24;
    expected=rounded>131071?18'sd131071:rounded< -131072?18'sh20000:18'(rounded);
    actual=dut.sat18(SUM_WIDTH'(raw));
    if(inject=="ROUND"&&round_checks==0) actual^=18'd1;
    if(actual!==expected) $fatal(1,"[ROUND] directed raw=%0d",raw);
    round_checks++;
  endtask
  initial begin
    if($value$plusargs("INJECT_MMSE3=%s",inject)) begin
      if(inject!="GRAM"&&inject!="SUM"&&inject!="ROUND") $fatal(1,"[WIDTHS] unknown injection");
    end
    lam='1;
    for(int j=0;j<9;j++) begin h_re[j]=18'sh20000;h_im[j]=18'sh20000;w_re[j]=0;w_im[j]=0;end
    for(int k=0;k<3;k++) begin x_re[k]=0;x_im[k]=0;end
    deposit_operands;#1;
    // Peak diagonal = 7*2^34-1, including unsigned full-code lambda.
    check_gram(0,0);
    if(128'(dut.gram(0,0,0))!==((128'd7<<34)-1)) $fatal(1,"[WIDTHS] diagonal peak witness");
    // Every corner of the twelve independent H coordinates in two columns:
    // includes both signs of imaginary extrema and cancellation/partial corners.
    for(int mask=0;mask<4096;mask++) begin
      for(int k=0;k<3;k++) begin
        h_re[3*k]=hcorner(1'(mask>>(4*k)));h_im[3*k]=hcorner(1'(mask>>(4*k+1)));
        h_re[3*k+1]=hcorner(1'(mask>>(4*k+2)));h_im[3*k+1]=hcorner(1'(mask>>(4*k+3)));
      end
      deposit_operands;#1;check_gram(0,1);check_gram(1,0);check_gram(0,0);check_gram(1,1);
    end
    // All corners of six independent full signed64 weights and six signed18
    // observations. Replicate each row so all six stored output sums are checked.
    for(int mask=0;mask<4096;mask++) begin
      for(int k=0;k<3;k++) begin
        x_re[k]=hcorner(1'(mask>>(2*k)));x_im[k]=hcorner(1'(mask>>(2*k+1)));
        for(int row=0;row<3;row++) begin
          w_re[3*row+k]=wcorner(1'(mask>>(6+2*k)));
          w_im[3*row+k]=wcorner(1'(mask>>(7+2*k)));
        end
      end
      deposit_operands;check_sum;
      for(int row=0;row<3;row++) begin check_round(128'(dut.yr[row]));check_round(128'(dut.yi[row]));end
    end
    // Adjacent values around half-LSB ties, zero, and both saturation thresholds.
    for(int q=-2;q<=2;q++) for(int delta=-1;delta<=1;delta++)
      check_round((128'(q)<<<24)+128'sd8388608+128'(delta));
    for(int delta=-1;delta<=1;delta++) begin
      check_round((128'sd131071<<<24)+128'sd8388608+128'(delta));
      check_round((-128'sd131073<<<24)+128'sd8388608+128'(delta));
    end
    check_round((128'sd1<<<83)-1);check_round(-(128'sd1<<<83));
    $display("PASS MMSE3 WIDTH DIRECTED GRAM_WIDTH=%0d SUM_WIDTH=%0d gram=%0d sum=%0d round=%0d",GRAM_WIDTH,SUM_WIDTH,gram_checks,sum_checks,round_checks);
    $finish;
  end
endmodule
