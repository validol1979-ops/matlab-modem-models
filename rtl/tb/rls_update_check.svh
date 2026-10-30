// 128-bit operand-level reference, separate from the full fixed-model scoreboards.
localparam int UPD_N=1<<LOG2N;
logic signed [127:0] upd_gr[0:UPD_N-1],upd_gi[0:UPD_N-1],upd_wr[0:UPD_N-1],upd_wi[0:UPD_N-1];
logic signed [127:0] upd_tr[0:UPD_N-1],upd_ti[0:UPD_N-1],upd_pr[0:UPD_N-1],upd_pi[0:UPD_N-1];
logic signed [127:0] upd_peak[0:4];
int upd_count[0:8];
bit upd_cov_pending=0,upd_weight_pending=0;
int upd_cov_row=0;
initial if($bits(dut.gain_raw_re[0])!=GAIN_WIDTH||$bits(dut.update_raw_re[0])!=UPDATE_WIDTH
    ||$bits(dut.weight_next_re[0])!=WEIGHT_WIDTH||$bits(dut.pt_raw_re[0])!=PT_WIDTH||$bits(dut.cov_raw_re[0])!=COV_WIDTH
    ||$bits(dut.cov_delta_re[0])!=47)$fatal(1,"[WIDTH] unexpected RLS update physical widths");
function automatic logic signed [127:0] upd_sat(input logic signed [127:0] v,input int bits);
  logic signed [127:0] hi,lo;
  hi=(128'sd1<<(bits-1))-1;lo=-(128'sd1<<(bits-1));return v>hi?hi:v<lo?lo:v;
endfunction
task automatic upd_track(input int stage,input logic signed [127:0] value);
  logic signed [127:0] magnitude;
  magnitude=value<0?-value:value;if(magnitude>upd_peak[stage])upd_peak[stage]=magnitude;
endtask
always @(posedge clk)begin
  if(rst==RESET_ACTIVE)begin
    for(int k=0;k<9;k++)upd_count[k]=0;
    for(int k=0;k<5;k++)upd_peak[k]=0;
    upd_cov_pending=0;upd_weight_pending=0;
  end else if(scoring&&$test$plusargs("CHECK_UPDATES"))begin
    if(upd_cov_pending)begin
      for(int j=upd_cov_row;j<cfg_taps_v;j++)begin
        if(128'(dut.pr[upd_cov_row][j])!==upd_pr[j]||128'(dut.pr[j][upd_cov_row])!==upd_pr[j])
          $fatal(1,"[COV] RLS real covariance register differs");
        if(j==upd_cov_row)begin
          if(dut.pi[j][j]!==44'sd0)$fatal(1,"[COV] RLS diagonal not real");
          upd_count[8]+=2;
        end else begin
          if(128'(dut.pi[upd_cov_row][j])!==upd_pi[j]||128'(dut.pi[j][upd_cov_row])!==128'(44'(-upd_pi[j])))
            $fatal(1,"[COV] RLS imaginary covariance register differs");
          upd_count[8]+=4;
        end
      end
      upd_cov_pending=0;
    end
    if(dut.state==dut.GAIN)begin
      if($isunknown({dut.r,dut.shift})||dut.r<24'd4194304||dut.r>24'd8388608)
        $fatal(1,"[GAIN] RLS reciprocal outside normalized contract");
      for(int i=0;i<cfg_taps_v;i++)begin
        logic signed [127:0] re,im,observed;
        re=128'(dut.ur[i])*128'($signed({1'b0,dut.r}));im=128'(dut.ui[i])*128'($signed({1'b0,dut.r}));
        observed=128'(dut.gain_raw_re[i]);if($test$plusargs("INJECT_UPDATE_GAIN"))observed++;
        if(observed!==re||128'(dut.gain_raw_im[i])!==im)$fatal(1,"[GAIN] RLS gain product differs");
        upd_gr[i]=upd_sat(rls_sat_rv(re,dut.shift-7'd15),40);upd_gi[i]=upd_sat(rls_sat_rv(im,dut.shift-7'd15),40);
        upd_track(0,re);upd_track(0,im);upd_count[0]+=2;
      end
    end
    if(dut.state==dut.WEIGHT)begin
      for(int i=0;i<cfg_taps_v;i++)begin
        logic signed [127:0] re,im,rr,ri,nr,ni,observed;
        if(128'(dut.gr[i])!==upd_gr[i]||128'(dut.gi[i])!==upd_gi[i])$fatal(1,"[GAIN] RLS gain register differs");
        upd_count[1]+=2;
        re=128'(dut.gr[i])*128'(dut.e_re)+128'(dut.gi[i])*128'(dut.e_im);
        im=128'(dut.gi[i])*128'(dut.e_re)-128'(dut.gr[i])*128'(dut.e_im);
        rr=(re+(128'sd1<<14))>>>15;ri=(im+(128'sd1<<14))>>>15;
        observed=128'(dut.update_raw_re[i]);if($test$plusargs("INJECT_UPDATE_PRODUCT"))observed++;
        if(observed!==re||128'(dut.update_raw_im[i])!==im||128'(dut.update_round_re[i])!==rr||128'(dut.update_round_im[i])!==ri)
          $fatal(1,"[PRODUCT] RLS weight product/round differs");
        nr=128'(dut.wr[i])+rr;ni=128'(dut.wi[i])+ri;
        observed=128'(dut.weight_next_re[i]);if($test$plusargs("INJECT_UPDATE_WEIGHT"))observed++;
        if(observed!==nr||128'(dut.weight_next_im[i])!==ni)$fatal(1,"[WEIGHT] RLS weight sum differs");
        upd_wr[i]=upd_sat(nr,34);upd_wi[i]=upd_sat(ni,34);
        upd_track(1,re);upd_track(1,im);upd_track(2,nr);upd_track(2,ni);
        upd_count[2]+=2;upd_count[3]+=2;
      end
      upd_weight_pending=1;
    end
    if(dut.state==dut.PT)begin
      if(upd_weight_pending)begin
        for(int i=0;i<cfg_taps_v;i++)begin
          if(128'(dut.wr[i])!==upd_wr[i]||128'(dut.wi[i])!==upd_wi[i])$fatal(1,"[WEIGHT] RLS weight register differs");
          upd_count[4]+=2;
        end
        upd_weight_pending=0;
      end
      for(int j=int'(dut.row);j<cfg_taps_v;j++)begin
        logic signed [127:0] re,im,rr,ri,observed;
        re=128'(dut.gr[dut.row])*128'(dut.ur[j])+128'(dut.gi[dut.row])*128'(dut.ui[j]);
        im=128'(dut.gi[dut.row])*128'(dut.ur[j])-128'(dut.gr[dut.row])*128'(dut.ui[j]);
        rr=(re+(128'sd1<<29))>>>30;ri=(im+(128'sd1<<29))>>>30;
        observed=128'(dut.pt_raw_re[j]);if($test$plusargs("INJECT_UPDATE_PT"))observed++;
        if(observed!==re||128'(dut.pt_raw_im[j])!==im||128'(dut.pt_round_re[j])!==rr||128'(dut.pt_round_im[j])!==ri)
          $fatal(1,"[PT] RLS outer product/round differs");
        upd_tr[j]=upd_sat(rr,46);upd_ti[j]=upd_sat(ri,46);
        upd_track(3,re);upd_track(3,im);upd_count[5]+=2;
      end
    end
    if(dut.state==dut.PN)begin
      for(int j=int'(dut.row);j<cfg_taps_v;j++)begin
        if(128'(dut.tr[j])!==upd_tr[j]||128'(dut.ti[j])!==upd_ti[j])$fatal(1,"[PT] RLS outer product register differs");
        upd_count[6]+=2;
        for(int component=0;component<(j==int'(dut.row)?1:2);component++)begin
          logic signed [127:0] delta,value,rounded,observed_delta,observed_raw,observed_round;
          if(component==0)begin
            delta=128'(dut.pr[dut.row][j])-128'(dut.tr[j]);
            observed_delta=128'(dut.cov_delta_re[j]);observed_raw=128'(dut.cov_raw_re[j]);observed_round=128'(dut.cov_round_re[j]);
          end else begin
            delta=128'(dut.pi[dut.row][j])-128'(dut.ti[j]);
            observed_delta=128'(dut.cov_delta_im[j]);observed_raw=128'(dut.cov_raw_im[j]);observed_round=128'(dut.cov_round_im[j]);
          end
          value=delta*128'($signed({1'b0,dut.invl}));rounded=(value+(128'sd1<<29))>>>30;
          if($test$plusargs("INJECT_UPDATE_COV"))observed_raw++;
          if(observed_delta!==delta||observed_raw!==value||observed_round!==rounded)$fatal(1,"[COV] RLS covariance delta/product/round differs");
          if(component==0)upd_pr[j]=upd_sat(rounded,44);else upd_pi[j]=upd_sat(rounded,44);
          upd_track(4,value);upd_count[7]++;
        end
      end
      upd_cov_row=int'(dut.row);upd_cov_pending=1;
    end
  end
end
task automatic check_rls_updates();
  int s,t;
  s=in_total;t=cfg_taps_v;
  if(upd_cov_pending||upd_weight_pending||upd_count[0]!=2*s*t||upd_count[1]!=2*s*t||upd_count[2]!=2*s*t
      ||upd_count[3]!=2*s*t||upd_count[4]!=2*s*t||upd_count[5]!=s*t*(t+1)||upd_count[6]!=s*t*(t+1)
      ||upd_count[7]!=s*t*t||upd_count[8]!=2*s*t*t)$fatal(1,"[WIDTH] incomplete RLS update observations");
  $display("PASS RLS UPDATES: %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",
    upd_count[0],upd_count[1],upd_count[2],upd_count[3],upd_count[4],upd_count[5],upd_count[6],upd_count[7],upd_count[8],
    upd_peak[0],upd_peak[1],upd_peak[2],upd_peak[3],upd_peak[4]);
endtask
