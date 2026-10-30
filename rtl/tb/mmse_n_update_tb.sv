`timescale 1ns/1ps
module mmse_n_update_tb;
  localparam int N=2;
  parameter bit RESET_ACTIVE=1;
  parameter int A_PRODUCT_WIDTH=83,B_PRODUCT_WIDTH=121,A_UPDATE_WIDTH=53,B_UPDATE_WIDTH=91;
  logic clk=0,rst=!RESET_ACTIVE;
  logic cfg_ready,configured,s_ready,m_valid,m_last,error;
  logic signed [17:0] m_re,m_im;
  int checks=0;
  mmse_n #(.N(N),.RESET_ACTIVE(RESET_ACTIVE),.A_PRODUCT_WIDTH(A_PRODUCT_WIDTH),.B_PRODUCT_WIDTH(B_PRODUCT_WIDTH),
    .A_UPDATE_WIDTH(A_UPDATE_WIDTH),.B_UPDATE_WIDTH(B_UPDATE_WIDTH)) dut(
    .clk(clk),.rst(rst),.cfg_valid(1'b0),.cfg_last(1'b0),.cfg_re(18'sd0),.cfg_im(18'sd0),.cfg_lambda(34'd0),.cfg_ready(cfg_ready),.configured(configured),
    .s_valid(1'b0),.s_last(1'b0),.s_re(18'sd0),.s_im(18'sd0),.s_ready(s_ready),.m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(1'b0),.error(error));
  `include "mmse_n_update_check.svh"
  initial begin force dut.cstate=dut.C_IDLE;force dut.ck=0;force dut.ci=1;force dut.cj=1;end
  task set_codes(input int mask);
    if(mask&1) force dut.mr[1]=48'sh7fffffffffff;else force dut.mr[1]=48'sh800000000000;
    if(mask&2) force dut.mi[1]=48'sh7fffffffffff;else force dut.mi[1]=48'sh800000000000;
    if(mask&4) begin force dut.ar[1]=34'sh1ffffffff;force dut.br[1]=72'sh7fffffffffffffffff;end
    else begin force dut.ar[1]=34'sh200000000;force dut.br[1]=72'sh800000000000000000;end
    if(mask&8) begin force dut.ai[1]=34'sh1ffffffff;force dut.bi[1]=72'sh7fffffffffffffffff;end
    else begin force dut.ai[1]=34'sh200000000;force dut.bi[1]=72'sh800000000000000000;end
    if(mask&16) begin force dut.ar[3]=34'sh1ffffffff;force dut.br[3]=72'sh7fffffffffffffffff;end
    else begin force dut.ar[3]=34'sh200000000;force dut.br[3]=72'sh800000000000000000;end
    if(mask&32) begin force dut.ai[3]=34'sh1ffffffff;force dut.bi[3]=72'sh7fffffffffffffffff;end
    else begin force dut.ai[3]=34'sh200000000;force dut.bi[3]=72'sh800000000000000000;end
  endtask
  initial begin
    for(int mask=0;mask<64;mask++) begin
      set_codes(mask);#1;update_compare(0,192'(dut.mr[1]),192'(dut.mi[1]),192'(dut.ar[1]),192'(dut.ai[1]),192'(dut.ar[3]),192'(dut.ai[3]),192'(dut.ua_re),192'(dut.ua_im),192'(dut.upd_a_re),192'(dut.upd_a_im));update_compare(1,192'(dut.mr[1]),192'(dut.mi[1]),192'(dut.br[1]),192'(dut.bi[1]),192'(dut.br[3]),192'(dut.bi[3]),192'(dut.ub_re),192'(dut.ub_im),192'(dut.upd_b_re),192'(dut.upd_b_im));checks+=8;
    end
    // Half-up ties and neighbouring codes with non-rail stored operands.
    force dut.mr[1]=48'sd1;force dut.mi[1]=48'sd0;
    force dut.ar[3]=34'sd0;force dut.ai[3]=34'sd0;force dut.br[3]=72'sd0;force dut.bi[3]=72'sd0;
    force dut.ar[1]=34'sd536870912;force dut.ai[1]=-34'sd536870912;
    force dut.br[1]=72'sd536870912;force dut.bi[1]=-72'sd536870912;
    #1;update_compare(0,192'(dut.mr[1]),192'(dut.mi[1]),192'(dut.ar[1]),192'(dut.ai[1]),192'(dut.ar[3]),192'(dut.ai[3]),192'(dut.ua_re),192'(dut.ua_im),192'(dut.upd_a_re),192'(dut.upd_a_im));update_compare(1,192'(dut.mr[1]),192'(dut.mi[1]),192'(dut.br[1]),192'(dut.bi[1]),192'(dut.br[3]),192'(dut.bi[3]),192'(dut.ub_re),192'(dut.ub_im),192'(dut.upd_b_re),192'(dut.upd_b_im));checks+=8;
    force dut.ar[1]=34'sd536870911;force dut.ai[1]=-34'sd536870911;
    force dut.br[1]=72'sd536870911;force dut.bi[1]=-72'sd536870911;
    #1;update_compare(0,192'(dut.mr[1]),192'(dut.mi[1]),192'(dut.ar[1]),192'(dut.ai[1]),192'(dut.ar[3]),192'(dut.ai[3]),192'(dut.ua_re),192'(dut.ua_im),192'(dut.upd_a_re),192'(dut.upd_a_im));update_compare(1,192'(dut.mr[1]),192'(dut.mi[1]),192'(dut.br[1]),192'(dut.bi[1]),192'(dut.br[3]),192'(dut.bi[3]),192'(dut.ub_re),192'(dut.ub_im),192'(dut.upd_b_re),192'(dut.upd_b_im));checks+=8;
    force dut.ar[1]=34'sd536870913;force dut.ai[1]=-34'sd536870913;
    force dut.br[1]=72'sd536870913;force dut.bi[1]=-72'sd536870913;
    #1;update_compare(0,192'(dut.mr[1]),192'(dut.mi[1]),192'(dut.ar[1]),192'(dut.ai[1]),192'(dut.ar[3]),192'(dut.ai[3]),192'(dut.ua_re),192'(dut.ua_im),192'(dut.upd_a_re),192'(dut.upd_a_im));update_compare(1,192'(dut.mr[1]),192'(dut.mi[1]),192'(dut.br[1]),192'(dut.bi[1]),192'(dut.br[3]),192'(dut.bi[3]),192'(dut.ub_re),192'(dut.ub_im),192'(dut.upd_b_re),192'(dut.upd_b_im));checks+=8;
    check_scale_updates();$display("PASS WIDTH DIRECTED updates checks=%0d",checks);$finish;
  end
endmodule
