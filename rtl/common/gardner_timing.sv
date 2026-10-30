// Gardner timing loop with cubic interpolation (research_core timing; bit-exact reference
// sync_fixed.timing). Configuration (one transfer, between transactions): sps (>= 2), the
// output count, the start position P0 (Q32 samples) and K3, K4 = round(k*2^32). A transaction
// is one Q15 signal of L <= 16384 samples (s_last on its last); it is stored in cpm_samples
// (frame 0), then `count` outputs follow (m_last on the last): with P16 = P >> 16,
// early/mid/late = interp(P16 -+ sps*2^15) (the pilot's cubic table, taps outside the signal
// read as zero), error = clip(re((late - early)*conj(mid)), +-2^30) in Q30, rate += rnd(K4*error,
// 30), P += sps*2^32 + rate + rnd(K3*error, 30). Outputs: mid (Q15) and P16. An output takes
// about 14 clocks (three interpolations, error, products, update); the input waits while the
// outputs of the previous transaction are produced.
// error is sticky: a signal longer than 16384 samples or sps < 2.
module gardner_timing #(
  parameter bit RESET_ACTIVE = 1,
  parameter TABLE_DIR = "rtl/modems/bpsk_costas_2008_08_25/tables"
)(
  input logic clk, rst,
  input logic cfg_valid,
  input logic [7:0] cfg_sps,
  input logic [15:0] cfg_count,
  input logic [47:0] cfg_position,
  input logic [31:0] cfg_k3, cfg_k4,
  output logic cfg_ready, configured,
  input logic s_valid, s_last,
  input logic signed [17:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [17:0] m_re, m_im,
  output logic signed [31:0] m_position,
  input logic m_ready,
  output logic error
);
  wire reset_now = rst == RESET_ACTIVE;
  localparam logic signed [31:0] ONE30 = 32'sd1073741824;
  typedef enum logic [2:0] {LOAD, ISSUE, COLLECT, GRADIENT, UPDATE} state_t;
  state_t state;
  logic [7:0] sps;
  logic [15:0] count, done_count;
  logic [47:0] position0;
  logic [31:0] k3, k4;
  logic [14:0] wcount, length;
  logic signed [55:0] p, rate;
  logic [1:0] issued, collected;
  logic signed [17:0] e_re, e_im, mid_re, mid_im, l_re, l_im;
  logic signed [31:0] clipped;
  logic signed [63:0] d3, d4;
  assign cfg_ready = !reset_now && state == LOAD && wcount == '0 && !m_valid;
  wire cfg_take = cfg_valid && cfg_ready;
  wire cfg_usable = cfg_sps >= 8'd2 && cfg_count != '0;
  // A valid idle configuration can coherently accept the first sample too. Invalid
  // configuration must leave the load buffer empty, allowing later recovery.
  assign s_ready = !reset_now && configured && state == LOAD && (!cfg_take || cfg_usable);
  wire take = s_valid && s_ready;
  // Interpolation positions in Q8 samples: P16 >> 8 = P >> 24, half a symbol = sps << 7.
  wire signed [23:0] centre = 24'(p >>> 24);
  wire signed [23:0] offset = $signed({9'd0, sps, 7'd0});
  wire signed [23:0] q_position = issued == 2'd0 ? centre - offset : issued == 2'd1 ? centre : centre + offset;
  wire q_valid = state == ISSUE;
  wire r_valid;
  wire signed [17:0] r_re, r_im;
  wire [14:0] r_tag;
  // Lane 1 (the next sample) is not needed.
  /* verilator lint_off PINCONNECTEMPTY */
  cpm_samples #(.RESET_ACTIVE(RESET_ACTIVE),.TABLE_DIR(TABLE_DIR)) samples(
    .clk(clk),.rst(rst),.wr_en(take),.wr_frame(1'b0),.wr_index(wcount),.wr_re(s_re),.wr_im(s_im),
    .ce(1'b1),.s_valid(q_valid),.s_frame(1'b0),.s_position(q_position),.s_length(length),.s_tag({13'd0, issued}),
    .m_valid(r_valid),.m_re0(r_re),.m_im0(r_im),.m_re1(),.m_im1(),.m_tag(r_tag));
  /* verilator lint_on PINCONNECTEMPTY */
  // re((late - early) conj(mid)) in Q30, clipped to +-1.
  wire signed [36:0] gardner = 37'(19'(l_re) - 19'(e_re))*37'(mid_re) + 37'(19'(l_im) - 19'(e_im))*37'(mid_im);
  always_ff @(posedge clk) begin
    if (reset_now) begin
      configured <= 0; error <= 0; state <= LOAD; wcount <= '0; m_valid <= 0;
    end else begin
      if (cfg_take) begin
        sps <= cfg_sps; count <= cfg_count; position0 <= cfg_position; k3 <= cfg_k3; k4 <= cfg_k4;
        configured <= cfg_usable; if (cfg_sps < 8'd2) error <= 1;
      end
      if (m_valid && m_ready) m_valid <= 0;
      case (state)
        LOAD: if (take) begin
          wcount <= wcount + 1'b1;
          if (wcount == 15'd16383 && !s_last) error <= 1;
          if (s_last) begin
            length <= wcount + 1'b1; state <= ISSUE; issued <= '0; collected <= '0;
            // A single-sample transaction starts on this same configuration edge.
            p <= $signed({8'd0, cfg_take ? cfg_position : position0}); rate <= '0; done_count <= '0;
          end
        end
        // Three requests (early, mid, late), then wait for their results.
        ISSUE: if (issued == 2'd2) state <= COLLECT; else issued <= issued + 1'b1;
        // Only the request index travels in the tag; its upper bits are zero.
        COLLECT: if (r_valid && r_tag[14:2] == '0) begin
          case (r_tag[1:0])
            2'd0: begin e_re <= r_re; e_im <= r_im; end
            2'd1: begin mid_re <= r_re; mid_im <= r_im; end
            default: begin l_re <= r_re; l_im <= r_im; end
          endcase
          collected <= collected + 1'b1;
          if (collected == 2'd2) state <= GRADIENT;
        end
        GRADIENT: if (!m_valid || m_ready) begin
          clipped <= gardner > 37'(ONE30) ? ONE30 : gardner < -(37'(ONE30)) ? -ONE30 : 32'(gardner);
          m_valid <= 1; m_re <= mid_re; m_im <= mid_im; m_position <= 32'(p >>> 16); m_last <= done_count == count - 1'b1;
          state <= UPDATE; issued <= 2'd3;
        end
        UPDATE: begin
          // issued counts the clocks of this state: products first, then the position update.
          if (issued == 2'd3) begin d3 <= 64'($signed({1'b0, k3}))*64'(clipped); d4 <= 64'($signed({1'b0, k4}))*64'(clipped); issued <= '0; end
          else begin
            rate <= rate + 56'((d4 + 64'sd536870912) >>> 30);
            p <= p + ($signed({40'd0, sps, 8'd0}) <<< 24) + rate + 56'((d4 + 64'sd536870912) >>> 30) + 56'((d3 + 64'sd536870912) >>> 30);
            done_count <= done_count + 1'b1; collected <= '0;
            if (done_count == count - 1'b1) begin state <= LOAD; wcount <= '0; end else state <= ISSUE;
          end
        end
        default: state <= LOAD;
      endcase
    end
  end
endmodule
