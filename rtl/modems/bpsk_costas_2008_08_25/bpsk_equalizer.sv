// Delayed-LMS equalizer between the rotator/AGC and the QAM16 slicer (psk_fixed.Equalizer):
// 7 forward taps (Q2.22) and, with DFE, 3 feedback taps on the decided levels.
// An 8-entry FIFO issues one symbol per >= 4 clocks; the output is visible 15 clocks
// after issue (t0). Only the input push and the output pop follow the tracking clock
// enable ce: the pipeline runs freely (no stall fan-out) and an 8-entry output FIFO holds
// results while ce is low. Symbol k applies the coefficient of symbol k-5 (EQ_DELAY=4)
// before its own products:
//  t1+p..t5+p  update of forward pair p = taps (2p,2p+1): fetch, c*conj(x) with three
//              products, sums, rounding, tap write;
//  t6+p..t9+p  products of the updated pair p and accumulation (acc complete after t12);
//  t7..t10 DFE taps update, t11 the two older feedback terms, t12 the term of the
//  previous decision; t13 sum, t14 rounding to the 18-bit output;
//  t15 target levels (decision, or the training label carried in the tag), t16 error;
//  t1..t5 squared magnitude on one multiplier and the forward power;
//  t11..t14 window power, its exponent and the step*reciprocal ROM address;
//  t17..t20 error*step*r on one multiplier (re, then im), variable shift, rounding.
// The coefficient of symbol k is visible from t21, when symbol k+5 reads it at the earliest.
// The decision loop (output, levels, feedback term, sum, rounding) closes in 4 clocks.
module bpsk_equalizer #(
 parameter bit RESET_ACTIVE=1,parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables",parameter bit DFE=0
)(
 input logic clk,rst,ce,start,
 input logic s_valid,
 input logic signed [17:0] s_re,s_im,
 input logic [31:0] s_tag,
 output logic m_valid,
 output logic signed [17:0] m_re,m_im,
 output logic [31:0] m_tag
);
 `include "bpsk_types.svh"
 `include "bpsk_math.svh"
 localparam int LAST=20;
 // Symbol number mod 8 in every stage; bit 3 (mod 16 for the history) only up to the
 // last stage that indexes the history: 8 (product indices), 15 with DFE (level write).
 localparam int HIGH_LAST=DFE?15:8;
 // Level code (3-bit signed, 0 for the empty history) times x by shift and add.
 function automatic logic signed [27:0] eq_scale(input logic signed [24:0] x,input logic signed [2:0] level);
  logic signed [27:0] magnitude;
  begin
   magnitude=(level==3'sd3||level==-3'sd3)?b_s28_t'(x)+(b_s28_t'(x)<<<1):b_s28_t'(x);
   eq_scale=level==0?28'sd0:level<0?-magnitude:magnitude;
  end
 endfunction
 // Squared level code: 0, 1 or 9.
 function automatic logic [3:0] eq_square(input logic signed [2:0] level);
  eq_square=level==0?4'd0:(level==3'sd3||level==-3'sd3)?4'd9:4'd1;
 endfunction
 // Stored level code {present, ca, cb}, c = (level-1)/2; absent (empty history) is level 0.
 function automatic logic [5:0] eq_level(input logic [4:0] code);
  eq_level=code[4] ? {code[3:2],1'b1,code[1:0],1'b1} : 6'd0;
 endfunction
 // Codes {ca,cb} of a training label (levels 2c+1 of q16_levels; inverse of q16_index).
 function automatic logic [3:0] eq_code(input logic [3:0] label);
  case(label)
   4'd0:eq_code=4'b0101;  4'd1:eq_code=4'b0001;  4'd2:eq_code=4'b0100;  4'd3:eq_code=4'b0000;
   4'd4:eq_code=4'b1001;  4'd5:eq_code=4'b1000;  4'd6:eq_code=4'b1101;  4'd7:eq_code=4'b1100;
   4'd8:eq_code=4'b1010;  4'd9:eq_code=4'b1110;  4'd10:eq_code=4'b1011; 4'd11:eq_code=4'b1111;
   4'd12:eq_code=4'b0110; 4'd13:eq_code=4'b0111; 4'd14:eq_code=4'b0010; default:eq_code=4'b0011;
  endcase
 endfunction
 function automatic logic [5:0] eq_norm(input logic [5:0] levels);
  eq_norm=6'(eq_square($signed(levels[5:3])))+6'(eq_square($signed(levels[2:0])));
 endfunction
 // F0 times a level code from F0 and 3*F0 (no adder after the selection).
 function automatic logic signed [26:0] eq_pick(input logic signed [26:0] single,triple,input logic [2:0] level);
  case(level)
   3'b001:eq_pick=single;3'b111:eq_pick=-single;3'b011:eq_pick=triple;3'b101:eq_pick=-triple;
   default:eq_pick=27'sd0;
  endcase
 endfunction
 function automatic logic signed [24:0] eq_sat25(input logic signed [63:0] value);
  if(value>64'sd16777215) eq_sat25=25'sd16777215;
  else if(value< -64'sd16777216) eq_sat25=25'sh1000000;
  else eq_sat25=b_s25_t'(value);
 endfunction
 // Bit length of the window power (the sum includes +1, so it is at least 1).
 function automatic logic [5:0] bit_length(input logic [38:0] value);
  bit_length=0;
  for(integer j=0;j<39;j=j+1) if(value[j]) bit_length=6'(j+1);
 endfunction
 wire reset_now=rst==RESET_ACTIVE;
 // Input FIFO (shift register) and the issue spacing.
 logic signed [17:0] fifo_re[0:7],fifo_im[0:7];
 logic [31:0] fifo_tag[0:7];
 logic [3:0] fifo_count;
 logic [1:0] gap;
 wire issue=fifo_count!=0&&gap==2'd3;
 wire push=s_valid&&ce,begin_frame=start&&ce;
 // At most eight symbols are in flight between the tracking start and their feedback.
 wire [2:0] push_slot=3'(issue ? fifo_count-4'd1 : fifo_count);
 // Output FIFO: pushed in t14, popped when the tracking loop takes the head (ce).
 logic signed [17:0] out_re[0:7],out_im[0:7];
 logic [31:0] out_tag[0:7];
 logic [3:0] out_count;
 wire pop=ce&&out_count!=0;
 wire [2:0] out_slot=3'(pop ? out_count-4'd1 : out_count);
 assign m_valid=out_count!=0;assign m_re=out_re[0];assign m_im=out_im[0];assign m_tag=out_tag[0];
 (* use_dsp="no" *) logic signed [47:0] total_re,total_im;
 // Equalizer output y (registered in t14) and its tag, for the target levels.
 logic signed [17:0] y_re,y_im;
 // Nearest-even rounding by 22 followed by saturation to 18 bits, evaluated on the
 // 48-bit accumulator instead of a sign-extended 64-bit value: the wide rounding add
 // and the two saturation compares were a 48-bit carry chain and missed 100 MHz.
 // round bit = bit21 && (|bits20:0 || bit22); in range iff the 27-bit sum repeats
 // bit17 above the result, which is exactly b_sat's -131072..131071 test.
 function automatic logic signed [17:0] round_sat22(input logic signed [47:0] value);
  logic signed [26:0] scaled;
  begin
   scaled={value[47],value[47:22]}+27'(value[21]&&((|value[20:0])||value[22]));
   round_sat22=scaled[26:17]=={10{scaled[17]}}?scaled[17:0]:(scaled[26]?18'sh20000:18'sd131071);
  end
 endfunction
 wire signed [17:0] y_next_re=round_sat22(total_re),y_next_im=round_sat22(total_im);
 // Stage valids and symbol numbers (index n: active during t_n).
 logic [LAST:1] v;
 logic [2:0] kl[1:LAST];
 logic [HIGH_LAST:1] kh;
 wire [3:0] ks[1:HIGH_LAST];
 genvar g;
 generate
 for(g=1;g<=HIGH_LAST;g=g+1) begin:g_symbol
  assign ks[g]={kh[g],kl[g]};
 end
 endgenerate
 logic [3:0] next_k;
 // Symbol history, squared magnitudes and target levels, indexed by symbol mod 16.
 logic signed [17:0] h_re[0:15],h_im[0:15];
 logic [35:0] h_square[0:15];
 // Per-symbol context, indexed by symbol mod 8.
 (* ram_style="registers",ramstyle="logic" *) logic [31:0] ctx_tag[0:7];
 (* ram_style="registers",ramstyle="logic" *) logic [4:0] ctx_train[0:7];
 (* ram_style="registers",ramstyle="logic" *) logic [38:0] ctx_power[0:7];
 (* ram_style="registers",ramstyle="logic" *) logic [5:0] ctx_shift[0:7];
 logic signed [17:0] c_re[0:7],c_im[0:7];
 logic signed [24:0] w_re[0:6],w_im[0:6];
 // Forward power: sum of the last 7 squared magnitudes.
 (* use_dsp="no" *) logic [37:0] forward_power;
 logic signed [17:0] x0_re,x0_im;
 logic [35:0] square_product,old_square;
 // Sums stay in fabric: DSPs are reserved for the products (and DSP cascades gave
 // negative hold in Artix-7 elsewhere in the core).
 (* use_dsp="no" *) logic [35:0] square_first,square;
 // Update lane.
 logic uf_v,um_v,us_v,ur_v;
 logic [1:0] uf_p,um_p,us_p,ur_p;
 logic signed [17:0] u_cr,u_ci;
 logic signed [17:0] u_xr[0:1];
 // Gauss operands formed in the fetch stage: cr+ci, -(xr+xi), xr-xi (single products in the DSP).
 logic signed [18:0] u_csum;
 logic signed [19:0] u_xneg[0:1],u_xdiff[0:1];
 logic signed [37:0] u_k1[0:1],u_k2[0:1],u_k3[0:1];
 (* use_dsp="no" *) logic signed [38:0] u_dre[0:1],u_dim[0:1];
 logic signed [20:0] u_rre[0:1],u_rim[0:1];
 // Product lane.
 logic mf_v,mm_v,ms_v;
 logic [1:0] mf_p,mm_p,ms_p;
 logic signed [24:0] m_wr[0:1],m_wi[0:1];
 logic signed [17:0] m_xr[0:1],m_xi[0:1];
 logic signed [42:0] p_rr[0:1],p_ii[0:1],p_ri[0:1],p_ir[0:1];
 (* use_dsp="no" *) logic signed [45:0] pair_re,pair_im,acc_re,acc_im;
 // Feedback terms and the squared feedback levels for the power (zero without DFE).
 wire signed [31:0] fb_re,fb_im;
 wire [5:0] old_norms,last_norm;
 // Coefficient lane.
 (* use_dsp="no" *) logic [38:0] power_partial,power_sum;
 logic [5:0] exponent;
 wire [23:0] step_reciprocal;
 logic [9:0] rom_address;
 logic [3:0] y_codes;
 logic signed [17:0] e_re,e_im;
 logic signed [42:0] coefficient_product;
 logic signed [63:0] shifted;
 logic sticky;
 logic signed [17:0] c_re_hold;
 sync_rom #(.WIDTH(24),.ADDR_WIDTH(10),.INIT_FILE({TABLE_DIR,"/eq_reciprocal.mem"})) reciprocal_rom(clk,1'b1,rom_address,step_reciprocal);
 // Mantissa 512..1023: the power normalized to 10 bits (address bits 8:0 = m-512).
 wire [8:0] mantissa=9'(exponent>6'd10 ? {25'd0,power_sum}>>(exponent-6'd10) : {25'd0,power_sum}<<(6'd10-exponent));
 // History indices of the update fetch (t1..t4) and the product fetch (t6..t9), computed
 // one clock earlier: pair p of symbol k reads k-5-2p-i (update) and k-2p-i (products).
 logic [1:0] uf_pair,mf_pair,uf_next_pair,mf_next_pair;
 logic [3:0] uf_next_k,mf_next_k;
 logic [3:0] uf_index[0:1],mf_index[0:1];
 logic [2:0] uf_c;
 always_comb begin
  uf_next_pair=v[1]?2'd1:v[2]?2'd2:v[3]?2'd3:2'd0;uf_next_k=v[1]?ks[1]:v[2]?ks[2]:v[3]?ks[3]:next_k;
  mf_next_pair=v[6]?2'd1:v[7]?2'd2:v[8]?2'd3:2'd0;mf_next_k=v[6]?ks[6]:v[7]?ks[7]:v[8]?ks[8]:ks[5];
 end
 // Target levels of the output: the training label (tag bits 13+) on the preamble, else the
 // per-axis decision c = clamp(floor(v/2T), -2, 1), level 2c+1.
 wire signed [2:0] fa=$signed(y_re[17:15]),fb=$signed(y_im[17:15]);
 // 2'sb10 = -2 (a decimal 2'sd2 overflows the signed 2-bit range in Quartus).
 wire signed [1:0] ca=fa < -3'sd2 ? 2'sb10 : fa > 3'sd1 ? 2'sb01 : fa[1:0];
 wire signed [1:0] cb=fb < -3'sd2 ? 2'sb10 : fb > 3'sd1 ? 2'sb01 : fb[1:0];
 // Tag bits 16:13 carry the training label, bit 12 the training flag.
 wire [4:0] y_tag=ctx_train[kl[15]];
 wire [3:0] target_codes=y_tag[0] ? eq_code(y_tag[4:1]) : {ca,cb};
 // Variable shift of the coefficient product by s-16 with nearest-even rounding: keep one
 // extra bit and a sticky flag, then round (left shifts leave the extra bit zero).
 // Shift amount s-16 of symbol k, registered in t17 for both products: right shift by s-17
 // (when s-16 >= 1) with the sticky mask of the dropped bits, else left shift by 17-s.
 wire signed [6:0] shift_amount=$signed({1'b0,ctx_shift[kl[17]]})-7'sd16;
 logic shift_right;
 logic [5:0] right_shift,left_shift;
 logic [63:0] sticky_mask;
 wire [5:0] next_right_shift=$unsigned(6'(shift_amount-7'sd1)),next_left_shift=$unsigned(6'(7'sd1-shift_amount));
 wire signed [63:0] product_wide=b_s64_t'(coefficient_product);
 wire signed [17:0] error_selected=v[17]?e_re:e_im;
 wire signed [17:0] square_input=v[1]?x0_re:x0_im;
 wire signed [63:0] rounded_coefficient=(shifted>>>1)+b_s64_t'(shifted[0]&&(sticky||shifted[1]));
 wire signed [17:0] coefficient_value=b_sat(rounded_coefficient);
 always_ff @(posedge clk) begin
  if(reset_now) begin
   v<=0;fifo_count<=0;out_count<=0;gap<=2'd3;uf_v<=0;um_v<=0;us_v<=0;ur_v<=0;mf_v<=0;mm_v<=0;ms_v<=0;
  end else begin
   // FIFO: pop the head on issue, push behind the remaining entries.
   if(issue) for(integer j=0;j<7;j=j+1) begin fifo_re[j]<=fifo_re[j+1];fifo_im[j]<=fifo_im[j+1];fifo_tag[j]<=fifo_tag[j+1];end
   if(push) begin fifo_re[push_slot]<=s_re;fifo_im[push_slot]<=s_im;fifo_tag[push_slot]<=s_tag;end
   fifo_count<=fifo_count+4'(push)-4'(issue);
   gap<=issue ? 2'd0 : gap==2'd3 ? 2'd3 : gap+2'd1;
   v<={v[LAST-1:1],issue};kl[1]<=next_k[2:0];for(integer j=2;j<=LAST;j=j+1) kl[j]<=kl[j-1];
   kh<={kh[HIGH_LAST-1:1],next_k[3]};
   // t0: issue into the history.
   if(issue) begin
    next_k<=next_k+4'd1;h_re[next_k]<=fifo_re[0];h_im[next_k]<=fifo_im[0];ctx_tag[next_k[2:0]]<=fifo_tag[0];ctx_train[next_k[2:0]]<=fifo_tag[0][16:12];
    x0_re<=fifo_re[0];x0_im<=fifo_im[0];
   end
   // t1/t2: re^2 and im^2 on one multiplier; t3: their sum; t4: the window of 7.
   square_product<=$unsigned(b_s36_t'(square_input)*b_s36_t'(square_input));
   if(v[2]) square_first<=square_product;
   if(v[3]) begin square<=square_first+square_product;old_square<=h_square[ks[3]-4'd7];end
   if(v[4]) begin h_square[ks[4]]<=square;forward_power<=forward_power+38'(square)-38'(old_square);end
   if(v[5]) ctx_power[kl[5]]<=39'(forward_power)+39'd1;
   // Update lane: fetch in t1..t4 (pair = stage-1), coefficient of symbol k-5.
   uf_pair<=uf_next_pair;uf_c<=3'(uf_next_k-4'd5);
   for(integer i=0;i<2;i=i+1) uf_index[i]<=uf_next_k-4'd5-{1'b0,uf_next_pair,1'b0}-4'(i);
   uf_v<=v[1]|v[2]|v[3]|v[4];
   uf_p<=uf_pair;u_cr<=c_re[uf_c];u_ci<=c_im[uf_c];u_csum<=b_s19_t'(c_re[uf_c])+b_s19_t'(c_im[uf_c]);
   for(integer i=0;i<2;i=i+1) begin
    u_xr[i]<=h_re[uf_index[i]];
    u_xneg[i]<=b_s20_t'(0)-b_s20_t'(h_re[uf_index[i]])-b_s20_t'(h_im[uf_index[i]]);u_xdiff[i]<=b_s20_t'(h_re[uf_index[i]])-b_s20_t'(h_im[uf_index[i]]);
   end
   // c*conj(x) = (cr+j ci)(ur+j ui) with u = conj(x): k1 = ur(cr+ci), k2 = cr(ui-ur),
   // k3 = ci(ur+ui); re = k1-k3, im = k1+k2.
   um_v<=uf_v;um_p<=uf_p;
   for(integer i=0;i<2;i=i+1) begin
    u_k1[i]<=u_csum*u_xr[i];u_k2[i]<=u_xneg[i]*u_cr;u_k3[i]<=u_xdiff[i]*u_ci;
   end
   us_v<=um_v;us_p<=um_p;
   for(integer i=0;i<2;i=i+1) begin
    u_dre[i]<=b_s39_t'(u_k1[i])-b_s39_t'(u_k3[i]);u_dim[i]<=b_s39_t'(u_k1[i])+b_s39_t'(u_k2[i]);
   end
   ur_v<=us_v;ur_p<=us_p;
   for(integer i=0;i<2;i=i+1) begin
    u_rre[i]<=b_s21_t'(b_round(b_s64_t'(u_dre[i]),18));u_rim[i]<=b_s21_t'(b_round(b_s64_t'(u_dim[i]),18));
   end
   if(ur_v) for(integer i=0;i<2;i=i+1) if(ur_p!=2'd3||i==0) begin
    w_re[{ur_p,1'(i)}]<=eq_sat25(b_s64_t'(w_re[{ur_p,1'(i)}])+b_s64_t'(u_rre[i]));
    w_im[{ur_p,1'(i)}]<=eq_sat25(b_s64_t'(w_im[{ur_p,1'(i)}])+b_s64_t'(u_rim[i]));
   end
   // Product lane: fetch in t6..t9 (pair = stage-6) after the pair was updated.
   mf_pair<=mf_next_pair;
   for(integer i=0;i<2;i=i+1) mf_index[i]<=mf_next_k-{1'b0,mf_next_pair,1'b0}-4'(i);
   mf_v<=v[6]|v[7]|v[8]|v[9];
   mf_p<=mf_pair;
   for(integer i=0;i<2;i=i+1) begin
    m_wr[i]<=mf_pair==2'd3&&i==1 ? 25'sd0 : w_re[{mf_pair,1'(i)}];m_wi[i]<=mf_pair==2'd3&&i==1 ? 25'sd0 : w_im[{mf_pair,1'(i)}];
    m_xr[i]<=h_re[mf_index[i]];m_xi[i]<=h_im[mf_index[i]];
   end
   mm_v<=mf_v;mm_p<=mf_p;
   for(integer i=0;i<2;i=i+1) begin
    p_rr[i]<=m_wr[i]*m_xr[i];p_ii[i]<=m_wi[i]*m_xi[i];p_ri[i]<=m_wr[i]*m_xi[i];p_ir[i]<=m_wi[i]*m_xr[i];
   end
   ms_v<=mm_v;ms_p<=mm_p;
   pair_re<=b_s46_t'(p_rr[0])-b_s46_t'(p_ii[0])+b_s46_t'(p_rr[1])-b_s46_t'(p_ii[1]);
   pair_im<=b_s46_t'(p_ri[0])+b_s46_t'(p_ir[0])+b_s46_t'(p_ri[1])+b_s46_t'(p_ir[1]);
   if(ms_v) begin acc_re<=(ms_p==0 ? 46'sd0 : acc_re)+pair_re;acc_im<=(ms_p==0 ? 46'sd0 : acc_im)+pair_im;end
   // t11/t12: window power (forward + feedback levels * T^2 = 2^28); t13: exponent;
   // t14: ROM address {training, mantissa-512}.
   if(v[11]) power_partial<=ctx_power[kl[11]]+{5'd0,old_norms,28'd0};
   if(v[12]) power_sum<=power_partial+{5'd0,last_norm,28'd0};
   if(v[13]) begin exponent<=bit_length(power_sum);ctx_shift[kl[13]]<=bit_length(power_sum);end
   if(v[14]) rom_address<={ctx_train[kl[14]][0],mantissa};
   // t13: sum with the feedback terms (levels * 2^14); t14: rounding to the output.
   total_re<=b_s48_t'(acc_re)+(b_s48_t'(fb_re)<<<14);total_im<=b_s48_t'(acc_im)+(b_s48_t'(fb_im)<<<14);
   if(pop) for(integer j=0;j<7;j=j+1) begin out_re[j]<=out_re[j+1];out_im[j]<=out_im[j+1];out_tag[j]<=out_tag[j+1];end
   if(v[14]) begin
    y_re<=y_next_re;y_im<=y_next_im;
    out_re[out_slot]<=y_next_re;out_im[out_slot]<=y_next_im;out_tag[out_slot]<=ctx_tag[kl[14]];
   end
   out_count<=out_count+4'(v[14])-4'(pop);
   // t15: target levels; t16: error against them (T = 2^14).
   if(v[15]) y_codes<=target_codes;
   if(v[16]) begin
    e_re<=b_sat(b_s64_t'(q16_scale(18'sd16384,$signed({y_codes[3:2],1'b1})))-b_s64_t'(y_re));
    e_im<=b_sat(b_s64_t'(q16_scale(18'sd16384,$signed({y_codes[1:0],1'b1})))-b_s64_t'(y_im));
   end
   // t17/t18: products with step*r; t18/t19: shift; t19/t20: rounding.
   if(v[17]) begin
    shift_right<=shift_amount>=7'sd1;right_shift<=next_right_shift;left_shift<=next_left_shift;
    sticky_mask<=shift_amount>=7'sd2 ? (64'd1<<next_right_shift)-64'd1 : 64'd0;
   end
   coefficient_product<=b_s43_t'(error_selected)*b_s43_t'($signed({1'b0,step_reciprocal}));
   shifted<=shift_right ? product_wide>>>right_shift : product_wide<<<left_shift;
   sticky<=|($unsigned(product_wide)&sticky_mask);
   if(v[19]) c_re_hold<=coefficient_value;
   if(v[20]) begin c_re[kl[20]]<=c_re_hold;c_im[kl[20]]<=coefficient_value;end
  end
  if(!reset_now&&begin_frame) begin
   fifo_count<=0;out_count<=0;gap<=2'd3;v<=0;next_k<=0;forward_power<=0;
   for(integer j=0;j<16;j=j+1) begin h_re[j]<=0;h_im[j]<=0;h_square[j]<=0;end
   for(integer j=0;j<8;j=j+1) begin c_re[j]<=0;c_im[j]<=0;end
   for(integer j=0;j<7;j=j+1) begin w_re[j]<=j==0 ? 25'sd4194304 : 25'sd0;w_im[j]<=0;end
  end
 end

 generate
 if(DFE) begin:g_dfe
  // Feedback lane. Stage 10 reads and stage 15 writes the level history (HIGH_LAST = 15).
  logic [4:0] h_codes[0:15];
  logic [4:0] last_code;
  logic [5:0] fu_levels[0:2],fb_l1,fb_l2;
  wire [5:0] last_levels=eq_level(last_code);
  logic signed [17:0] fu_cr,fu_ci;
  logic signed [27:0] fu_ra[0:2],fu_rb[0:2],fu_ia[0:2],fu_ib[0:2];
  logic signed [20:0] fu_dre[0:2],fu_dim[0:2];
  logic signed [24:0] f_re[0:2],f_im[0:2];
  logic signed [31:0] fb_old_re,fb_old_im,fb_q_re,fb_q_im;
  logic signed [26:0] f0_re,f0_im,f0_re3,f0_im3;
  wire [2:0] f_c=kl[7]-3'd5;
  wire [3:0] k_level_read=ks[HIGH_LAST-5],k_level_write=ks[HIGH_LAST];
  always_ff @(posedge clk) if(!reset_now) begin
   // t7: coefficient of k-5 and the levels of k-6..k-8; t8: c times the levels;
   // t9: round(c*conj(L), 4); t10: the feedback taps and the levels of k-2, k-3.
   if(v[7]) begin
    fu_cr<=c_re[f_c];fu_ci<=c_im[f_c];
    for(integer j=0;j<3;j=j+1) fu_levels[j]<=eq_level(h_codes[ks[7]-4'd6-4'(j)]);
   end
   if(v[8]) for(integer j=0;j<3;j=j+1) begin
    fu_ra[j]<=eq_scale(b_s25_t'(fu_cr),$signed(fu_levels[j][5:3]));fu_rb[j]<=eq_scale(b_s25_t'(fu_ci),$signed(fu_levels[j][2:0]));
    fu_ia[j]<=eq_scale(b_s25_t'(fu_ci),$signed(fu_levels[j][5:3]));fu_ib[j]<=eq_scale(b_s25_t'(fu_cr),$signed(fu_levels[j][2:0]));
   end
   if(v[9]) for(integer j=0;j<3;j=j+1) begin
    fu_dre[j]<=b_s21_t'(b_round(b_s64_t'(fu_ra[j])+b_s64_t'(fu_rb[j]),4));
    fu_dim[j]<=b_s21_t'(b_round(b_s64_t'(fu_ia[j])-b_s64_t'(fu_ib[j]),4));
   end
   if(v[10]) begin
    for(integer j=0;j<3;j=j+1) begin
     f_re[j]<=eq_sat25(b_s64_t'(f_re[j])+b_s64_t'(fu_dre[j]));f_im[j]<=eq_sat25(b_s64_t'(f_im[j])+b_s64_t'(fu_dim[j]));
    end
    fb_l1<=eq_level(h_codes[k_level_read-4'd2]);fb_l2<=eq_level(h_codes[k_level_read-4'd3]);
   end
   // t11: F1*L(k-2)+F2*L(k-3), F0 and 3*F0; t12: + F0*L(k-1), decided 4 clocks earlier.
   if(v[11]) begin
    fb_old_re<=b_s32_t'(eq_scale(f_re[1],$signed(fb_l1[5:3])))-b_s32_t'(eq_scale(f_im[1],$signed(fb_l1[2:0])))
              +b_s32_t'(eq_scale(f_re[2],$signed(fb_l2[5:3])))-b_s32_t'(eq_scale(f_im[2],$signed(fb_l2[2:0])));
    fb_old_im<=b_s32_t'(eq_scale(f_re[1],$signed(fb_l1[2:0])))+b_s32_t'(eq_scale(f_im[1],$signed(fb_l1[5:3])))
              +b_s32_t'(eq_scale(f_re[2],$signed(fb_l2[2:0])))+b_s32_t'(eq_scale(f_im[2],$signed(fb_l2[5:3])));
    f0_re<=b_s27_t'(f_re[0]);f0_im<=b_s27_t'(f_im[0]);
    f0_re3<=b_s27_t'(f_re[0])+(b_s27_t'(f_re[0])<<<1);f0_im3<=b_s27_t'(f_im[0])+(b_s27_t'(f_im[0])<<<1);
   end
   // (F0r + j F0i)(a + j b): re = F0r*a - F0i*b, im = F0r*b + F0i*a.
   if(v[12]) begin
    fb_q_re<=fb_old_re+b_s32_t'(eq_pick(f0_re,f0_re3,last_levels[5:3]))-b_s32_t'(eq_pick(f0_im,f0_im3,last_levels[2:0]));
    fb_q_im<=fb_old_im+b_s32_t'(eq_pick(f0_re,f0_re3,last_levels[2:0]))+b_s32_t'(eq_pick(f0_im,f0_im3,last_levels[5:3]));
   end
   if(v[15]) begin h_codes[k_level_write]<={1'b1,target_codes};last_code<={1'b1,target_codes};end
   if(begin_frame) begin
    last_code<=0;
    for(integer j=0;j<16;j=j+1) h_codes[j]<=0;
    for(integer j=0;j<3;j=j+1) begin f_re[j]<=0;f_im[j]<=0;end
   end
  end
  assign fb_re=fb_q_re;assign fb_im=fb_q_im;
  assign old_norms=6'(eq_norm(fb_l1)+eq_norm(fb_l2));assign last_norm=eq_norm(last_levels);
 end else begin:g_linear
  assign fb_re=0;assign fb_im=0;assign old_norms=0;assign last_norm=0;
 end
 endgenerate
endmodule
