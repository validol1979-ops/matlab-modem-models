// Interval corners of every sized LMS/NLMS intermediate through test forces: no clocks,
// no adaptation and no reset-reachability claim. Corners are the full stored codes
// (signed18 history/desired/error/prediction, sat34 weights) or the proven contract
// ranges (k <= 2^27, 1 <= shift <= 27+LOG2N, |c| <= 2^43, |h c| <= 2^61).
`timescale 1ns/1ps
module lms_width_bounds_tb;
  parameter int LOG2N=0;
  parameter bit RESET_ACTIVE=1;
  parameter string RECIP_FILE="rtl/common/mem/lms_reciprocal.mem";
  parameter int PRED_WIDTH=53+LOG2N,ERROR_WIDTH=19,STEP_WIDTH=46,COEFF_WIDTH=45,DELTA_WIDTH=63,WEIGHT_WIDTH=58,DUMP_WIDTH=35;
  localparam int N=1<<LOG2N;
  localparam logic signed [127:0] W_MIN=-(128'sd1<<33),W_MAX=(128'sd1<<33)-1,X_MIN=-128'sd131072,X_MAX=128'sd131071;
  localparam logic signed [127:0] P_MIN=-(128'sd1<<51)+(128'sd1<<17),P_MAX=128'sd1<<51;
  localparam logic signed [127:0] C_LIM=128'sd1<<43,D_LIM=128'sd1<<61;
  logic clk=0,rst=RESET_ACTIVE;
  logic signed [127:0] wre=0,wim=0,hre=0,him=0,pre=0,pim=0,sre=0,sim=0,dre=0,dim=0,ere=0,eim=0,cre=0,cim=0,lre=0,lim=0;
  logic [27:0] kval=28'd1;
  logic [6:0] shval=7'd1;
  logic signed [127:0] a,b,x,y,observed;
  int product_checks=0,pred_checks=0,error_checks=0,step_checks=0,tap_checks=0,weight_checks=0,dump_checks=0;
  lms_filter #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE),.RECIP_FILE(RECIP_FILE),
      .PRED_WIDTH(PRED_WIDTH),.ERROR_WIDTH(ERROR_WIDTH),.STEP_WIDTH(STEP_WIDTH),.COEFF_WIDTH(COEFF_WIDTH),
      .DELTA_WIDTH(DELTA_WIDTH),.WEIGHT_WIDTH(WEIGHT_WIDTH),.DUMP_WIDTH(DUMP_WIDTH)) dut
    (.clk(clk),.rst(rst),.cfg_valid(1'b0),.cfg_nlms(1'b0),.cfg_taps((LOG2N+1)'(0)),.cfg_mu(18'd0),.cfg_eps(34'd0),
     .cfg_ready(),.configured(),.s_valid(1'b0),.s_last(1'b0),.s_re(18'sd0),.s_im(18'sd0),.s_dre(18'sd0),.s_dim(18'sd0),
     .s_ready(),.m_valid(),.m_last(),.m_pre(),.m_pim(),.m_ere(),.m_eim(),.m_ready(1'b1),
     .w_valid(),.w_last(),.w_re(),.w_im(),.w_ready(1'b1),.error());
  initial begin
    force dut.taps=(LOG2N+1)'(N);force dut.state=dut.IDLE;force dut.dump='0;
    force dut.sum_re=(53+LOG2N)'(sre);force dut.sum_im=(53+LOG2N)'(sim);
    force dut.d_re=18'(dre);force dut.d_im=18'(dim);force dut.e_re=18'(ere);force dut.e_im=18'(eim);
    force dut.k=kval;force dut.shift=shval;force dut.c_re=COEFF_WIDTH'(cre);force dut.c_im=COEFF_WIDTH'(cim);
  end
  for(genvar n=0;n<N;n++)begin:g_lane
    initial begin
      force dut.wr[n]=34'(wre);force dut.wi[n]=34'(wim);force dut.h_re[n]=18'(hre);force dut.h_im[n]=18'(him);
      force dut.pr_re[n]=53'(pre);force dut.pr_im[n]=53'(pim);
      force dut.dl_re[n]=DELTA_WIDTH'(lre);force dut.dl_im[n]=DELTA_WIDTH'(lim);
    end
  end
  function automatic logic signed [127:0] sat(input logic signed [127:0] v,input int bits);
    logic signed [127:0] hi,lo;
    hi=(128'sd1<<(bits-1))-1;lo=-(128'sd1<<(bits-1));return v>hi?hi:v<lo?lo:v;
  endfunction
  initial begin
    #1;
    for(int corner=0;corner<16;corner++)begin
      wre=(corner&1)?W_MAX:W_MIN;wim=(corner&2)?W_MAX:W_MIN;hre=(corner&4)?X_MAX:X_MIN;him=(corner&8)?X_MAX:X_MIN;#1;
      a=wre*hre+wim*him;b=wre*him-wim*hre;
      for(int n=0;n<N;n++)begin
        if(128'(dut.product_re[n])!==a||128'(dut.product_im[n])!==b)$fatal(1,"[ARITHMETIC] conj(w) h corner");
        product_checks+=2;
      end
    end
    for(int corner=0;corner<4;corner++)begin
      pre=(corner&1)?P_MAX:P_MIN;pim=(corner&2)?P_MAX:P_MIN;sre=N*pre;sim=N*pim;#1;
      x=sre+(128'sd1<<29);y=sim+(128'sd1<<29);
      if(128'(dut.tree_re)!==sre||128'(dut.tree_im)!==sim||128'(dut.pred_raw_re)!==x||128'(dut.pred_raw_im)!==y
          ||128'(dut.pred_round_re)!==(x>>>30)||128'(dut.pred_round_im)!==(y>>>30)
          ||128'(dut.pred_re)!==sat(x>>>30,18)||128'(dut.pred_im)!==sat(y>>>30,18))
        $fatal(1,"[ARITHMETIC] prediction tree/rounding corner");
      pred_checks+=8;
    end
    for(int corner=0;corner<16;corner++)begin
      dre=(corner&1)?X_MAX:X_MIN;dim=(corner&2)?X_MAX:X_MIN;
      a=(corner&4)?X_MAX:X_MIN;b=(corner&8)?X_MAX:X_MIN;sre=a<<<30;sim=b<<<30;#1;
      if(128'(dut.pred_re)!==a||128'(dut.pred_im)!==b||128'(dut.error_raw_re)!==dre-a||128'(dut.error_raw_im)!==dim-b)
        $fatal(1,"[ARITHMETIC] error corner");
      error_checks+=2;
    end
    for(int corner=0;corner<24;corner++)begin
      int sh;
      kval=(corner&1)?28'd134217728:28'd1;ere=(corner&2)?X_MAX:X_MIN;eim=(corner&4)?X_MAX:X_MIN;
      sh=corner/8==0?1:corner/8==1?12:27+LOG2N;shval=7'(sh);#1;
      a=128'(kval)*ere;b=-(128'(kval)*eim);x=a+(128'sd1<<(sh-1));y=b+(128'sd1<<(sh-1));
      observed=128'(dut.step_sum_re);if($test$plusargs("INJECT_DIRECTED_WIDTH"))observed++;
      if(128'(dut.step_raw_re)!==a||128'(dut.step_raw_im)!==b||observed!==x||128'(dut.step_sum_im)!==y
          ||128'(dut.step_round_re)!==(x>>>sh)||128'(dut.step_round_im)!==(y>>>sh))
        $fatal(1,"[ARITHMETIC] step-error corner");
      step_checks+=6;
    end
    for(int corner=0;corner<16;corner++)begin
      hre=(corner&1)?X_MAX:X_MIN;him=(corner&2)?X_MAX:X_MIN;cre=(corner&4)?C_LIM:-C_LIM;cim=(corner&8)?C_LIM:-C_LIM;#1;
      a=hre*cre-him*cim;b=hre*cim+him*cre;
      for(int n=0;n<N;n++)begin
        if(128'(dut.tap_re[n])!==a||128'(dut.tap_im[n])!==b)$fatal(1,"[ARITHMETIC] tap update corner");
        tap_checks+=2;
      end
    end
    for(int corner=0;corner<16;corner++)begin
      lre=(corner&1)?D_LIM:-D_LIM;lim=(corner&2)?D_LIM:-D_LIM;wre=(corner&4)?W_MAX:W_MIN;wim=(corner&8)?W_MAX:W_MIN;#1;
      a=(lre+16)>>>5;b=(lim+16)>>>5;
      for(int n=0;n<N;n++)begin
        if(128'(dut.delta_round_re[n])!==a||128'(dut.delta_round_im[n])!==b
            ||128'(dut.weight_next_re[n])!==wre+a||128'(dut.weight_next_im[n])!==wim+b)
          $fatal(1,"[ARITHMETIC] weight update corner");
        weight_checks+=4;
      end
    end
    for(int corner=0;corner<4;corner++)begin
      wre=(corner&1)?W_MAX:W_MIN;wim=(corner&2)?W_MAX:W_MIN;#1;
      x=wre+(128'sd1<<14);y=wim+(128'sd1<<14);
      if(128'(dut.dump_raw_re)!==x||128'(dut.dump_raw_im)!==y||128'(dut.dump_round_re)!==(x>>>15)
          ||128'(dut.dump_round_im)!==(y>>>15))$fatal(1,"[ARITHMETIC] dump corner");
      dump_checks+=6;
    end
    if(product_checks!=32*N||pred_checks!=32||error_checks!=32||step_checks!=144||tap_checks!=32*N
        ||weight_checks!=64*N||dump_checks!=24)$fatal(1,"[ARITHMETIC] incomplete LMS width corners");
    $display("PASS LMS WIDTH BOUNDS: %0d %0d %0d %0d %0d %0d %0d",product_checks,pred_checks,error_checks,step_checks,
      tap_checks,weight_checks,dump_checks);
    $finish;
  end
endmodule
