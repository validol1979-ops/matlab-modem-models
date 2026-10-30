// MSK/GMSK sample engine (cpm_fixed.transmit): per-sample frequency d in {-1,0,+1}
// (0 outside the frame), for GMSK filtered by the symmetric 33-tap Gaussian (Q16, sum
// 2^16) as pair sums times taps in fabric; the phase advances by f*2^11 (32-bit turns)
// and cos/sin come from the pilot table (Q17) rounded to Q15. s_first clears the
// history and starts the phase from 0. Latency 8 enabled clocks, II=1.
module cpm_modulator #(
 parameter bit RESET_ACTIVE=1,parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables",parameter bit GMSK=0,
 parameter int TAG_WIDTH=2
)(
 input logic clk,rst,ce,s_valid,s_first,
 input logic signed [1:0] s_d,
 input logic [TAG_WIDTH-1:0] s_tag,
 output logic m_valid,
 output logic signed [17:0] m_re,m_im,
 output logic signed [17:0] m_frequency,
 output logic [TAG_WIDTH-1:0] m_tag
);
 `include "bpsk_types.svh"
 `include "bpsk_math.svh"
 `include "bpsk_constants.svh"
 localparam int LATENCY=8;
 wire reset_now=rst==RESET_ACTIVE;
 logic [LATENCY-1:0] valid_pipe;
 logic [4:0] first_pipe;
 logic [TAG_WIDTH-1:0] tag_pipe[0:LATENCY-1];
 // Stage 1: history (newest first); 2: pair terms; 3: partial sums; 4: sum; 5: f.
 // GMSK keeps taps 1..31 of the history (tap 0 and 32 are zero); MSK only the newest.
 localparam int HISTORY=GMSK?32:1;
 logic signed [1:0] history[0:HISTORY-1];
 wire signed [21:0] partial[0:3];
 wire signed [17:0] msk_frequency;
 logic signed [17:0] frequency_sum,frequency,frequency_delay[0:1];
 logic signed [31:0] phase;
 wire [11:0] cos_index=phase[31:20];
 wire [17:0] cos_value,sin_value;
 sync_rom #(.WIDTH(18),.ADDR_WIDTH(12),.INIT_FILE({TABLE_DIR,"/cos.mem"})) cosine(clk,ce,cos_index,cos_value);
 sync_rom #(.WIDTH(18),.ADDR_WIDTH(12),.INIT_FILE({TABLE_DIR,"/cos.mem"})) sine(clk,ce,b_s12_t'(cos_index-12'd1024),sin_value);
 // Tap times a pair sum in -2..2 (shift and negate only).
 function automatic logic signed [20:0] pair_term(input integer k,input logic signed [2:0] pair);
  logic signed [20:0] g;
  begin
   g=b_s21_t'(gauss_coefficient(k));
   case(pair)
    3'sd1:pair_term=g;3'sd2:pair_term=g<<<1;-3'sd1:pair_term=-g;-3'sd2:pair_term=-(g<<<1);
    default:pair_term=21'sd0;
   endcase
  end
 endfunction
 genvar g;
 generate
 if(GMSK) begin:g_gauss
  // |2*tap| < 2^15 and every partial sum stays within +-2^17 (all taps sum to 2^16).
  (* use_dsp="no" *) logic signed [17:0] term[1:16];
  (* use_dsp="no" *) logic signed [17:0] partial_q[0:3];
  always_ff @(posedge clk) if(!reset_now&&ce) begin
   for(integer k=1;k<16;k=k+1) term[k]<=b_s18_t'(pair_term(k,b_s3_t'(history[k])+b_s3_t'(history[32-k])));
   term[16]<=b_s18_t'(pair_term(16,b_s3_t'(history[16])));
   partial_q[0]<=term[1]+term[2]+term[3];
   for(integer j=1;j<4;j=j+1) partial_q[j]<=term[4*j]+term[4*j+1]+term[4*j+2]+term[4*j+3]+(j==3 ? term[16] : 18'sd0);
  end
  for(g=0;g<4;g=g+1) begin:g_partial
   assign partial[g]=b_s22_t'(partial_q[g]);
  end
  assign msk_frequency=18'sd0;
 end else begin:g_msk
  for(g=0;g<4;g=g+1) begin:g_partial
   assign partial[g]=22'sd0;
  end
  // MSK: f = d*2^16 from the newest sample, delayed to the GMSK depth.
  logic signed [1:0] newest[0:1];
  always_ff @(posedge clk) if(ce) begin newest[0]<=history[0];newest[1]<=newest[0];end
  assign msk_frequency=b_s18_t'(newest[1])<<<16;
 end
 endgenerate
 assign m_valid=valid_pipe[LATENCY-1]&&!reset_now;assign m_tag=tag_pipe[LATENCY-1];
 always_ff @(posedge clk) begin
  if(reset_now) valid_pipe<=0;
  else if(ce) begin
   valid_pipe<={valid_pipe[LATENCY-2:0],s_valid};first_pipe<={first_pipe[3:0],s_valid&&s_first};
   tag_pipe[0]<=s_tag;for(integer j=1;j<LATENCY;j=j+1) tag_pipe[j]<=tag_pipe[j-1];
   if(s_valid) begin
    for(integer j=HISTORY-1;j>0;j=j-1) history[j]<=s_first?2'sd0:history[j-1];
    history[0]<=s_d;
   end
   frequency_sum<=GMSK?b_s18_t'(partial[0]+partial[1]+partial[2]+partial[3]):msk_frequency;
   frequency<=frequency_sum;
   // Stage 6: phase; stage 7: table; stage 8: rounding to Q15 (f delayed alongside).
   if(valid_pipe[4]) phase<=(first_pipe[4]?32'sd0:phase)+(b_s32_t'(frequency)<<<11);
   m_re<=b_s18_t'(b_round(b_s64_t'($signed(cos_value)),2));m_im<=b_s18_t'(b_round(b_s64_t'($signed(sin_value)),2));
   frequency_delay[0]<=frequency;frequency_delay[1]<=frequency_delay[0];m_frequency<=frequency_delay[1];
  end
 end
endmodule
