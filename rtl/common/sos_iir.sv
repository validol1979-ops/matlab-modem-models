// Portable, resource-shared DF2T SOS. See docs/RTL_SOS.md for timing and bounds.
// Coefficients are already normalized, balanced and quantized by SOSFilterFixed.
// State persists across TLAST; configuration/reset clears it. Fatal configuration
// error is sticky until reset; arithmetic clipping only sets saturated.
module sos_iir #(
  parameter int COEF_FRAC = 28,
  parameter int STATE_BITS = 64,
  parameter bit RESET_ACTIVE = 1
)(
  input logic clk, rst,
  input logic cfg_valid, cfg_last,
  input logic signed [31:0] cfg_b0, cfg_b1, cfg_b2, cfg_a1, cfg_a2,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  input logic m_ready,
  output logic error, saturated
);
  // A product needs 50 bits. Two products plus state need max(STATE_BITS,51)+1.
  localparam int AW = (STATE_BITS > 51 ? STATE_BITS : 51) + 1;
  localparam logic signed [AW-1:0] STATE_MAX = (AW'(1) << (STATE_BITS-1))-1;
  localparam logic signed [AW-1:0] OUT_MAX = AW'(131071);
  localparam logic signed [AW-1:0] HALF = AW'(1) << (COEF_FRAC-1);
  localparam logic signed [33:0] ONE = 34'sd1 << COEF_FRAC;
  initial begin
    if (COEF_FRAC < 16 || COEF_FRAC > 28 || STATE_BITS < 40 || STATE_BITS > 64)
      $fatal(1,"[PARAMETER] SOS needs COEF_FRAC=16..28, STATE_BITS=40..64");
  end
  function automatic logic signed [17:0] clip_output(input logic signed [AW-1:0] v);
    if (v > OUT_MAX) return 18'sd131071;
    if (v < -OUT_MAX) return -18'sd131071;
    return 18'(v);
  endfunction
  function automatic logic signed [STATE_BITS-1:0] clip_state(input logic signed [AW-1:0] v);
    if (v > STATE_MAX) return STATE_BITS'(STATE_MAX);
    if (v < -STATE_MAX) return STATE_BITS'(-STATE_MAX);
    return STATE_BITS'(v);
  endfunction
  wire reset_now = rst == RESET_ACTIVE;
  // Strict Jury/Schur conditions for z^2 + a1*z + a2; exact integer tests.
  wire stable_row = 34'(cfg_a2) > -ONE && 34'(cfg_a2) < ONE
                 && ONE + 34'(cfg_a1) + 34'(cfg_a2) > 0
                 && ONE - 34'(cfg_a1) + 34'(cfg_a2) > 0;
  typedef enum logic [3:0] {IDLE, LOAD_Y, MULT_Y, ROUND_Y, MULT_B1,
    SAVE_B1, MULT_A1, UPDATE1, MULT_B2, SAVE_B2, MULT_A2, UPDATE2} phase_t;
  phase_t phase;
  logic [2:0] cfg_count, sections;
  logic [1:0] section;
  logic in_frame, pending_last, out_valid;
  logic signed [31:0] coeff [0:3][0:4]; // b0,b1,b2,a1,a2
  logic signed [STATE_BITS-1:0] state1 [0:1][0:3], state2 [0:1][0:3];
  logic signed [17:0] x [0:1], y [0:1], operand [0:1];
  logic signed [31:0] multiplier_coef;
  logic signed [49:0] product [0:1], saved_product [0:1];
  wire cfg_take = cfg_valid && cfg_ready;
  assign cfg_ready = !reset_now && !error && !in_frame && phase == IDLE && !out_valid;
  assign s_ready = !reset_now && !error && configured && phase == IDLE && !out_valid && !cfg_take;
  assign m_valid = !reset_now && out_valid;
  wire take = s_valid && s_ready;
  wire signed [AW-1:0] raw_y [0:1], rounded_y [0:1], raw_state [0:1];
  for (genvar c=0; c<2; c=c+1) begin : g_channel
    assign raw_y[c] = AW'(product[c]) + AW'(state1[c][section]) + HALF;
    assign rounded_y[c] = raw_y[c] >>> COEF_FRAC;
    assign raw_state[c] = AW'(saved_product[c]) - AW'(product[c])
                       + (phase == UPDATE1 ? AW'(state2[c][section]) : AW'(0));
    // Registered operands and registered full product; data registers need no reset.
    always_ff @(posedge clk) product[c] <= multiplier_coef * operand[c];
  end
  always_ff @(posedge clk) begin
    if (reset_now) begin
      phase <= IDLE; cfg_count <= 0; sections <= 0; section <= 0;
      in_frame <= 0; pending_last <= 0; out_valid <= 0;
      configured <= 0; error <= 0; saturated <= 0;
      for (int c=0; c<2; c=c+1)
        for (int j=0; j<4; j=j+1) begin state1[c][j] <= 0; state2[c][j] <= 0; end
    end else begin
      if (out_valid && m_ready) begin
        out_valid <= 0;
        if (m_last) in_frame <= 0;
      end
      if (cfg_take) begin
        configured <= 0;
        if (!stable_row || cfg_count == 3'd4
            || (cfg_last && !(cfg_count == 0 || cfg_count == 1 || cfg_count == 3))) begin
          error <= 1;
        end else begin
          coeff[2'(cfg_count)][0] <= cfg_b0; coeff[2'(cfg_count)][1] <= cfg_b1;
          coeff[2'(cfg_count)][2] <= cfg_b2; coeff[2'(cfg_count)][3] <= cfg_a1;
          coeff[2'(cfg_count)][4] <= cfg_a2;
          cfg_count <= cfg_count + 1'b1;
          if (cfg_last) begin
            cfg_count <= 0; sections <= cfg_count + 1'b1; configured <= 1; saturated <= 0;
            for (int c=0; c<2; c=c+1)
              for (int j=0; j<4; j=j+1) begin state1[c][j] <= 0; state2[c][j] <= 0; end
          end
        end
      end
      case (phase)
        IDLE: if (take) begin
          x[0] <= s_re; x[1] <= s_im; section <= 0;
          pending_last <= s_last; in_frame <= 1; phase <= LOAD_Y;
        end
        LOAD_Y: begin
          multiplier_coef <= coeff[section][0];
          for (int c=0; c<2; c=c+1) operand[c] <= x[c];
          phase <= MULT_Y;
        end
        MULT_Y: phase <= ROUND_Y;
        ROUND_Y: begin
          for (int c=0; c<2; c=c+1) begin
            y[c] <= clip_output(rounded_y[c]); operand[c] <= x[c];
            if (rounded_y[c] > OUT_MAX || rounded_y[c] < -OUT_MAX) saturated <= 1;
          end
          multiplier_coef <= coeff[section][1]; phase <= MULT_B1;
        end
        MULT_B1: phase <= SAVE_B1;
        SAVE_B1: begin
          for (int c=0; c<2; c=c+1) begin saved_product[c] <= product[c]; operand[c] <= y[c]; end
          multiplier_coef <= coeff[section][3]; phase <= MULT_A1;
        end
        MULT_A1: phase <= UPDATE1;
        UPDATE1: begin
          for (int c=0; c<2; c=c+1) begin
            state1[c][section] <= clip_state(raw_state[c]); operand[c] <= x[c];
            if (raw_state[c] > STATE_MAX || raw_state[c] < -STATE_MAX) saturated <= 1;
          end
          multiplier_coef <= coeff[section][2]; phase <= MULT_B2;
        end
        MULT_B2: phase <= SAVE_B2;
        SAVE_B2: begin
          for (int c=0; c<2; c=c+1) begin saved_product[c] <= product[c]; operand[c] <= y[c]; end
          multiplier_coef <= coeff[section][4]; phase <= MULT_A2;
        end
        MULT_A2: phase <= UPDATE2;
        UPDATE2: begin
          for (int c=0; c<2; c=c+1) begin
            state2[c][section] <= clip_state(raw_state[c]);
            if (raw_state[c] > STATE_MAX || raw_state[c] < -STATE_MAX) saturated <= 1;
          end
          if (3'(section) + 3'd1 == sections) begin
            m_re <= y[0]; m_im <= y[1]; m_last <= pending_last; out_valid <= 1; phase <= IDLE;
          end else begin
            for (int c=0; c<2; c=c+1) x[c] <= y[c];
            section <= section + 1'b1; phase <= LOAD_Y;
          end
        end
        default: phase <= IDLE;
      endcase
    end
  end
endmodule
