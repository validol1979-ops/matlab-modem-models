// Arbitrary operand codes, no clocks/adaptation and no reset-reachability claim.
`timescale 1ns/1ps
module rls_update_bounds_tb;
  parameter int LOG2N=0,GAIN_WIDTH=71,UPDATE_WIDTH=59,WEIGHT_WIDTH=44,PT_WIDTH=89,COV_WIDTH=79;
  parameter bit RESET_ACTIVE=1;
  localparam int N=1<<LOG2N;
  logic clk=0,rst=RESET_ACTIVE;
  logic [(LOG2N>0?LOG2N:1)-1:0] selected_row=0;
  logic signed [127:0] g0=0,g1=0,u0=0,u1=0,e0=0,e1=0,wval=0,pval=0,tval=0;
  logic [23:0] rvalue=24'd4194304;
  logic [31:0] invl_value=0;
  logic signed [127:0] re,im,rr,ri,delta,observed;
  int gain_checks=0,update_checks=0,pt_checks=0,cov_checks=0;
  rls_filter #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE),.GAIN_WIDTH(GAIN_WIDTH),.UPDATE_WIDTH(UPDATE_WIDTH),
      .WEIGHT_WIDTH(WEIGHT_WIDTH),.PT_WIDTH(PT_WIDTH),.COV_WIDTH(COV_WIDTH)) dut
    (.clk(clk),.rst(rst),.cfg_valid(1'b0),.cfg_taps((LOG2N+1)'(0)),.cfg_p0(44'd0),.cfg_lambda(30'd1),.cfg_invl(32'd0),
     .cfg_ready(),.configured(),.s_valid(1'b0),.s_last(1'b0),.s_re(18'sd0),.s_im(18'sd0),.s_dre(18'sd0),.s_dim(18'sd0),
     .s_ready(),.m_valid(),.m_last(),.m_pre(),.m_pim(),.m_ere(),.m_eim(),.m_ready(1'b1),
     .w_valid(),.w_last(),.w_re(),.w_im(),.w_ready(1'b1),.error());
  initial begin
    force dut.taps=(LOG2N+1)'(N);force dut.row=selected_row;force dut.state=dut.IDLE;
    force dut.r=rvalue;force dut.invl=invl_value;force dut.e_re=18'(e0);force dut.e_im=18'(e1);
  end
  for(genvar k=0;k<N;k++)begin:g_lane
    initial begin
      force dut.h_re[k]=18'sd0;force dut.h_im[k]=18'sd0;
      force dut.gr[k]=40'(g0);force dut.gi[k]=40'(g1);force dut.ur[k]=48'(u0);force dut.ui[k]=48'(u1);
      force dut.wr[k]=34'(wval);force dut.wi[k]=34'(wval);force dut.tr[k]=46'(tval);force dut.ti[k]=46'(tval);
    end
    for(genvar i=0;i<N;i++)begin:g_row
      initial begin force dut.pr[i][k]=44'(pval);force dut.pi[i][k]=44'(pval);end
    end
  end
  initial begin
    #1;
    for(int corner=0;corner<8;corner++)begin
      u0=(corner&1)?(128'sd1<<47)-1:-(128'sd1<<47);u1=(corner&2)?(128'sd1<<47)-1:-(128'sd1<<47);
      rvalue=(corner&4)?24'd8388608:24'd4194304;#1;
      re=u0*128'($signed({1'b0,rvalue}));im=u1*128'($signed({1'b0,rvalue}));
      for(int k=0;k<N;k++)begin
        if(128'(dut.gain_raw_re[k])!==re||128'(dut.gain_raw_im[k])!==im)$fatal(1,"[ARITHMETIC] gain corner");
        gain_checks+=2;
      end
    end
    for(int corner=0;corner<32;corner++)begin
      g0=(corner&1)?(128'sd1<<39)-1:-(128'sd1<<39);g1=(corner&2)?(128'sd1<<39)-1:-(128'sd1<<39);
      e0=(corner&4)?128'sd131071:-128'sd131072;e1=(corner&8)?128'sd131071:-128'sd131072;
      wval=(corner&16)?(128'sd1<<33)-1:-(128'sd1<<33);#1;
      re=g0*e0+g1*e1;im=g1*e0-g0*e1;rr=(re+(128'sd1<<14))>>>15;ri=(im+(128'sd1<<14))>>>15;
      for(int k=0;k<N;k++)begin
        if(128'(dut.update_raw_re[k])!==re||128'(dut.update_raw_im[k])!==im||128'(dut.update_round_re[k])!==rr
            ||128'(dut.update_round_im[k])!==ri||128'(dut.weight_next_re[k])!==wval+rr||128'(dut.weight_next_im[k])!==wval+ri)
          $fatal(1,"[ARITHMETIC] weight update corner");
        update_checks+=6;
      end
    end
    for(int corner=0;corner<16;corner++)begin
      g0=(corner&1)?(128'sd1<<39)-1:-(128'sd1<<39);g1=(corner&2)?(128'sd1<<39)-1:-(128'sd1<<39);
      u0=(corner&4)?(128'sd1<<47)-1:-(128'sd1<<47);u1=(corner&8)?(128'sd1<<47)-1:-(128'sd1<<47);
      re=g0*u0+g1*u1;im=g1*u0-g0*u1;rr=(re+(128'sd1<<29))>>>30;ri=(im+(128'sd1<<29))>>>30;
      for(int i=0;i<N;i++)begin
        selected_row=(LOG2N>0?LOG2N:1)'(i);#1;
        for(int k=0;k<N;k++)begin
          if(128'(dut.pt_raw_re[k])!==re||128'(dut.pt_raw_im[k])!==im||128'(dut.pt_round_re[k])!==rr||128'(dut.pt_round_im[k])!==ri)
            $fatal(1,"[ARITHMETIC] outer product corner");
          pt_checks+=4;
        end
      end
    end
    for(int corner=0;corner<8;corner++)begin
      pval=(corner&1)?(128'sd1<<43)-1:-(128'sd1<<43);tval=(corner&2)?(128'sd1<<45)-1:-(128'sd1<<45);
      invl_value=(corner&4)?32'hffffffff:32'd0;delta=pval-tval;re=delta*128'($signed({1'b0,invl_value}));rr=(re+(128'sd1<<29))>>>30;
      for(int i=0;i<N;i++)begin
        selected_row=(LOG2N>0?LOG2N:1)'(i);#1;
        for(int k=0;k<N;k++)begin
          observed=128'(dut.cov_raw_re[k]);if($test$plusargs("INJECT_DIRECTED_UPDATE"))observed++;
          if(128'(dut.cov_delta_re[k])!==delta||128'(dut.cov_delta_im[k])!==delta||observed!==re||128'(dut.cov_raw_im[k])!==re
              ||128'(dut.cov_round_re[k])!==rr||128'(dut.cov_round_im[k])!==rr)$fatal(1,"[ARITHMETIC] covariance corner");
          cov_checks+=6;
        end
      end
    end
    if(gain_checks!=16*N||update_checks!=192*N||pt_checks!=64*N*N||cov_checks!=48*N*N)$fatal(1,"[ARITHMETIC] incomplete update corners");
    $display("PASS RLS UPDATE BOUNDS: %0d %0d %0d %0d",gain_checks,update_checks,pt_checks,cov_checks);$finish;
  end
endmodule
