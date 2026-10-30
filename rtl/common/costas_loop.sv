// QPSK Costas loop (research_core costas; bit-exact reference sync_fixed.costas).
// Configuration (one transfer, between transactions): K1 = round(k1/(2 pi)*2^33),
// K2 = round(k2/(2 pi)*2^33) (sync_fixed.costas_gains). A transaction is one Q15 signal (s_last
// on its last sample) and gives one output per sample: the rotated value x*exp(-j phase)
// (bpsk_rotate: the pilot's cos table, 12-bit phase index) and the phase used (2^-32 turns).
// error = sign(re)*im - sign(im)*re; frequency += rnd(K2*error, 16); phase += frequency +
// rnd(K1*error, 16). The loop has no sample delay (as the model). An unstalled next sample
// is accepted during UPDATE using the exact updated phase, giving II=8 clocks; this
// combinational forwarding does not establish a physical clock limit. Each transaction
// starts from phase = frequency = 0. Configuration waits for the final output handshake.
module costas_loop #(
  parameter bit RESET_ACTIVE = 1,
  parameter TABLE_DIR = "rtl/modems/bpsk_costas_2008_08_25/tables"
)(
  input logic clk, rst,
  input logic cfg_valid,
  input logic [31:0] cfg_k1, cfg_k2,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  output logic signed [31:0] m_phase,
  input logic m_ready
);
  wire reset_now = rst == RESET_ACTIVE;
  typedef enum logic [1:0] {IDLE, ROTATE, UPDATE} state_t;
  state_t state;
  logic [31:0] k1, k2;
  logic signed [31:0] phase, frequency, phase_used;
  logic sample_last, frame_active;
  logic signed [50:0] d1, d2;
  wire output_available = !m_valid || m_ready;
  wire final_output_take = m_valid && m_ready && m_last;
  assign cfg_ready = !reset_now && state == IDLE && output_available &&
                     (!frame_active || final_output_take);
  wire cfg_take = cfg_valid && cfg_ready;
  // Pending configuration cannot obstruct an open frame. At its UPDATE boundary,
  // wait one cycle for IDLE so configuration can win before the next frame starts.
  assign s_ready = !reset_now && configured && output_available && !cfg_take &&
                   (state == IDLE || (state == UPDATE && !(sample_last && cfg_valid)));
  wire take = s_valid && s_ready;
  wire r_valid;
  wire signed [17:0] r_re, r_im;
  wire [31:0] r_tag;
  wire signed [31:0] frequency_next = frequency + 32'((d2 + 51'sd32768) >>> 16);
  wire signed [31:0] phase_next = sample_last ? 32'sd0 :
                               phase + frequency_next + 32'((d1 + 51'sd32768) >>> 16);
  wire signed [31:0] input_phase = state == UPDATE ? phase_next : phase;
  bpsk_rotate #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) rotation(
    clk,rst,1'b1,take,s_re,s_im,input_phase[31:20],25'd1048576,{31'd0,s_last},r_valid,r_re,r_im,r_tag);
  wire signed [1:0] sign_re = r_re > 0 ? 2'sd1 : r_re < 0 ? -2'sd1 : 2'sd0;
  wire signed [1:0] sign_im = r_im > 0 ? 2'sd1 : r_im < 0 ? -2'sd1 : 2'sd0;
  wire signed [19:0] error = 20'(sign_re)*20'(r_im) - 20'(sign_im)*20'(r_re);
  always_ff @(posedge clk) begin
    if (reset_now) begin configured <= 0; state <= IDLE; m_valid <= 0; phase <= '0; frequency <= '0; frame_active <= 0; end
    else begin
      if (cfg_take) begin k1 <= cfg_k1; k2 <= cfg_k2; configured <= 1; end
      if (m_valid && m_ready) m_valid <= 0;
      if (final_output_take) frame_active <= 0;
      if (take) frame_active <= 1;
      case (state)
        IDLE: if (take) begin state <= ROTATE; phase_used <= input_phase; end
        // The upper tag bits are zero (only the last flag travels through the rotator).
        ROTATE: if (r_valid && r_tag[31:1] == '0) begin
          m_valid <= 1; m_re <= r_re; m_im <= r_im; m_phase <= phase_used; m_last <= r_tag[0];
          sample_last <= r_tag[0];
          d1 <= 51'($signed({1'b0, k1}))*51'(error); d2 <= 51'($signed({1'b0, k2}))*51'(error);
          state <= UPDATE;
        end
        UPDATE: begin
          frequency <= frequency_next; phase <= phase_next;
          // A transaction's last sample restarts the loop for the next one.
          if (sample_last) begin frequency <= '0; phase <= '0; end
          if (take) begin state <= ROTATE; phase_used <= input_phase; end
          else state <= IDLE;
        end
        default: state <= IDLE;
      endcase
    end
  end
endmodule
