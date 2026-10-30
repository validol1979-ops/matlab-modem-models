// Complex CIC: updated-stage integrators -> keep phase R-1 -> M-delay combs.
// All recurrence arithmetic is modulo 2**ACC_WIDTH. See docs/RTL_CIC.md.
module cic_decimator #(
  parameter int STAGES = 3,
  parameter int DELAY = 1,
  parameter int MAX_RATE = 32,
  parameter int ACC_WIDTH = 18 + $clog2((MAX_RATE*DELAY)**STAGES),
  parameter bit NORMALIZE = 0,
  parameter bit RESET_ACTIVE = 1,
  parameter int OUT_WIDTH = NORMALIZE ? 18 : ACC_WIDTH
)(
  input logic clk, rst,
  input logic cfg_valid,
  input logic [5:0] cfg_rate,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [OUT_WIDTH-1:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  // MAX_RATE*DELAY <=64, gain <=2**30, hence 31 unsigned gain bits.
  // The default width expression is exact for the supported gain (<=2**30).
  localparam int QW = ACC_WIDTH+2 > 33 ? ACC_WIDTH+2 : 33;
  wire reset_now = rst == RESET_ACTIVE;
  logic frame_open, out_valid, out_last;
  logic [5:0] rate, phase;
  logic [30:0] gain, cfg_gain;
  logic signed [OUT_WIDTH-1:0] out_re, out_im;
  logic signed [ACC_WIDTH-1:0] integ [0:1][0:STAGES-1];
  logic signed [ACC_WIDTH-1:0] history [0:1][0:STAGES-1][0:DELAY-1];
  logic signed [ACC_WIDTH-1:0] isum [0:1][0:STAGES];
  logic signed [ACC_WIDTH-1:0] comb [0:1][0:STAGES];
  wire cfg_take = cfg_valid && cfg_ready;
  wire take = s_valid && s_ready;
  wire completes = phase == rate-6'd1;

  initial begin
    if (!(STAGES==1 || STAGES==2 || STAGES==3 || STAGES==5) ||
        DELAY<1 || DELAY>2 || MAX_RATE<1 || MAX_RATE>32 ||
        ACC_WIDTH<18 || ACC_WIDTH>128 || OUT_WIDTH!=(NORMALIZE?18:ACC_WIDTH))
      $fatal(1,"[PARAMETER] invalid CIC geometry/width");
  end

  always_comb begin
    cfg_gain = 31'd1;
    for (int k=0; k<STAGES; k=k+1)
      cfg_gain = cfg_gain * (31'(cfg_rate) * 31'(DELAY));
  end
  assign cfg_ready = !reset_now && !error && !frame_open && !out_valid;
  // Independent of s_valid. A pending, currently illegal cfg cannot stall a frame.
  assign s_ready = !reset_now && configured && !error && !cfg_take &&
                   (!out_valid || m_ready);
  assign m_valid = !reset_now && out_valid;
  assign m_last = out_last;
  assign m_re = out_re;
  assign m_im = out_im;
  always_comb begin
    isum[0][0] = ACC_WIDTH'(s_re);
    isum[1][0] = ACC_WIDTH'(s_im);
    for (int c=0; c<2; c=c+1) begin
      for (int k=0; k<STAGES; k=k+1)
        isum[c][k+1] = integ[c][k] + isum[c][k];
      comb[c][0] = isum[c][STAGES];
      for (int k=0; k<STAGES; k=k+1)
        comb[c][k+1] = comb[c][k] - history[c][k][DELAY-1];
    end
  end

  // Python floor((2*v+G)/(2*G)); SV division truncates toward zero, so a
  // negative nonintegral quotient needs one correction. QW covers 2*v+G,
  // the positive divisor 2*G and every signed intermediate, even for AW=18.
  function automatic logic signed [OUT_WIDTH-1:0] format_output(
    input logic signed [ACC_WIDTH-1:0] v
  );
    logic signed [QW-1:0] numerator, denominator, quotient;
    if (NORMALIZE) begin
      numerator = (QW'(v) <<< 1) + QW'({1'b0,gain});
      denominator = QW'({1'b0,gain}) <<< 1;
      quotient = numerator / denominator;
      if (numerator < 0 && numerator % denominator != 0) quotient = quotient-1;
      if (quotient > QW'(131071)) return OUT_WIDTH'(131071);
      if (quotient < -QW'(131072)) return OUT_WIDTH'(-131072);
      return OUT_WIDTH'(quotient);
    end
    return OUT_WIDTH'(v);
  endfunction

  always_ff @(posedge clk) begin
    if (reset_now) begin
      configured <= 0;
      error <= 0;
      frame_open <= 0;
      out_valid <= 0;
      rate <= 1;
      gain <= 1;
      phase <= 0;
      for (int c=0; c<2; c=c+1)
        for (int k=0; k<STAGES; k=k+1) begin
          integ[c][k] <= '0;
          for (int d=0; d<DELAY; d=d+1) history[c][k][d] <= '0;
        end
    end else begin
      if (out_valid && m_ready) out_valid <= 0;
      if (cfg_take) begin
        if (cfg_rate<1 || cfg_rate>6'(MAX_RATE)) begin
          error <= 1;
          configured <= 0;
        end else begin
          configured <= 1;
          rate <= cfg_rate;
          gain <= cfg_gain;
          phase <= 0;
          frame_open <= 0;
          for (int c=0; c<2; c=c+1)
            for (int k=0; k<STAGES; k=k+1) begin
              integ[c][k] <= '0;
              for (int d=0; d<DELAY; d=d+1) history[c][k][d] <= '0;
            end
        end
      end else if (take) begin
        if (s_last && !completes) begin
          // Atomic numeric rejection. Sticky diagnostic/fail-stop until reset.
          error <= 1;
          configured <= 0;
        end else begin
          frame_open <= !s_last;
          for (int c=0; c<2; c=c+1)
            for (int k=0; k<STAGES; k=k+1) begin
              integ[c][k] <= isum[c][k+1];
              if (completes) begin
                history[c][k][0] <= comb[c][k];
                for (int d=1; d<DELAY; d=d+1)
                  history[c][k][d] <= history[c][k][d-1];
              end
            end
          if (completes) begin
            phase <= 0;
            out_valid <= 1;
            out_last <= s_last;
            out_re <= format_output(comb[0][STAGES]);
            out_im <= format_output(comb[1][STAGES]);
          end else phase <= phase+6'd1;
        end
      end
    end
  end
endmodule
