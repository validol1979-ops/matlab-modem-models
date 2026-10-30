// OM-LSA spectral gain (the per-bin part of omlsa_fixed.enhance). Input: the STFT frames of one
// transaction (N bins each, X/N in Q19, s_last on the last bin); output: the same frames times the
// gain (m_last on the last bin). The first `nnoise` frames are stored (frame RAM), their powers
// summed per bin; then noise = max(divide(sum, nnoise), 1) and its normalised reciprocal are
// formed per bin (fxp_divide_seq, norm_reciprocal), the stored frames are processed and the later
// frames follow from the input. Per bin (Q16 ratios, tables in MEM_DIR):
//   gamma = min(rnd(P*Rn, Zn - 16), GMAX); xi = clip(rnd(A prev + (65536 - A) max(gamma - 65536, 0), 16), 1, GMAX);
//   w = 65536 - R(65536 + xi); v = min(rnd(gamma w, 16), GMAX);
//   G1 = clip(rnd(w TF[v], 12), GMIN, 65536); t = min(rnd((65536 + xi) TE[v], 18), GMAX); p = R(65536 + t);
//   a = LN05 + rnd(p (LN[G1 >> 4] - LN05), 16); G = EXPN[min(max(-a, 0) >> 6, 4095)];
//   out = (rnd(re G, 16), rnd(im G, 16)); prev = min(rnd(rnd(G G, 16) gamma, 16), GMAX).
// A bin takes 12 clocks (one ROM read per step); the noise set-up about 130 clocks per bin.
// error is sticky: a transaction shorter than nnoise frames (its frames are dropped).
// Intermediate widths (docs/RTL_OMLSA_WIDTHS.md, common/python/omlsa_gain_widths.py) are exact
// for the full register/ROM codes, power <= 2^47 and the interface contract alpha <= 65536;
// the former 128-bit layout stays legal for comparison. UNSAFE_WIDTH_TEST is verification
// only: it lifts the lower-width guard so a bench can show that one bit less fails.
module omlsa_gain #(
  parameter int LOG2N = 5,
  parameter bit RESET_ACTIVE = 1,
  parameter MEM_DIR = "rtl/common/mem",
  parameter int RECIP_WIDTH = 18,               // R(u) rounding, any shift
  parameter int GAMMA_WIDTH = 72,               // power rn and its variable rounding
  parameter int XI_WIDTH = 47,                  // A prev + (65536 - A) excess, + 2^15
  parameter int V_WIDTH = 48,                   // gamma w, + 2^15
  parameter int G1_WIDTH = 37,                  // w TF, + 2^11
  parameter int T_WIDTH = 48,                   // (65536 + xi) TE, + 2^17
  parameter int A_WIDTH = 37,                   // p (LN - LN05), + 2^15 (signed)
  parameter int OUT_WIDTH = 41,                 // re G, im G, + 2^15 (signed)
  parameter int GG_WIDTH = 34,                  // G G, + 2^15
  parameter int PREV_WIDTH = 49,                // rnd(G G, 16) gamma, + 2^15
  parameter bit UNSAFE_WIDTH_TEST = 0
)(
  input logic clk, rst,
  input logic [4:0] nnoise,                     // 1..16
  input logic [16:0] alpha,                     // round(alpha*65536)
  input logic s_valid, s_last,
  input logic signed [23:0] s_re, s_im,
  output logic s_ready,
  output logic m_valid, m_last,
  output logic signed [23:0] m_re, m_im,
  input logic m_ready,
  output logic error
);
  localparam int N = 1 << LOG2N;
  localparam logic [30:0] GMAX = 31'h7fffffff;
  localparam logic [16:0] GMIN = 17'd3277;
  localparam logic signed [20:0] LN05 = -21'sd196328;
  initial if ((!UNSAFE_WIDTH_TEST && (RECIP_WIDTH < 18 || GAMMA_WIDTH < 72 || XI_WIDTH < 47 || V_WIDTH < 48 || G1_WIDTH < 37
      || T_WIDTH < 48 || A_WIDTH < 37 || OUT_WIDTH < 41 || GG_WIDTH < 34 || PREV_WIDTH < 49))
      || RECIP_WIDTH < 2 || GAMMA_WIDTH < 32 || XI_WIDTH < 32 || V_WIDTH < 32 || G1_WIDTH < 18 || T_WIDTH < 32
      || A_WIDTH < 22 || OUT_WIDTH < 25 || GG_WIDTH < 17 || PREV_WIDTH < 32
      || RECIP_WIDTH > 128 || GAMMA_WIDTH > 128 || XI_WIDTH > 128 || V_WIDTH > 128 || G1_WIDTH > 128
      || T_WIDTH > 128 || A_WIDTH > 128 || OUT_WIDTH > 128 || GG_WIDTH > 128 || PREV_WIDTH > 128)
    $fatal(1, "[PARAMETER] OM-LSA widths require RECIP>=18 GAMMA>=72 XI>=47 V>=48 G1>=37 T>=48 A>=37 OUT>=41 GG>=34 PREV>=49, all <=128");
  wire reset_now = rst == RESET_ACTIVE;
  function automatic logic [5:0] bits(input logic [31:0] v);
    bits = '0;
    for (int b = 0; b < 32; b++) if (v[b]) bits = 6'(b + 1);
  endfunction
  // Log-table index: (bit length - 1)*256 + the 8 bits after the leading one (v = 0 -> row 0).
  function automatic logic [12:0] log_index(input logic [30:0] v);
    logic [5:0] s;
    logic [39:0] wide;
    s = bits({1'b0, v}); if (s == 0) s = 6'd1;
    wide = 40'(v) << 8;
    return (13'(s - 6'd1) << 8) + 13'((wide >> (s - 1'b1)) & 40'd255);
  endfunction

  typedef enum logic [4:0] {COLLECT, NDIV, NDIVW, NREC, NRECW, PICK, G0, G1, G2, G3, G4, G5, G6, G7, G8, G9, G10, G11, G12, G13, G14, G15, G16, G17, G18} state_t;
  state_t state;
  logic [LOG2N-1:0] k;
  logic [4:0] frames_in, frame_out, stored;
  logic stored_last;                            // the transaction ended inside the stored frames
  logic [52:0] sum [0:N-1];
  logic [23:0] rn [0:N-1];
  logic [6:0] zn [0:N-1];
  logic [30:0] prev [0:N-1];
  // Frame RAM: 16 frames of N bins.
  wire [47:0] frame_q;
  wire store = state == COLLECT && s_valid;
  wire [LOG2N+3:0] rd_addr = {frame_out[3:0], k};
  sync_ram #(.WIDTH(48),.ADDR_WIDTH(LOG2N+4)) frame_ram(
    .clk(clk),.wr_en(store && frames_in < 5'd16),.rd_en(state == PICK),.wr_addr({frames_in[3:0], k}),.rd_addr(rd_addr),
    .wr_data({s_re, s_im}),.rd_data(frame_q));
  // Noise set-up.
  logic div_start, rec_start;
  wire div_busy, div_done;
  wire signed [63:0] div_result;
  fxp_divide_seq #(.NUM_WIDTH(64),.DEN_WIDTH(5),.RESET_ACTIVE(RESET_ACTIVE)) divider(
    .clk(clk),.rst(rst),.start(div_start),.numerator(64'(sum[k])),.denominator(nnoise),
    .busy(div_busy),.done(div_done),.result(div_result));
  logic [52:0] noise;
  wire rec_done, rec_zero;
  wire [23:0] rec_r;
  wire [6:0] rec_shift;
  norm_reciprocal #(.WIDTH(53),.RESET_ACTIVE(RESET_ACTIVE)) recip_noise(
    .clk(clk),.rst(rst),.start(rec_start),.energy(noise),.done(rec_done),.zero(rec_zero),.r(rec_r),.shift(rec_shift));
  // Per-bin registers.
  logic signed [23:0] re, im;
  logic last;
  logic [48:0] power;
  logic [30:0] gamma, xi, v, t;
  logic [16:0] w, g1, p, g;
  logic signed [20:0] a;
  // ROMs (address registered in the step before the use).
  logic [10:0] recip_addr;
  logic [12:0] tab_addr, ln_addr;
  logic [11:0] expn_addr;
  logic [5:0] rs;                               // bit length of the reciprocal argument
  wire [16:0] recip_q, expn_q;
  wire [19:0] tf_q;
  wire [15:0] te_q;
  wire [18:0] ln_q;
  sync_rom #(.WIDTH(17),.ADDR_WIDTH(11),.INIT_FILE({MEM_DIR,"/omlsa_recip.mem"})) rom_recip(.clk(clk),.rd_en(1'b1),.rd_addr(recip_addr),.rd_data(recip_q));
  sync_rom #(.WIDTH(20),.ADDR_WIDTH(13),.INIT_FILE({MEM_DIR,"/omlsa_tf.mem"})) rom_tf(.clk(clk),.rd_en(1'b1),.rd_addr(tab_addr),.rd_data(tf_q));
  sync_rom #(.WIDTH(16),.ADDR_WIDTH(13),.INIT_FILE({MEM_DIR,"/omlsa_te.mem"})) rom_te(.clk(clk),.rd_en(1'b1),.rd_addr(tab_addr),.rd_data(te_q));
  sync_rom #(.WIDTH(19),.ADDR_WIDTH(13),.INIT_FILE({MEM_DIR,"/omlsa_ln.mem"})) rom_ln(.clk(clk),.rd_en(1'b1),.rd_addr(ln_addr),.rd_data(ln_q));
  sync_rom #(.WIDTH(17),.ADDR_WIDTH(12),.INIT_FILE({MEM_DIR,"/omlsa_expn.mem"})) rom_expn(.clk(clk),.rd_en(1'b1),.rd_addr(expn_addr),.rd_data(expn_q));
  // R(u) = rnd(RECIP[top 12 bits - 2048], s - 17) for u >= 65536.
  function automatic logic [10:0] recip_index(input logic [31:0] u, input logic [5:0] s); return 11'(u >> (s - 6'd12)); endfunction
  wire [31:0] one_xi = 32'd65536 + 32'(xi);
  wire [31:0] one_t = 32'd65536 + 32'(t);
  wire [30:0] excess = gamma > 31'd65536 ? gamma - 31'd65536 : 31'd0;
  // Raw products, the half-up rounding and the limiter inputs, each in its proven width.
  // Variable shifts: s = 0 passes the value, s >= width gives 0 (as the 128-bit form does).
  wire [6:0] recip_shift = 7'(rs) - 7'd17;
  wire [6:0] gamma_shift = zn[k] - 1'b1;
  // recip_round, a_round and out_round keep the exact rounded value for the raw monitors; the
  // datapath keeps only its former 17/21/24 low bits (the unchanged truncating casts).
  /* verilator lint_off UNUSEDSIGNAL */
  wire [RECIP_WIDTH-1:0] recip_round = recip_shift == 7'd0 ? RECIP_WIDTH'(recip_q)
    : (RECIP_WIDTH'(recip_q) + (RECIP_WIDTH'(1) << (recip_shift - 1'b1))) >> recip_shift;
  /* verilator lint_on UNUSEDSIGNAL */
  wire [16:0] recip_value = rs == 6'd17 ? recip_q : 17'(recip_round);
  wire [GAMMA_WIDTH-1:0] gamma_raw = GAMMA_WIDTH'(power)*GAMMA_WIDTH'(rn[k]);
  wire [GAMMA_WIDTH-1:0] gamma_round = gamma_shift == 7'd0 ? gamma_raw
    : (gamma_raw + (GAMMA_WIDTH'(1) << (gamma_shift - 1'b1))) >> gamma_shift;
  wire [XI_WIDTH-1:0] xi_raw = XI_WIDTH'(alpha)*XI_WIDTH'(prev[k]) + XI_WIDTH'(17'd65536 - alpha)*XI_WIDTH'(excess);
  wire [XI_WIDTH-1:0] xi_round = (xi_raw + (XI_WIDTH'(1) << 15)) >> 16;
  wire [30:0] xi_next = xi_round > XI_WIDTH'(GMAX) ? GMAX : 31'(xi_round);
  wire [V_WIDTH-1:0] v_raw = V_WIDTH'(gamma)*V_WIDTH'(w);
  wire [V_WIDTH-1:0] v_round = (v_raw + (V_WIDTH'(1) << 15)) >> 16;
  wire [G1_WIDTH-1:0] g1_raw = G1_WIDTH'(w)*G1_WIDTH'(tf_q);
  wire [G1_WIDTH-1:0] g1_next = (g1_raw + (G1_WIDTH'(1) << 11)) >> 12;
  wire [T_WIDTH-1:0] t_raw = T_WIDTH'(one_xi)*T_WIDTH'(te_q);
  wire [T_WIDTH-1:0] t_round = (t_raw + (T_WIDTH'(1) << 17)) >> 18;
  wire signed [A_WIDTH-1:0] a_raw = A_WIDTH'(p)*A_WIDTH'(21'($signed(ln_q)) - LN05);
  wire signed [OUT_WIDTH-1:0] out_raw_re = OUT_WIDTH'(re)*OUT_WIDTH'($signed({1'b0, g}));
  wire signed [OUT_WIDTH-1:0] out_raw_im = OUT_WIDTH'(im)*OUT_WIDTH'($signed({1'b0, g}));
  /* verilator lint_off UNUSEDSIGNAL */
  wire signed [A_WIDTH-1:0] a_round = (a_raw + (A_WIDTH'(1) <<< 15)) >>> 16;
  wire signed [OUT_WIDTH-1:0] out_round_re = (out_raw_re + (OUT_WIDTH'(1) <<< 15)) >>> 16;
  wire signed [OUT_WIDTH-1:0] out_round_im = (out_raw_im + (OUT_WIDTH'(1) <<< 15)) >>> 16;
  /* verilator lint_on UNUSEDSIGNAL */
  wire [GG_WIDTH-1:0] gg_raw = GG_WIDTH'(g)*GG_WIDTH'(g);
  // gg_round <= 262140 (18 bits): with GG_WIDTH > PREV_WIDTH its zero upper bits are not consumed.
  /* verilator lint_off UNUSEDSIGNAL */
  wire [GG_WIDTH-1:0] gg_round = (gg_raw + (GG_WIDTH'(1) << 15)) >> 16;
  /* verilator lint_on UNUSEDSIGNAL */
  wire [PREV_WIDTH-1:0] prev_raw = PREV_WIDTH'(gg_round)*PREV_WIDTH'(gamma);
  wire [PREV_WIDTH-1:0] prev_round = (prev_raw + (PREV_WIDTH'(1) << 15)) >> 16;
  assign s_ready = !reset_now && (state == COLLECT || state == PICK && frame_out >= stored && !stored_last);
  wire take_live = s_valid && s_ready && state == PICK;
  always_ff @(posedge clk) begin
    if (reset_now) begin
      state <= COLLECT; k <= '0; frames_in <= '0; frame_out <= '0; stored <= '0; stored_last <= 0; error <= 0; m_valid <= 0;
      div_start <= 0; rec_start <= 0;
      for (int b = 0; b < N; b++) begin sum[b] <= '0; prev[b] <= 31'd65536; end
    end else begin
      div_start <= 0; rec_start <= 0;
      if (m_valid && m_ready) m_valid <= 0;
      // noise >= 1, so a zero energy would be an internal fault.
      if (rec_zero) error <= 1;
      case (state)
        // Store the first nnoise frames, sum the powers.
        COLLECT: if (s_valid) begin
          sum[k] <= sum[k] + 53'(49'(s_re*s_re) + 49'(s_im*s_im));
          k <= k + 1'b1;
          if (k == LOG2N'(N-1)) begin
            frames_in <= frames_in + 1'b1;
            if (s_last && frames_in + 1'b1 < nnoise) begin
              // Too short for the noise estimate: drop it.
              error <= 1; frames_in <= '0; for (int b = 0; b < N; b++) sum[b] <= '0;
            end else if (frames_in + 1'b1 == nnoise) begin
              stored <= nnoise; stored_last <= s_last; state <= NDIV;
            end
          end else if (s_last) begin error <= 1; frames_in <= '0; k <= '0; for (int b = 0; b < N; b++) sum[b] <= '0; end
        end
        // Per bin: noise = max(divide(sum, nnoise), 1), then its reciprocal.
        NDIV: if (!div_busy) begin div_start <= 1; state <= NDIVW; end
        NDIVW: if (div_done) begin noise <= div_result == 0 ? 53'd1 : 53'(div_result); rec_start <= 1; state <= NREC; end
        NREC: state <= NRECW;
        NRECW: if (rec_done) begin
          rn[k] <= rec_r; zn[k] <= rec_shift;
          if (k == LOG2N'(N-1)) begin k <= '0; frame_out <= '0; state <= PICK; end
          else begin k <= k + 1'b1; state <= NDIV; end
        end
        // The next bin: a stored frame from the RAM, else the live input.
        PICK: if (frame_out < stored) state <= G0;
          else if (take_live) begin re <= s_re; im <= s_im; last <= s_last; state <= G1; end
        G0: begin re <= $signed(frame_q[47:24]); im <= $signed(frame_q[23:0]); last <= stored_last && frame_out == stored - 1'b1 && k == LOG2N'(N-1); state <= G1; end
        G1: begin power <= 49'(re*re) + 49'(im*im); state <= G2; end
        G2: begin
          // zn = Z - 15, so Z - 16 = zn - 1.
          gamma <= gamma_round > GAMMA_WIDTH'(GMAX) ? GMAX : 31'(gamma_round);
          state <= G3;
        end
        G3: begin
          xi <= xi_next == 31'd0 ? 31'd1 : xi_next;
          state <= G4;
        end
        // w = 65536 - R(65536 + xi): address, ROM read, value.
        G4: begin rs <= bits(one_xi); recip_addr <= recip_index(one_xi, bits(one_xi)); state <= G5; end
        G5: state <= G6;
        G6: begin w <= 17'(17'd65536 - recip_value); state <= G7; end
        G7: begin v <= v_round > V_WIDTH'(GMAX) ? GMAX : 31'(v_round); state <= G8; end
        G8: begin tab_addr <= log_index(v); state <= G9; end
        G9: state <= G10;
        G10: begin
          g1 <= g1_next < G1_WIDTH'(GMIN) ? GMIN : g1_next > G1_WIDTH'(65536) ? 17'd65536 : 17'(g1_next);
          t <= t_round > T_WIDTH'(GMAX) ? GMAX : 31'(t_round);
          state <= G11;
        end
        // p = R(65536 + t) and LN[G1 >> 4].
        G11: begin rs <= bits(one_t); recip_addr <= recip_index(one_t, bits(one_t)); ln_addr <= 13'(g1 >> 4); state <= G12; end
        G12: state <= G13;
        G13: begin p <= recip_value; state <= G14; end
        G14: begin a <= 21'(LN05 + 21'(a_round)); state <= G15; end
        G15: begin expn_addr <= a >= 0 ? 12'd0 : (-a) >>> 6 > 21'sd4095 ? 12'd4095 : 12'((-a) >>> 6); state <= G16; end
        G16: state <= G17;
        G17: begin g <= expn_q; state <= G18; end
        // Output and the state of the bin.
        G18: if (!m_valid || m_ready) begin
          m_valid <= 1; m_last <= last;
          m_re <= 24'(out_round_re); m_im <= 24'(out_round_im);
          prev[k] <= prev_round > PREV_WIDTH'(GMAX) ? GMAX : 31'(prev_round);
          k <= k + 1'b1;
          // frame_out only counts the stored frames (then the input is live).
          if (k == LOG2N'(N-1) && frame_out < stored) frame_out <= frame_out + 1'b1;
          if (last) begin
            // The transaction is complete: restart for the next one.
            state <= COLLECT; k <= '0; frames_in <= '0; frame_out <= '0; stored <= '0; stored_last <= 0;
            for (int b = 0; b < N; b++) begin sum[b] <= '0; prev[b] <= 31'd65536; end
          end else state <= PICK;
        end
        default: state <= COLLECT;
      endcase
    end
  end
endmodule
