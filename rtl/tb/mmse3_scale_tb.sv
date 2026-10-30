`timescale 1ns/1ps
module mmse3_scale_tb;
  parameter bit RESET_ACTIVE=1;
  parameter int SCALE_WIDTH=145;
  logic clk=0,rst=!RESET_ACTIVE;
  logic [23:0] r_control=24'd8388608;
  logic [7:0] shift_control=8;
  logic cfg_ready,configured,s_ready,m_valid,m_last,error;
  logic signed [17:0] m_re,m_im;
  int checks=0;
  mmse3 #(.RESET_ACTIVE(RESET_ACTIVE),.SCALE_WIDTH(SCALE_WIDTH)) dut(
    .clk(clk),.rst(rst),.cfg_valid(1'b0),.cfg_last(1'b0),.cfg_re(18'sd0),.cfg_im(18'sd0),.cfg_lambda(34'd0),.cfg_ready(cfg_ready),.configured(configured),
    .s_valid(1'b0),.s_last(1'b0),.s_re(18'sd0),.s_im(18'sd0),.s_ready(s_ready),.m_valid(m_valid),.m_last(m_last),.m_re(m_re),.m_im(m_im),.m_ready(1'b0),.error(error));
  `include "mmse3_scale_check.svh"
  initial begin force dut.r=r_control;force dut.shift=shift_control;force dut.cstate=dut.C_IDLE;end
  initial begin
    for(int sh=8;sh<=134;sh++) for(int ri=0;ri<4;ri++) for(int vi=0;vi<5;vi++) begin
      logic signed [105:0] v;
      shift_control=8'(sh);
      case(ri) 0:r_control=24'd4194304;1:r_control=24'd4194305;2:r_control=24'd8388607;3:r_control=24'd8388608;endcase
      case(vi) 0:v=-(106'sd1<<<105);1:v=(106'sd1<<<105)-1;2:v=-1;3:v=0;4:v=1;endcase
      #1;scale_compare(v,0);scale_compare(v,1);checks+=2;
    end
    // Exact signed64 boundaries through the real rounding function.
    r_control=24'd8388608;shift_control=48;
    for(int d=-2;d<=2;d++) begin
      #1;scale_compare((106'sd1<<<64)+106'(d),0);
      scale_compare(-(106'sd1<<<64)+106'(d),1);checks+=2;
    end
    check_scale_updates();
    $display("PASS WIDTH DIRECTED scale checks=%0d",checks);$finish;
  end
endmodule
