// 128-bit operand-level reference of every sized LMS/NLMS intermediate (+CHECK_WIDTHS).
// The history comes from the original pin files and the reciprocal/shift are recomputed from
// it; weights, c and dl are the DUT's own registers (checked one stage later against this
// recomputation). This is not an independent adaptive model: the full fixed-model scoreboards
// above check outputs and weights.
localparam int LW_N=1<<LOG2N;
logic signed [127:0] lw_hr[0:LW_N-1],lw_hi[0:LW_N-1];
logic signed [127:0] lw_pr[0:LW_N-1],lw_pi[0:LW_N-1],lw_dr[0:LW_N-1],lw_di[0:LW_N-1],lw_wr[0:LW_N-1],lw_wi[0:LW_N-1];
logic signed [127:0] lw_sum_re,lw_sum_im,lw_e_re,lw_e_im,lw_c_re,lw_c_im,lw_d_re,lw_d_im;
logic signed [127:0] lw_peak[0:8];
longint lw_count[0:10];
int lw_inputs=0;
bit lw_weight_pending=0;
initial if($bits(dut.pred_raw_re)!=PRED_WIDTH||$bits(dut.error_raw_re)!=ERROR_WIDTH||$bits(dut.step_raw_re)!=STEP_WIDTH
    ||$bits(dut.step_sum_re)!=STEP_WIDTH||$bits(dut.c_re)!=COEFF_WIDTH||$bits(dut.step_round_re)!=COEFF_WIDTH
    ||$bits(dut.dl_re[0])!=DELTA_WIDTH||$bits(dut.tap_re[0])!=DELTA_WIDTH||$bits(dut.weight_next_re[0])!=WEIGHT_WIDTH
    ||$bits(dut.dump_raw_re)!=DUMP_WIDTH||$bits(dut.pr_re[0])!=53||$bits(dut.product_re[0])!=53||$bits(dut.sum_re)!=53+LOG2N
    ||$bits(dut.wr[0])!=34||$bits(dut.k)!=28)
  $fatal(1,"[WIDTH] unexpected LMS physical widths");
function automatic logic signed [127:0] lw_sat(input logic signed [127:0] v,input int bits);
  logic signed [127:0] hi,lo;
  hi=(128'sd1<<(bits-1))-1;lo=-(128'sd1<<(bits-1));return v>hi?hi:v<lo?lo:v;
endfunction
task automatic lw_track(input int stage,input logic signed [127:0] value);
  logic signed [127:0] magnitude;
  magnitude=value<0?-value:value;if(magnitude>lw_peak[stage])lw_peak[stage]=magnitude;
endtask
function automatic logic signed [127:0] lw_inject(input logic signed [127:0] v,input string tag);
  return $test$plusargs({"INJECT_WIDTH_",tag})?v+1:v;
endfunction
always @(posedge clk)begin
  if(rst==RESET_ACTIVE)begin
    for(int k=0;k<11;k++)lw_count[k]=0;
    for(int k=0;k<9;k++)lw_peak[k]=0;
    for(int k=0;k<LW_N;k++)begin lw_hr[k]=0;lw_hi[k]=0;end
    lw_inputs=0;lw_weight_pending=0;
  end else if(scoring&&$test$plusargs("CHECK_WIDTHS"))begin
    if(lw_weight_pending)begin
      for(int k=0;k<cfg_taps_v;k++)begin
        if(128'(dut.wr[k])!==lw_wr[k]||128'(dut.wi[k])!==lw_wi[k])$fatal(1,"[WEIGHT] LMS sat34 weight register differs");
        lw_count[9]+=2;
      end
      lw_weight_pending=0;
    end
    if(dut.take)begin
      if(lw_inputs>=in_total)$fatal(1,"[WIDTH] extra input");
      if(s_re!==18'(in_xre[lw_inputs])||s_im!==18'(in_xim[lw_inputs])||s_dre!==18'(in_dre[lw_inputs])||s_dim!==18'(in_dim[lw_inputs]))
        $fatal(1,"[WIDTH] input differs from original pin file");
      // The DUT shifts all lanes; only the first T are consumed.
      for(int k=LW_N-1;k>0;k--)begin lw_hr[k]=lw_hr[k-1];lw_hi[k]=lw_hi[k-1];end
      lw_hr[0]=in_xre[lw_inputs];lw_hi[0]=in_xim[lw_inputs];lw_d_re=in_dre[lw_inputs];lw_d_im=in_dim[lw_inputs];
      lw_inputs++;
    end
    if(dut.state==dut.PRODUCT)begin
      for(int k=0;k<LW_N;k++)begin
        if(128'(dut.h_re[k])!==lw_hr[k]||128'(dut.h_im[k])!==lw_hi[k])$fatal(1,"[PREDICT] LMS history differs from pin files");
        lw_pr[k]=0;lw_pi[k]=0;
        if(k<cfg_taps_v)begin
          lw_pr[k]=128'(dut.wr[k])*lw_hr[k]+128'(dut.wi[k])*lw_hi[k];
          lw_pi[k]=128'(dut.wr[k])*lw_hi[k]-128'(dut.wi[k])*lw_hr[k];
          if(lw_inject(128'(dut.product_re[k]),"PRODUCT")!==lw_pr[k]||128'(dut.product_im[k])!==lw_pi[k])
            $fatal(1,"[PRODUCT] LMS conj(w) h product differs");
          lw_track(0,lw_pr[k]);lw_track(0,lw_pi[k]);lw_count[0]+=2;
        end
      end
    end
    if(dut.state==dut.SUM)begin
      lw_sum_re=0;lw_sum_im=0;
      for(int k=0;k<LW_N;k++)begin
        if(128'(dut.pr_re[k])!==lw_pr[k]||128'(dut.pr_im[k])!==lw_pi[k])$fatal(1,"[PRODUCT] LMS product register differs");
        lw_sum_re+=lw_pr[k];lw_sum_im+=lw_pi[k];
      end
      if(128'(dut.tree_re)!==lw_sum_re||128'(dut.tree_im)!==lw_sum_im)$fatal(1,"[PREDICT] LMS prediction tree differs");
      lw_track(1,lw_sum_re);lw_track(1,lw_sum_im);lw_count[1]+=2;
    end
    if(dut.state==dut.ERROR)begin
      logic signed [127:0] raw_re,raw_im,pred_re,pred_im,err_re,err_im;
      if(128'(dut.sum_re)!==lw_sum_re||128'(dut.sum_im)!==lw_sum_im||128'(dut.d_re)!==lw_d_re||128'(dut.d_im)!==lw_d_im)
        $fatal(1,"[PREDICT] LMS prediction sum/desired register differs");
      raw_re=lw_sum_re+(128'sd1<<29);raw_im=lw_sum_im+(128'sd1<<29);
      pred_re=lw_sat(raw_re>>>30,18);pred_im=lw_sat(raw_im>>>30,18);
      if(lw_inject(128'(dut.pred_raw_re),"PREDICT")!==raw_re||128'(dut.pred_raw_im)!==raw_im
          ||128'(dut.pred_round_re)!==(raw_re>>>30)||128'(dut.pred_round_im)!==(raw_im>>>30)
          ||128'(dut.pred_re)!==pred_re||128'(dut.pred_im)!==pred_im)
        $fatal(1,"[PREDICT] LMS prediction rounding differs");
      err_re=lw_d_re-pred_re;err_im=lw_d_im-pred_im;
      if(lw_inject(128'(dut.error_raw_re),"ERROR")!==err_re||128'(dut.error_raw_im)!==err_im)
        $fatal(1,"[ERROR] LMS error difference differs");
      lw_e_re=lw_sat(err_re,18);lw_e_im=lw_sat(err_im,18);
      lw_track(2,raw_re);lw_track(2,raw_im);lw_track(3,err_re);lw_track(3,err_im);lw_count[2]+=2;lw_count[3]+=2;
    end
    if(dut.state==dut.COEFF)begin
      logic signed [127:0] k_expected,raw_re,raw_im,sum_re,sum_im,power,total;
      int bits,mantissa,reciprocal,shift_expected;
      if(128'(dut.e_re)!==lw_e_re||128'(dut.e_im)!==lw_e_im)$fatal(1,"[ERROR] LMS sat18 error register differs");
      if(cfg_nlms_v)begin
        power=0;for(int k=0;k<cfg_taps_v;k++)power+=lw_hr[k]*lw_hr[k]+lw_hi[k]*lw_hi[k];
        total=power+cfg_eps_v;bits=0;for(int b=0;b<127;b++)if((total>>>b)!=0)bits=b+1;
        mantissa=int'(total>>>(bits-10));reciprocal=(524288+mantissa/2)/mantissa;
        k_expected=128'(cfg_mu_v)*reciprocal;shift_expected=bits-9;
      end else begin k_expected=cfg_mu_v;shift_expected=12;end
      // Configuration contract used by the width proof.
      if(k_expected<1||k_expected>(128'sd1<<27)||shift_expected<1||shift_expected>27+LOG2N||(!cfg_nlms_v&&k_expected>(128'sd1<<17)))
        $fatal(1,"[STEP] LMS step/shift outside the width contract");
      if(128'(dut.k)!==k_expected||int'(dut.shift)!=shift_expected)$fatal(1,"[STEP] LMS step or shift register differs");
      raw_re=k_expected*lw_e_re;raw_im=-(k_expected*lw_e_im);
      sum_re=raw_re+(128'sd1<<(shift_expected-1));sum_im=raw_im+(128'sd1<<(shift_expected-1));
      if(lw_inject(128'(dut.step_raw_re),"STEP")!==raw_re||128'(dut.step_raw_im)!==raw_im
          ||128'(dut.step_sum_re)!==sum_re||128'(dut.step_sum_im)!==sum_im)
        $fatal(1,"[STEP] LMS step-error product differs");
      lw_c_re=sum_re>>>shift_expected;lw_c_im=sum_im>>>shift_expected;
      if(lw_inject(128'(dut.step_round_re),"COEFF")!==lw_c_re||128'(dut.step_round_im)!==lw_c_im)
        $fatal(1,"[COEFF] LMS rounded coefficient differs");
      lw_track(4,sum_re);lw_track(4,sum_im);lw_track(4,raw_re);lw_track(4,raw_im);lw_track(5,lw_c_re);lw_track(5,lw_c_im);
      lw_count[4]+=2;
    end
    if(dut.state==dut.TAP)begin
      if(128'(dut.c_re)!==lw_c_re||128'(dut.c_im)!==lw_c_im)$fatal(1,"[COEFF] LMS coefficient register differs");
      lw_count[5]+=2;
      for(int k=0;k<cfg_taps_v;k++)begin
        lw_dr[k]=lw_hr[k]*lw_c_re-lw_hi[k]*lw_c_im;lw_di[k]=lw_hr[k]*lw_c_im+lw_hi[k]*lw_c_re;
        if(lw_inject(128'(dut.tap_re[k]),"DELTA")!==lw_dr[k]||128'(dut.tap_im[k])!==lw_di[k])
          $fatal(1,"[DELTA] LMS tap update product differs");
        lw_track(6,lw_dr[k]+16);lw_track(6,lw_di[k]+16);lw_count[6]+=2;
      end
    end
    if(dut.state==dut.WEIGHT)begin
      for(int k=0;k<cfg_taps_v;k++)begin
        logic signed [127:0] rr,ri,nr,ni;
        if(128'(dut.dl_re[k])!==lw_dr[k]||128'(dut.dl_im[k])!==lw_di[k])$fatal(1,"[DELTA] LMS tap update register differs");
        rr=(lw_dr[k]+16)>>>5;ri=(lw_di[k]+16)>>>5;nr=128'(dut.wr[k])+rr;ni=128'(dut.wi[k])+ri;
        if(128'(dut.delta_round_re[k])!==rr||128'(dut.delta_round_im[k])!==ri)$fatal(1,"[DELTA] LMS round-5 update differs");
        if(lw_inject(128'(dut.weight_next_re[k]),"WEIGHT")!==nr||128'(dut.weight_next_im[k])!==ni)
          $fatal(1,"[WEIGHT] LMS weight sum before sat34 differs");
        lw_wr[k]=lw_sat(nr,34);lw_wi[k]=lw_sat(ni,34);
        lw_track(7,nr);lw_track(7,ni);lw_count[7]+=2;lw_count[8]+=2;
      end
      lw_weight_pending=1;
    end
    if(dut.state==dut.DUMP&&(!w_valid||w_ready))begin
      if(dut.dump==dut.taps)begin
        for(int k=0;k<LW_N;k++)begin lw_hr[k]=0;lw_hi[k]=0;end
      end else begin
        logic signed [127:0] wre,wim;
        wre=128'(dut.wr[int'(dut.dump)]);wim=128'(dut.wi[int'(dut.dump)]);
        if(128'(dut.dump_re)!==wre||128'(dut.dump_im)!==wim||lw_inject(128'(dut.dump_raw_re),"DUMP")!==wre+(128'sd1<<14)
            ||128'(dut.dump_raw_im)!==wim+(128'sd1<<14)||128'(dut.dump_round_re)!==((wre+(128'sd1<<14))>>>15)
            ||128'(dut.dump_round_im)!==((wim+(128'sd1<<14))>>>15))
          $fatal(1,"[DUMP] LMS weight dump rounding differs");
        lw_track(8,wre+(128'sd1<<14));lw_track(8,wim+(128'sd1<<14));lw_count[10]+=2;
      end
    end
  end
end
task automatic check_lms_widths();
  longint s,t,expected[0:10];
  s=in_total;t=cfg_taps_v;
  expected='{2*s*t,2*s,2*s,2*s,2*s,2*s,2*s*t,2*s*t,2*s*t,2*s*t,2*longint'(w_total)};
  if(lw_inputs!=in_total||lw_weight_pending)$fatal(1,"[WIDTH] incomplete LMS width observations");
  for(int k=0;k<11;k++)if(lw_count[k]!=expected[k])$fatal(1,"[WIDTH] LMS width observation count %0d: %0d/%0d",k,lw_count[k],expected[k]);
  $display("PASS LMS WIDTHS: %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",
    lw_count[0],lw_count[1],lw_count[2],lw_count[3],lw_count[4],lw_count[5],lw_count[6],lw_count[7],lw_count[8],lw_count[9],lw_count[10],
    lw_peak[0],lw_peak[1],lw_peak[2],lw_peak[3],lw_peak[4],lw_peak[5],lw_peak[6],lw_peak[7],lw_peak[8]);
endtask
