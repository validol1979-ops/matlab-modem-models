// Forced independent stored codes, not a claim of H/reset reachability.
`timescale 1ns/1ps
module mmse_n_norm_back_tb;
  parameter int N=2;
  parameter bit RESET_ACTIVE=1;
  parameter int NORM_WIDTH=70,WEIGHT_WIDTH=87,MULT_NUM_WIDTH=65;
  parameter int BACK_PRODUCT_WIDTH=107,BACK_ACC_WIDTH=106+$clog2(N);
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  mmse_n #(.N(N),.RESET_ACTIVE(RESET_ACTIVE),.NORM_WIDTH(NORM_WIDTH),.WEIGHT_WIDTH(WEIGHT_WIDTH),
    .MULT_NUM_WIDTH(MULT_NUM_WIDTH),.BACK_PRODUCT_WIDTH(BACK_PRODUCT_WIDTH),.BACK_ACC_WIDTH(BACK_ACC_WIDTH)) dut
    (.clk(clk),.rst(rst),.cfg_valid(1'b0),.cfg_last(1'b0),.cfg_re(18'sd0),.cfg_im(18'sd0),.cfg_lambda(34'd0),
     .cfg_ready(),.configured(),.s_valid(1'b0),.s_last(1'b0),.s_re(18'sd0),.s_im(18'sd0),.s_ready(),
     .m_valid(),.m_last(),.m_re(),.m_im(),.m_ready(1'b1),.error());
  int pattern=-1,checks=0;
  string injection;
  logic signed [6:0] exponent;
  logic signed [BACK_ACC_WIDTH-1:0] seed_re,seed_im;
  // Genvar indices and literal force RHS avoid dynamic array-force semantics.
  for(genvar q=1;q<N;q++) begin : g_codes
    always @(pattern) begin
      if(pattern[0]) force dut.ar[q]=34'sh1ffffffff;else force dut.ar[q]=34'sh200000000;
      if(pattern[1]) force dut.ai[q]=34'sh1ffffffff;else force dut.ai[q]=34'sh200000000;
      if(pattern[2]) force dut.br[N*q]=72'sh7fffffffffffffffff;else force dut.br[N*q]=72'sh800000000000000000;
      if(pattern[3]) force dut.bi[N*q]=72'sh7fffffffffffffffff;else force dut.bi[N*q]=72'sh800000000000000000;
    end
  end
  always @(pattern) begin
    if(pattern[0]) begin
      force dut.gr[0]=40'sh7fffffffff;force dut.gi[0]=40'sh7fffffffff;
      force dut.ar[0]=34'sh1ffffffff;force dut.ai[0]=34'sh1ffffffff;
    end else begin
      force dut.gr[0]=40'sh8000000000;force dut.gi[0]=40'sh8000000000;
      force dut.ar[0]=34'sh200000000;force dut.ai[0]=34'sh200000000;
    end
    if(pattern[1]) begin force dut.br[0]=72'sh7fffffffffffffffff;force dut.bi[0]=72'sh7fffffffffffffffff;end
    else begin force dut.br[0]=72'sh800000000000000000;force dut.bi[0]=72'sh800000000000000000;end
  end
  function automatic logic signed [191:0] shift_round(input logic signed [191:0] v,input int s);
    if(s>0) return (v+(192'sd1<<<(s-1)))>>>s;
    return v<<<(-s);
  endfunction
  task automatic equal_raw(input string tag,input logic signed [191:0] actual,expected);
    logic signed [191:0] observed;
    observed=actual;
    if(injection==tag) observed+=1;
    if(observed!==expected) $fatal(1,"[%s] directed norm/back arithmetic actual=%0d expected=%0d",tag,observed,expected);
    checks++;
  endtask
  initial begin
    logic signed [191:0] g,b,a,ai,x,xi,pr,pi,er,ei;
    if($value$plusargs("INJECT_NORM_BACK=%s",injection)) begin end
    repeat(3) @(negedge clk);rst=!RESET_ACTIVE;
    force dut.escale=exponent;
    for(int v=0;v<16;v++) begin
      @(negedge clk);pattern=v;#1;
      g=v[0]?(192'sd1<<<39)-1:-(192'sd1<<<39);
      b=v[1]?(192'sd1<<<71)-1:-(192'sd1<<<71);
      a=v[0]?(192'sd1<<<33)-1:-(192'sd1<<<33);
      ai=v[1]?(192'sd1<<<33)-1:-(192'sd1<<<33);
      x=v[2]?(192'sd1<<<71)-1:-(192'sd1<<<71);
      xi=v[3]?(192'sd1<<<71)-1:-(192'sd1<<<71);
      for(int e=-30;e<=8;e++) begin
        exponent=7'(e);#1;
        equal_raw("NORM",192'(dut.norm_re),shift_round(g,e));
        equal_raw("NORM",192'(dut.norm_im),shift_round(g,e));
        equal_raw("WEIGHT",192'(dut.weight_re),shift_round(b,e+15));
        equal_raw("WEIGHT",192'(dut.weight_im),shift_round(b,e+15));
        equal_raw("NORM",192'(dut.fits(138'(dut.norm_re),34)),
          192'(shift_round(g,e)>=-(192'sd1<<<33)&&shift_round(g,e)<(192'sd1<<<33)));
        equal_raw("WEIGHT",192'(dut.fits(138'(dut.weight_re),64)),
          192'(shift_round(b,e+15)>=-(192'sd1<<<63)&&shift_round(b,e+15)<(192'sd1<<<63)));
      end
      equal_raw("MULT",192'(dut.mult_num_re),a<<<30);
      equal_raw("MULT",192'(dut.mult_num_im),-(a<<<30));
      // Execute the real C_BACK FSM over all N-1 terms; no accumulator force.
      @(negedge clk);force dut.ck=0;force dut.cj=0;force dut.cc=1;
      er=b<<<30;ei=b<<<30;seed_re=BACK_ACC_WIDTH'(er);seed_im=BACK_ACC_WIDTH'(ei);
      force dut.acc_re=seed_re;force dut.acc_im=seed_im;#1;
      release dut.ck;release dut.cj;release dut.cc;release dut.acc_re;release dut.acc_im;
      force dut.cstate=dut.C_BACK;#1;release dut.cstate;#1;
      pr=a*x-ai*xi;pi=a*xi+ai*x;
      for(int t=1;t<N;t++) begin
        equal_raw("ACC",192'(dut.acc_re),er);equal_raw("ACC",192'(dut.acc_im),ei);
        equal_raw("PRODUCT",192'(dut.back_product_re),pr);equal_raw("PRODUCT",192'(dut.back_product_im),pi);
        er-=pr;ei-=pi;
        equal_raw("ACC",192'(dut.back_re),er);equal_raw("ACC",192'(dut.back_im),ei);
        @(negedge clk);#1;
      end
      equal_raw("ACC",192'(dut.acc_re),er);equal_raw("ACC",192'(dut.acc_im),ei);
      if(int'(dut.cc)!=N) $fatal(1,"[ACC] directed C_BACK term count");
      force dut.cstate=dut.C_IDLE;#1;release dut.cstate;
    end
    $display("PASS WIDTH DIRECTED norm_back n=%0d checks=%0d",N,checks);$finish;
  end
  initial begin #1000000;$fatal(1,"directed norm/back timeout");end
endmodule
