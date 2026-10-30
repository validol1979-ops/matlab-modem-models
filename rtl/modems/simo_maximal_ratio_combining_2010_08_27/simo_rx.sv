// Two-branch SIMO receiver: fxp_mrc2 combining with known branch gains in front
// of the pilot receiver as diagonal unit QPSK, Gray-differential, feedback carrier
// and early-late timing (profile QPSK_DIFF in psk_fixed.py, mrc_fixed.py).
// Load gains (gain_*) and the 192 training labels (cfg_*) before frames; both
// are accepted only while idle. Branch samples share valid/last; TLAST per waveform.
module simo_rx #(
 parameter bit RESET_ACTIVE=1,parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables"
)(
 input logic clk,rst,
 input logic gain_valid,
 input logic signed [17:0] gain_a_re,gain_a_im,gain_b_re,gain_b_im,
 input logic [15:0] variance_a,variance_b,
 output logic gain_ready,gain_configured,gain_error,saturated,
 input logic cfg_valid,
 input logic [1:0] cfg_bit,
 input logic cfg_last,
 input logic [11:0] cfg_count,
 output logic cfg_ready,configured,error,
 input logic s_valid,s_last,
 input logic signed [17:0] s_a_re,s_a_im,s_b_re,s_b_im,
 output logic s_ready,
 output logic m_valid,m_last,
 output logic [1:0] m_bit,m_index,
 input logic m_ready,
 output logic signed [17:0] m_re,m_im,
 output logic signed [31:0] m_phase,m_frequency,m_correction,
 output logic [24:0] m_gain,
 output logic acquisition_valid,acquisition_confidence,
 output logic signed [31:0] acquisition_delay,acquisition_frequency,acquisition_phase,
 output logic [24:0] acquisition_gain,
 output logic [63:0] acquisition_score
);
 logic combined_valid,combined_last,combined_ready;
 logic signed [17:0] combined_re,combined_im;
 // An input register separates configuration arbitration from the combiner's
 // valid output. Count all front-end words, including its pipeline/FIFO: a
 // training change is legal only when none can still reach the receiver.
 logic pending,pending_last,combiner_ready,receiver_cfg_ready,combiner_cfg_ready;
 logic signed [17:0] pending_ar,pending_ai,pending_br,pending_bi;
 logic [3:0] front_used;
 wire front_idle=front_used==0;
 wire cfg_take=cfg_valid&&cfg_ready;
 wire gain_take=gain_valid&&gain_ready;
 wire push=s_valid&&s_ready;
 wire transfer=pending&&combiner_ready;
 wire pop=combined_valid&&combined_ready;
 assign cfg_ready=receiver_cfg_ready;
 assign gain_ready=combiner_cfg_ready;
 assign s_ready=configured&&gain_configured&&rst!=RESET_ACTIVE&&!cfg_take&&!gain_take&&(!pending||combiner_ready);
 always_ff @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin pending<=0;front_used<=0;end
  else begin
   if(push||transfer) pending<=push;
   if(push) begin
    pending_ar<=s_a_re;pending_ai<=s_a_im;pending_br<=s_b_re;pending_bi<=s_b_im;pending_last<=s_last;
   end
   case({push,pop})
    2'b10:front_used<=front_used+1'b1;
    2'b01:front_used<=front_used-1'b1;
    default:;
   endcase
  end
 end
 fxp_mrc2 #(.RESET_ACTIVE(RESET_ACTIVE)) combiner(
  .clk(clk),.rst(rst),.cfg_valid(gain_valid),.cfg_enable(front_idle),.cfg_gain_a_re(gain_a_re),.cfg_gain_a_im(gain_a_im),.cfg_gain_b_re(gain_b_re),.cfg_gain_b_im(gain_b_im),
  .cfg_variance_a(variance_a),.cfg_variance_b(variance_b),.cfg_ready(combiner_cfg_ready),.configured(gain_configured),.error(gain_error),.saturated(saturated),
  .s_valid(pending),.s_last(pending_last),.s_a_re(pending_ar),.s_a_im(pending_ai),.s_b_re(pending_br),.s_b_im(pending_bi),.s_ready(combiner_ready),
  .m_valid(combined_valid),.m_last(combined_last),.m_ready(combined_ready),.m_re(combined_re),.m_im(combined_im));
 bpsk_rx #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR),.ORDER(4),.AMPLITUDE(23170),.DIFFERENTIAL(1),.FEEDFORWARD(0),.TIMING_LOOP(1)) receiver(
  .clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_enable(front_idle),.cfg_bit(cfg_bit),.cfg_last(cfg_last),.cfg_count(cfg_count),.cfg_ready(receiver_cfg_ready),.configured(configured),.error(error),
  .s_valid(combined_valid),.s_last(combined_last),.s_re(combined_re),.s_im(combined_im),.s_ready(combined_ready),
  .m_valid(m_valid),.m_last(m_last),.m_bit(m_bit),.m_index(m_index),.m_ready(m_ready),.m_re(m_re),.m_im(m_im),
  .m_phase(m_phase),.m_frequency(m_frequency),.m_correction(m_correction),.m_gain(m_gain),
  .acquisition_valid(acquisition_valid),.acquisition_confidence(acquisition_confidence),.acquisition_delay(acquisition_delay),
  .acquisition_frequency(acquisition_frequency),.acquisition_phase(acquisition_phase),.acquisition_gain(acquisition_gain),.acquisition_score(acquisition_score));
endmodule
