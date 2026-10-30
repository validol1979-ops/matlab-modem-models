// Complex 33-tap RRC. Latency=8 enabled clocks; II=1, one final rounding by SHIFT bits
// (17 keeps Q15; QAM64 uses 16 in the transmitter and 19 in the receiver).
module bpsk_fir #(parameter bit RESET_ACTIVE=1,parameter bit REAL_ONLY=0,parameter int SHIFT=17)(
 input logic clk,rst,ce,s_valid,s_last,s_first,
 input logic signed [17:0] s_re,s_im,
 output logic m_valid,m_last,
 output logic signed [17:0] m_re,m_im
);
 `include "bpsk_types.svh"
 logic [7:0] valid_pipe,last_pipe;
 logic [5:0] history_count;
 wire reset_now=rst==RESET_ACTIVE;
 assign m_valid=valid_pipe[7]&&!reset_now;assign m_last=last_pipe[7];
 bpsk_rrc_axis #(.SHIFT(SHIFT)) real_axis(clk,ce,s_valid,s_first,history_count,s_re,m_re);
 generate
 if(REAL_ONLY) begin:g_real
  wire [17:0] unused_im=s_im;
  assign m_im=0;
 end else begin:g_complex
  bpsk_rrc_axis #(.SHIFT(SHIFT)) imag_axis(clk,ce,s_valid,s_first,history_count,s_im,m_im);
 end
 endgenerate
 always_ff @(posedge clk) begin
  if(reset_now) begin valid_pipe<=0;history_count<=0;end
  else if(ce) begin
   valid_pipe<={valid_pipe[6:0],s_valid};last_pipe<={last_pipe[6:0],s_last};
   if(s_valid) begin
    if(s_first) history_count<=1;else if(history_count<32) history_count<=history_count+1'b1;
   end
  end
 end
endmodule
