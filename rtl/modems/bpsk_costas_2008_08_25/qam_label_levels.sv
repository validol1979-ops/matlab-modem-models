// QAM training label (table index) to 4-bit signed per-axis levels: QAM16 (+-1/+-3) or
// QAM64 (+-1..+-7).
module qam_label_levels #(parameter int ORDER=16)(
 input logic [(ORDER==64?6:4)-1:0] label,
 output logic signed [3:0] la,lb
);
 `include "bpsk_types.svh"
 `include "bpsk_math.svh"
 generate
 if(ORDER==64) begin:g_qam64
  wire [7:0] levels=q64_levels(label);
  assign la=$signed(levels[7:4]);assign lb=$signed(levels[3:0]);
 end else begin:g_qam16
  wire [5:0] levels=q16_levels(label);
  assign la={levels[5],levels[5:3]};assign lb={levels[2],levels[2:0]};
 end
 endgenerate
endmodule
