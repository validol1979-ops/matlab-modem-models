// Direct arithmetic proof on arbitrary register codes, without clocks/adaptation.
// These corners are not claimed to be reachable from a legal RLS reset trajectory.
`timescale 1ns/1ps
module rls_dot_bounds_tb;
  parameter int LOG2N=2,PRED_WIDTH=53+LOG2N,DOT_WIDTH=63+LOG2N,Q_WIDTH=67+LOG2N;
  parameter bit RESET_ACTIVE=1;
  localparam int N=1<<LOG2N;
  logic clk=0,rst=RESET_ACTIVE;
  rls_filter #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE),.PRED_WIDTH(PRED_WIDTH),.DOT_WIDTH(DOT_WIDTH),.Q_WIDTH(Q_WIDTH)) dut
    (.clk(clk),.rst(rst),.cfg_valid(1'b0),.cfg_taps((LOG2N+1)'(0)),.cfg_p0(44'd0),.cfg_lambda(30'd1),.cfg_invl(32'd0),
     .cfg_ready(),.configured(),.s_valid(1'b0),.s_last(1'b0),.s_re(18'sd0),.s_im(18'sd0),.s_dre(18'sd0),.s_dim(18'sd0),
     .s_ready(),.m_valid(),.m_last(),.m_pre(),.m_pim(),.m_ere(),.m_eim(),.m_ready(1'b1),
     .w_valid(),.w_last(),.w_re(),.w_im(),.w_ready(1'b1),.error());
  int pred_checks=0,matrix_checks=0,q_checks=0;
  int selected_kind=0;
  logic [(LOG2N>0?LOG2N:1)-1:0] selected_row='0;
  logic signed [127:0] a,b,c,d,re,im,observed;
  // Force overrides the clocked owners legally; the DUT clock never has an edge here.
  initial begin
    force dut.taps=(LOG2N+1)'(N);
    force dut.row=selected_row;
    force dut.state=selected_kind==0?dut.PRODUCT:selected_kind==1?dut.U:dut.Q;
  end
  for(genvar j=0;j<N;j++)begin:g_lane
    initial begin
      force dut.h_re[j]=18'(c);force dut.h_im[j]=18'(d);
      force dut.wr[j]=34'(a);force dut.wi[j]=34'(b);force dut.ur[j]=48'(a);force dut.ui[j]=48'(b);
    end
    for(genvar i=0;i<N;i++)begin:g_row
      initial begin force dut.pr[i][j]=44'(a);force dut.pi[i][j]=44'(b);end
    end
  end
  initial begin
    #1;
    for(int corner=0;corner<16;corner++)begin
      c=(corner&4)?128'sd131071:-128'sd131072;d=(corner&8)?128'sd131071:-128'sd131072;
      for(int kind=0;kind<3;kind++)begin
        int w;
        w=kind==0?34:kind==1?44:48;
        a=(corner&1)?(128'sd1<<(w-1))-1:-(128'sd1<<(w-1));
        b=(corner&2)?(128'sd1<<(w-1))-1:-(128'sd1<<(w-1));
        selected_kind=kind;
        if(kind==0)begin
          #1;re=N*(a*c+b*d);im=N*(a*d-b*c);
          if(128'(dut.acc_re)!==re||128'(dut.acc_im)!==im)$fatal(1,"[ARITHMETIC] directed RLS prediction corner");
          if(128'(PRED_WIDTH'(re))!==re||128'(PRED_WIDTH'(im))!==im)$fatal(1,"[ARITHMETIC] directed prediction storage width");
          pred_checks+=2;
        end else if(kind==1)begin
          for(int i=0;i<N;i++)begin
            selected_row=(LOG2N>0?LOG2N:1)'(i);#1;re=N*(a*c-b*d);im=N*(a*d+b*c);
            if(128'(dut.acc_re)!==re||128'(dut.acc_im)!==im)$fatal(1,"[ARITHMETIC] directed RLS matrix corner");
            matrix_checks+=2;
          end
        end else begin
          #1;re=N*(a*c+b*d);observed=128'(dut.q_sum);
          if($test$plusargs("INJECT_DIRECTED"))observed++;
          if(observed!==re)$fatal(1,"[ARITHMETIC] directed RLS quadratic corner");
          q_checks++;
        end
      end
    end
    if(pred_checks!=32||matrix_checks!=32*N||q_checks!=16)$fatal(1,"[ARITHMETIC] incomplete RLS corners");
    $display("PASS RLS DOT BOUNDS: %0d %0d %0d",pred_checks,matrix_checks,q_checks);$finish;
  end
endmodule
