// Fully pipelined vectoring CORDIC, signed phase in 32-bit turns, II=1.
module bpsk_cordic #(parameter int WIDTH=49,TAG_WIDTH=16,parameter bit RESET_ACTIVE=1)(
 input logic clk,rst,ce,s_valid,
 input logic signed [WIDTH-1:0] s_x,s_y,
 input logic [TAG_WIDTH-1:0] s_tag,
 output logic m_valid,
 output logic signed [31:0] m_phase,
 output logic [TAG_WIDTH-1:0] m_tag
);
 `include "bpsk_types.svh"
 `include "bpsk_constants.svh"
 localparam int W=WIDTH+2;
 logic signed [W-1:0] x[0:18],y[0:19];
 logic signed [31:0] angle[0:20];
 logic [TAG_WIDTH-1:0] tag_pipe[0:20];
 logic [20:0] valid_pipe,zero_pipe;
 wire reset_now=rst==RESET_ACTIVE;
 assign m_valid=valid_pipe[20]&&!reset_now;assign m_phase=zero_pipe[20]?32'sd0:angle[20];assign m_tag=tag_pipe[20];
 always_ff @(posedge clk) begin
  if(reset_now) valid_pipe<=0;
  else if(ce) begin
   valid_pipe<={valid_pipe[19:0],s_valid};zero_pipe<={zero_pipe[19:0],s_x==0 && s_y==0};tag_pipe[0]<=s_tag;
   if(s_x<0) begin x[0]<=-$signed({{2{s_x[WIDTH-1]}},s_x});y[0]<=-$signed({{2{s_y[WIDTH-1]}},s_y});angle[0]<=32'sh80000000;end
   else begin x[0]<=$signed({{2{s_x[WIDTH-1]}},s_x});y[0]<=$signed({{2{s_y[WIDTH-1]}},s_y});angle[0]<=0;end
   for(integer j=0;j<20;j=j+1) begin
    tag_pipe[j+1]<=tag_pipe[j];
    if(y[j]>=0) begin if(j<18) x[j+1]<=x[j]+(y[j]>>>j);if(j<19) y[j+1]<=y[j]-(x[j]>>>j);angle[j+1]<=angle[j]+atan_coefficient(j);end
    else begin if(j<18) x[j+1]<=x[j]-(y[j]>>>j);if(j<19) y[j+1]<=y[j]+(x[j]>>>j);angle[j+1]<=angle[j]-atan_coefficient(j);end
   end
  end
 end
endmodule
