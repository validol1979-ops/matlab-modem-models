// 128-bit operand-level reference of the narrowed OM-LSA gain arithmetic (+CHECK_GAIN_WIDTHS).
// Every raw product, its rounding and every register written from it are recomputed in 128 bits
// from the DUT's own operands, at each real per-bin step; the outputs themselves are scored
// independently against the fixed model. +INJECT_GAIN_<TAG> corrupts one observation.
initial if($bits(dut.gain.recip_round)!=RECIP_WIDTH||$bits(dut.gain.gamma_raw)!=GAMMA_WIDTH||$bits(dut.gain.gamma_round)!=GAMMA_WIDTH
    ||$bits(dut.gain.xi_raw)!=XI_WIDTH||$bits(dut.gain.v_raw)!=V_WIDTH||$bits(dut.gain.g1_raw)!=G1_WIDTH
    ||$bits(dut.gain.t_raw)!=T_WIDTH||$bits(dut.gain.a_raw)!=A_WIDTH||$bits(dut.gain.out_raw_re)!=OUT_WIDTH
    ||$bits(dut.gain.gg_raw)!=GG_WIDTH||$bits(dut.gain.prev_raw)!=PREV_WIDTH)
  $fatal(1,"[WIDTH] unexpected OM-LSA gain physical widths");
localparam logic [127:0] GW_GMAX=128'h7fffffff;
logic [127:0] gw_peak[0:9];
int gw_count[0:3];                              // bin_count, reciprocal evaluations, register checks, prev writes
bit gw_pending=0,gw_prev=0;
logic [127:0] gw_prev_value;
int gw_reg=0,gw_bin=0;
logic [127:0] gw_value,gw_value_im;
function automatic logic [127:0] gw_rnd(input logic [127:0] v,input int s);
  return s==0 ? v:(v+(128'd1<<(s-1)))>>s;
endfunction
function automatic logic signed [127:0] gw_srnd(input logic signed [127:0] v);
  return (v+(128'sd1<<<15))>>>16;
endfunction
function automatic logic [127:0] gw_cap(input logic [127:0] v);return v>GW_GMAX ? GW_GMAX:v;endfunction
task automatic gw_track(input int stage,input logic signed [127:0] value);
  logic [127:0] magnitude;
  magnitude=value<0 ? -value:value;if(magnitude>gw_peak[stage])gw_peak[stage]=magnitude;
endtask
function automatic logic [127:0] gw_obs(input logic [127:0] value,input string tag);
  return $test$plusargs({"INJECT_GAIN_",tag}) ? value+1:value;
endfunction
// R(u) for the current rs and ROM word, as the 128-bit form did.
task automatic gw_recip(output logic [127:0] value);
  logic [127:0] rounded;
  logic [6:0] shift;
  shift=7'(dut.gain.rs)-7'd17;rounded=gw_rnd(128'(dut.gain.recip_q),int'(shift));
  if(gw_obs(128'(dut.gain.recip_round),"RECIP")!==rounded)$fatal(1,"[RECIP] OM-LSA reciprocal rounding differs");
  value=dut.gain.rs==6'd17 ? 128'(dut.gain.recip_q):128'(17'(rounded));
  if(128'(dut.gain.recip_value)!==value)$fatal(1,"[RECIP] OM-LSA reciprocal value differs");
  gw_track(0,128'(dut.gain.recip_q));gw_count[1]++;
endtask
always @(posedge clk)begin
  if(rst==RESET_ACTIVE)begin
    for(int k=0;k<10;k++)gw_peak[k]=0;
    for(int k=0;k<4;k++)gw_count[k]=0;
    gw_pending=0;gw_prev=0;
  end else if(scoring&&$test$plusargs("CHECK_GAIN_WIDTHS"))begin
    logic [127:0] raw,rounded,observed;
    logic [6:0] shift;
    // The register written by the previous step.
    if(gw_pending)begin
      case(gw_reg)
        0:observed=128'(dut.gain.gamma);
        1:observed=128'(dut.gain.xi);
        2:observed=128'(dut.gain.w);
        3:observed=128'(dut.gain.v);
        4:observed=128'(dut.gain.g1)|(128'(dut.gain.t)<<17);
        5:observed=128'(dut.gain.p);
        6:observed={107'd0,dut.gain.a};
        default:observed=128'(dut.gain.m_re);
      endcase
      if(gw_obs(observed,"REGISTER")!==gw_value)$fatal(1,"[REGISTER] OM-LSA gain register %0d differs",gw_reg);
      if(gw_reg==7&&128'(dut.gain.m_im)!==gw_value_im)$fatal(1,"[REGISTER] OM-LSA gain output im differs");
      if(gw_reg==7&&gw_prev)begin
        if(128'(dut.gain.prev[gw_bin])!==gw_prev_value)$fatal(1,"[REGISTER] OM-LSA prev register differs");
        gw_count[3]++;gw_prev=0;
      end
      gw_count[2]++;gw_pending=0;
    end
    case(dut.gain.state)
      dut.gain.G2:begin
        if(dut.gain.power>49'(1)<<47)$fatal(1,"[CONTRACT] OM-LSA power above 2^47");
        raw=128'(dut.gain.power)*128'(dut.gain.rn[dut.gain.k]);
        shift=dut.gain.zn[dut.gain.k]-1'b1;rounded=gw_rnd(raw,int'(shift));
        if(gw_obs(128'(dut.gain.gamma_raw),"GAMMA")!==raw||128'(dut.gain.gamma_round)!==rounded)
          $fatal(1,"[GAMMA] OM-LSA gamma product/round differs");
        gw_track(1,raw);gw_count[0]++;gw_value=gw_cap(rounded);gw_reg=0;gw_pending=1;
      end
      dut.gain.G3:begin
        logic [127:0] excess;
        if(dut.gain.alpha>17'd65536)$fatal(1,"[CONTRACT] OM-LSA alpha above 65536");
        excess=dut.gain.gamma>31'd65536 ? 128'(dut.gain.gamma)-128'd65536:128'd0;
        raw=128'(dut.gain.alpha)*128'(dut.gain.prev[dut.gain.k])+(128'd65536-128'(dut.gain.alpha))*excess;
        rounded=gw_rnd(raw,16);
        if(gw_obs(128'(dut.gain.xi_raw),"XI")!==raw||128'(dut.gain.xi_round)!==rounded)$fatal(1,"[XI] OM-LSA xi product/round differs");
        gw_track(2,raw);gw_value=gw_cap(rounded)==0 ? 128'd1:gw_cap(rounded);gw_reg=1;gw_pending=1;
      end
      dut.gain.G6:begin
        gw_recip(raw);gw_value=128'(17'(128'd65536-raw));gw_reg=2;gw_pending=1;
      end
      dut.gain.G7:begin
        raw=128'(dut.gain.gamma)*128'(dut.gain.w);rounded=gw_rnd(raw,16);
        if(gw_obs(128'(dut.gain.v_raw),"V")!==raw||128'(dut.gain.v_round)!==rounded)$fatal(1,"[V] OM-LSA v product/round differs");
        gw_track(3,raw);gw_value=gw_cap(rounded);gw_reg=3;gw_pending=1;
      end
      dut.gain.G10:begin
        logic [127:0] g1,t;
        raw=128'(dut.gain.w)*128'(dut.gain.tf_q);rounded=gw_rnd(raw,12);
        if(gw_obs(128'(dut.gain.g1_raw),"G1")!==raw||128'(dut.gain.g1_next)!==rounded)$fatal(1,"[G1] OM-LSA G1 product/round differs");
        gw_track(4,raw);g1=rounded<128'd3277 ? 128'd3277:rounded>128'd65536 ? 128'd65536:rounded;
        raw=(128'd65536+128'(dut.gain.xi))*128'(dut.gain.te_q);rounded=gw_rnd(raw,18);
        if(gw_obs(128'(dut.gain.t_raw),"T")!==raw||128'(dut.gain.t_round)!==rounded)$fatal(1,"[T] OM-LSA t product/round differs");
        gw_track(5,raw);t=gw_cap(rounded);gw_value=g1|(t<<17);gw_reg=4;gw_pending=1;
      end
      dut.gain.G13:begin
        gw_recip(raw);gw_value=raw;gw_reg=5;gw_pending=1;
      end
      dut.gain.G14:begin
        logic signed [127:0] product,difference;
        difference=128'($signed(dut.gain.ln_q))+128'sd196328;
        product=128'(dut.gain.p)*difference;rounded=gw_srnd(product);
        if(gw_obs(128'(dut.gain.a_raw),"A")!==product||128'(dut.gain.a_round)!==rounded)$fatal(1,"[A] OM-LSA a product/round differs");
        gw_track(6,product);gw_value=128'(21'(-21'sd196328+21'(rounded)));gw_reg=6;gw_pending=1;
      end
      dut.gain.G18:if(!dut.gain.m_valid||dut.gain.m_ready)begin
        logic signed [127:0] pre,pim,rre,rim;
        logic [127:0] gg;
        pre=128'(dut.gain.re)*128'($signed({1'b0,dut.gain.g}));pim=128'(dut.gain.im)*128'($signed({1'b0,dut.gain.g}));
        rre=gw_srnd(pre);rim=gw_srnd(pim);
        if(gw_obs(128'(dut.gain.out_raw_re),"OUT")!==pre||128'(dut.gain.out_raw_im)!==pim
            ||128'(dut.gain.out_round_re)!==rre||128'(dut.gain.out_round_im)!==rim)$fatal(1,"[OUT] OM-LSA output product/round differs");
        gw_track(7,pre);gw_track(7,pim);
        raw=128'(dut.gain.g)*128'(dut.gain.g);gg=gw_rnd(raw,16);
        if(gw_obs(128'(dut.gain.gg_raw),"GG")!==raw||128'(dut.gain.gg_round)!==gg)$fatal(1,"[GG] OM-LSA G^2 product/round differs");
        gw_track(8,raw);
        raw=gg*128'(dut.gain.gamma);rounded=gw_rnd(raw,16);
        if(gw_obs(128'(dut.gain.prev_raw),"PREV")!==raw||128'(dut.gain.prev_round)!==rounded)$fatal(1,"[PREV] OM-LSA prev product/round differs");
        gw_track(9,raw);
        // m_re/m_im next clock, with prev[k] unless the transaction restarts (all bin_count reset).
        gw_value=128'(24'(rre));gw_value_im=128'(24'(rim));gw_reg=7;gw_pending=1;
        gw_prev=!dut.gain.last;gw_bin=int'(dut.gain.k);gw_prev_value=gw_cap(rounded);
      end
      default:;
    endcase
  end
end
task automatic check_omlsa_gain_widths();
  int bin_count;
  if(!$test$plusargs("CHECK_GAIN_WIDTHS"))return;
  bin_count=gw_count[0];
  if(gw_pending||gw_prev||bin_count<1||gw_count[1]!=2*bin_count||gw_count[2]!=8*bin_count)$fatal(1,"[WIDTH] incomplete OM-LSA gain observations");
  $display("PASS OMLSA GAIN WIDTHS: %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",gw_count[0],gw_count[1],gw_count[2],gw_count[3],
    gw_peak[0],gw_peak[1],gw_peak[2],gw_peak[3],gw_peak[4],gw_peak[5],gw_peak[6],gw_peak[7],gw_peak[8],gw_peak[9]);
endtask
