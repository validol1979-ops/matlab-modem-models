// Operand-level shadow arithmetic: original-file history, actual bounded w/P/u state.
// The existing fixed-model scoreboards independently check the adaptive outputs/weights.
longint dot_hr[0:(1<<LOG2N)-1],dot_hi[0:(1<<LOG2N)-1];
logic signed [127:0] dot_pred_re=0,dot_pred_im=0,dot_den=0;
logic signed [127:0] dot_pred_peak=0,dot_matrix_peak=0,dot_q_peak=0;
int dot_inputs=0,dot_predictions=0,dot_registers=0,dot_matrices=0,dot_quadratics=0,dot_denominators=0;
initial if($bits(dut.sum_re)!=PRED_WIDTH||$bits(dut.acc_re)!=DOT_WIDTH||$bits(dut.q_sum)!=Q_WIDTH)
  $fatal(1,"[WIDTH] unexpected physical RLS dot widths");
function automatic logic signed [127:0] dot_abs(input logic signed [127:0] x);
  return x<0?-x:x;
endfunction
always @(posedge clk)begin
  if(rst==RESET_ACTIVE)begin
    dot_inputs=0;dot_predictions=0;dot_registers=0;dot_matrices=0;dot_quadratics=0;dot_denominators=0;
    dot_pred_peak=0;dot_matrix_peak=0;dot_q_peak=0;
    for(int j=0;j<(1<<LOG2N);j++)begin dot_hr[j]=0;dot_hi[j]=0;end
  end else if(scoring&&$test$plusargs("CHECK_DOT"))begin
    if(dut.take)begin
      if(dot_inputs>=in_total)$fatal(1,"[PREDICT] extra RLS sample");
      if(s_re!==18'(in_xre[dot_inputs])||s_im!==18'(in_xim[dot_inputs])||s_dre!==18'(in_dre[dot_inputs])
          ||s_dim!==18'(in_dim[dot_inputs])||s_last!==1'(in_last[dot_inputs]))$fatal(1,"[PREDICT] RLS sample differs from original file");
      for(int j=cfg_taps_v-1;j>0;j--)begin dot_hr[j]=dot_hr[j-1];dot_hi[j]=dot_hi[j-1];end
      dot_hr[0]=in_xre[dot_inputs];dot_hi[0]=in_xim[dot_inputs];dot_inputs++;
    end
    if(dut.state==dut.PRODUCT)begin
      logic signed [127:0] observed_re,observed_im;
      dot_pred_re=0;dot_pred_im=0;
      for(int j=0;j<cfg_taps_v;j++)begin
        if(64'(dut.h_re[j])!==dot_hr[j]||64'(dut.h_im[j])!==dot_hi[j])$fatal(1,"[PREDICT] RLS history differs");
        dot_pred_re+=128'(dut.wr[j])*128'(dot_hr[j])+128'(dut.wi[j])*128'(dot_hi[j]);
        dot_pred_im+=128'(dut.wr[j])*128'(dot_hi[j])-128'(dut.wi[j])*128'(dot_hr[j]);
      end
      observed_re=128'(dut.acc_re);observed_im=128'(dut.acc_im);
      if($test$plusargs("INJECT_DOT_PREDICT"))observed_re++;
      if(observed_re!==dot_pred_re||observed_im!==dot_pred_im)$fatal(1,"[PREDICT] RLS raw prediction differs");
      if(dot_abs(dot_pred_re)>dot_pred_peak)dot_pred_peak=dot_abs(dot_pred_re);
      if(dot_abs(dot_pred_im)>dot_pred_peak)dot_pred_peak=dot_abs(dot_pred_im);
      dot_predictions+=2;
    end
    if(dut.state==dut.ERROR)begin
      logic signed [127:0] observed;
      observed=128'(dut.sum_re);
      if($test$plusargs("INJECT_DOT_REGISTER"))observed++;
      if(observed!==dot_pred_re||128'(dut.sum_im)!==dot_pred_im)$fatal(1,"[REGISTER] RLS prediction register truncated");
      dot_registers+=2;
    end
    if(dut.state==dut.U)begin
      logic signed [127:0] re,im,observed;
      re=0;im=0;
      for(int j=0;j<cfg_taps_v;j++)begin
        re+=128'(dut.pr[dut.row][j])*128'(dot_hr[j])-128'(dut.pi[dut.row][j])*128'(dot_hi[j]);
        im+=128'(dut.pr[dut.row][j])*128'(dot_hi[j])+128'(dut.pi[dut.row][j])*128'(dot_hr[j]);
      end
      observed=128'(dut.acc_re);
      if($test$plusargs("INJECT_DOT_MATRIX"))observed++;
      if(observed!==re||128'(dut.acc_im)!==im)$fatal(1,"[MATRIX] RLS raw matrix row differs");
      if(dot_abs(re)>dot_matrix_peak)dot_matrix_peak=dot_abs(re);
      if(dot_abs(im)>dot_matrix_peak)dot_matrix_peak=dot_abs(im);
      dot_matrices+=2;
    end
    if(dut.state==dut.Q)begin
      logic signed [127:0] q,rounded,observed;
      q=0;
      for(int j=0;j<cfg_taps_v;j++)q+=128'(dot_hr[j])*128'(dut.ur[j])+128'(dot_hi[j])*128'(dut.ui[j]);
      observed=128'(dut.q_sum);
      if($test$plusargs("INJECT_DOT_QUADRATIC"))observed++;
      if(observed!==q)$fatal(1,"[QUADRATIC] RLS raw hH-u differs");
      if(dot_abs(q)>dot_q_peak)dot_q_peak=dot_abs(q);
      rounded=(q+(128'sd1<<14))>>>15;
      if(rounded>(128'sd1<<49)-1)rounded=(128'sd1<<49)-1;
      if(rounded<-(128'sd1<<49))rounded=-(128'sd1<<49);
      dot_den=rounded+128'(cfg_lambda_v);dot_quadratics++;
    end
    if(dut.state==dut.RECIP&&dut.norm_start)begin
      logic signed [127:0] observed;
      observed=128'(dut.dden);
      if($test$plusargs("INJECT_DOT_DENOMINATOR"))observed++;
      if(observed!==dot_den)$fatal(1,"[DENOMINATOR] RLS denominator differs");
      dot_denominators++;
    end
    if(dut.state==dut.DUMP&&(!w_valid||w_ready)&&dut.dump==dut.taps)
      for(int j=0;j<(1<<LOG2N);j++)begin dot_hr[j]=0;dot_hi[j]=0;end
  end
end
task automatic check_rls_dot();
  if(dot_inputs!=in_total||dot_predictions!=2*in_total||dot_registers!=2*in_total||dot_matrices!=2*cfg_taps_v*in_total
      ||dot_quadratics!=in_total||dot_denominators!=in_total)$fatal(1,"[WIDTH] incomplete RLS raw dot observations");
  $display("PASS RLS DOT: %0d %0d %0d %0d %0d %0d %0d %0d %0d",dot_inputs,dot_predictions,dot_registers,dot_matrices,
    dot_quadratics,dot_denominators,dot_pred_peak,dot_matrix_peak,dot_q_peak);
endtask
