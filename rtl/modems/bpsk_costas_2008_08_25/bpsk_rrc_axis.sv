// One real axis of the symmetric RRC datapath. No reset on data registers.
// Last three stages: three-input sum, rounding, saturation (latency unchanged).
module bpsk_rrc_axis #(parameter int SHIFT=17)(
 input logic clk,ce,s_valid,s_first,
 input logic [5:0] history_count,
 input logic signed [17:0] sample,
 output logic signed [17:0] result
);
 `include "bpsk_types.svh"
 `include "bpsk_constants.svh"
 logic signed [17:0] history[0:31];
 wire signed [36:0] product[0:16];
 // Adders stay in fabric: DSP cascades (PCOUT->PCIN) left no hold margin on Artix-7.
 (* use_dsp="no" *) logic signed [37:0] sum1[0:8];
 (* use_dsp="no" *) logic signed [38:0] sum2[0:4];
 (* use_dsp="no" *) logic signed [39:0] sum3[0:2];
 logic signed [41:0] total;
 // Nearest-even rounding to Q15 never saturates at 26 bits; saturation is a separate stage.
 wire signed [25:0] rounded;
 logic signed [25:0] rounded_reg;
 wire signed [17:0] saturated;
 wire unused_round_overflow,unused_overflow;
 fxp_round_sat #(.IN_WIDTH(42),.IN_FRAC(SHIFT+15),.OUT_WIDTH(26),.OUT_FRAC(15)) quantize(total,rounded,unused_round_overflow);
 fxp_round_sat #(.IN_WIDTH(26),.IN_FRAC(15),.OUT_WIDTH(18),.OUT_FRAC(15)) limit(rounded_reg,saturated,unused_overflow);
 always_ff @(posedge clk) if(ce&&s_valid) begin
  for(integer j=31;j>0;j=j-1) history[j]<=history[j-1];history[0]<=sample;
 end
 genvar g;
 generate
 for(g=0;g<17;g=g+1) begin:g_tap
  if(rrc_coefficient(g)==0) begin:g_zero
   assign product[g]=0;
  end else begin:g_product
   logic signed [18:0] pair;
   logic signed [36:0] multiplied;
   if(g==0) begin:g_first
    always_ff @(posedge clk) if(ce&&s_valid) pair<=b_s19_t'(sample)+((!s_first&&history_count==32)?b_s19_t'(history[31]):19'sd0);
   end else if(g==16) begin:g_center
    always_ff @(posedge clk) if(ce&&s_valid) pair<=(!s_first&&history_count>=16)?b_s19_t'(history[15]):19'sd0;
   end else begin:g_symmetric
    always_ff @(posedge clk) if(ce&&s_valid)
     pair<=((!s_first&&history_count>=b_u6_t'(g))?b_s19_t'(history[g-1]):19'sd0)+((!s_first&&history_count>=b_u6_t'(32-g))?b_s19_t'(history[31-g]):19'sd0);
   end
   always_ff @(posedge clk) if(ce) multiplied<=pair*rrc_coefficient(g);
   assign product[g]=multiplied;
  end
 end
 endgenerate
 always_ff @(posedge clk) if(ce) begin
  for(integer j=0;j<9;j=j+1) begin
   if(j<8) sum1[j]<=$signed(product[2*j])+$signed(product[2*j+1]);else sum1[j]<=b_s38_t'(product[16]);
  end
  for(integer j=0;j<5;j=j+1) begin
   if(j<4) sum2[j]<=$signed(sum1[2*j])+$signed(sum1[2*j+1]);else sum2[j]<=b_s39_t'(sum1[8]);
  end
  for(integer j=0;j<3;j=j+1) begin
   if(j<2) sum3[j]<=$signed(sum2[2*j])+$signed(sum2[2*j+1]);else sum3[j]<=b_s40_t'(sum2[4]);
  end
  total<=b_s42_t'(sum3[0])+b_s42_t'(sum3[1])+b_s42_t'(sum3[2]);
  rounded_reg<=rounded;result<=saturated;
 end
endmodule
