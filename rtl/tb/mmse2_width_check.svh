// +CHECK_MMSE2_WIDTHS: independent 128-bit recomputation of every sized mmse2 intermediate
// (docs/RTL_MMSE2_WIDTHS.md). The reference is built only from the configuration words and
// observations accepted at the DUT ports; the DUT's Gram, det, R/shift, M, M*R products,
// scaled weights, stored weights and raw output sums are compared on every real trajectory.
// Each reference value must also stay inside the proved widths 38/74/55/78/68 (and |left shift|
// below 2^57), so a violated bound fails even with a wider layout.
// +INJECT_MMSE2=<TAG> perturbs the first observation of that class (negative control).
typedef logic signed [127:0] mw_t;
bit mw_enable;
string mw_inject;
mw_t mw_h [0:7];                                // h00 re, im, h01 re, im, h10 ..., h11 ...
mw_t mw_lambda;
int mw_count, mw_prev_state;
bit mw_ready, mw_valid_det, mw_overflow, mw_second;
mw_t mw_gram [0:3], mw_det, mw_m [0:7], mw_prod [0:7], mw_full [0:7], mw_r;
int mw_z;
mw_t mw_o0r, mw_o0i;
mw_t mw_q0 [$], mw_q1 [$], mw_q2 [$], mw_q3 [$];
int mw_gram_checks, mw_det_checks, mw_recip_checks, mw_m_checks, mw_prod_checks, mw_scale_checks,
    mw_weight_checks, mw_sum_checks;
mw_t mw_det_peak, mw_m_peak, mw_prod_peak, mw_scale_peak, mw_sum_peak;
longint mw_clock, mw_cfg_clock, mw_recip_cycles, mw_config_cycles;
bit mw_injected [string];
initial begin
  mw_enable = $test$plusargs("CHECK_MMSE2_WIDTHS");
  if (!$value$plusargs("INJECT_MMSE2=%s", mw_inject)) mw_inject = "";
  mw_gram_checks = 0; mw_det_checks = 0; mw_recip_checks = 0; mw_m_checks = 0; mw_prod_checks = 0;
  mw_scale_checks = 0; mw_weight_checks = 0; mw_sum_checks = 0;
  mw_det_peak = 0; mw_m_peak = 0; mw_prod_peak = 0; mw_scale_peak = 0; mw_sum_peak = 0;
  mw_recip_cycles = -1; mw_config_cycles = -1; mw_clock = 0;
end

function automatic mw_t mw_abs(input mw_t v); return v < 0 ? -v : v; endfunction
function automatic bit mw_fits(input mw_t v, input int width);
  return v >= -(mw_t'(1) <<< (width - 1)) && v < (mw_t'(1) <<< (width - 1));
endfunction
// Observed DUT value, +1 on the first observation of the injected class.
function automatic mw_t mw_seen(input string tag, input mw_t v);
  if (mw_inject == tag && !mw_injected.exists(tag)) begin mw_injected[tag] = 1; return v + 1; end
  return v;
endfunction
function automatic void mw_compare(input string tag, input string what, input mw_t seen, input mw_t expected, input int width);
  mw_t observed;
  if (!mw_fits(expected, width)) $fatal(1, "[%s] mmse2 %s reference %0d exceeds proved signed%0d", tag, what, expected, width);
  observed = mw_seen(tag, seen);
  if (observed !== expected) $fatal(1, "[%s] mmse2 %s: DUT %0d, reference %0d", tag, what, observed, expected);
endfunction

// Reference configuration from the captured H and LAMBDA (beam_energy.exact_reciprocal, mmse_fixed).
function automatic void mw_configure();
  mw_t a0, a1, b0, b1, c0, c1, d0, d1, amount, limit;
  mw_t pr [0:3], pi [0:3], qr [0:3], qi [0:3], ur [0:3], ui [0:3], vr [0:3], vi [0:3];
  int bits;
  mw_t num, rem;
  {a0, a1, b0, b1, c0, c1, d0, d1} = {mw_h[0], mw_h[1], mw_h[2], mw_h[3], mw_h[4], mw_h[5], mw_h[6], mw_h[7]};
  mw_gram[0] = a0*a0 + a1*a1 + c0*c0 + c1*c1 + mw_lambda;
  mw_gram[1] = b0*b0 + b1*b1 + d0*d0 + d1*d1 + mw_lambda;
  mw_gram[2] = a0*b0 + a1*b1 + c0*d0 + c1*d1;
  mw_gram[3] = a0*b1 - a1*b0 + c0*d1 - c1*d0;
  mw_det = mw_gram[0]*mw_gram[1] - mw_gram[2]*mw_gram[2] - mw_gram[3]*mw_gram[3];
  mw_valid_det = mw_det > 0; mw_overflow = 0;
  if (!mw_valid_det) return;
  // adj(G) = [[d, -b], [-conj b, a]] times H^H.
  for (int k = 0; k < 4; k++) begin
    if (k < 2) begin pr[k] = mw_gram[1]; pi[k] = 0; qr[k] = -mw_gram[2]; qi[k] = -mw_gram[3]; end
    else begin pr[k] = -mw_gram[2]; pi[k] = mw_gram[3]; qr[k] = mw_gram[0]; qi[k] = 0; end
    ur[k] = (k % 2) ? c0 : a0; ui[k] = (k % 2) ? c1 : a1; vr[k] = (k % 2) ? d0 : b0; vi[k] = (k % 2) ? d1 : b1;
    mw_m[2*k] = pr[k]*ur[k] + pi[k]*ui[k] + qr[k]*vr[k] + qi[k]*vi[k];
    mw_m[2*k+1] = pi[k]*ur[k] - pr[k]*ui[k] + qi[k]*vr[k] - qr[k]*vi[k];
  end
  bits = 0;
  for (int b = 0; b < 127; b++) if (mw_det[b]) bits = b + 1;
  mw_z = 22 + bits; num = mw_t'(1) <<< mw_z;
  mw_r = num / mw_det; rem = num % mw_det;
  if (2*rem > mw_det || (2*rem == mw_det && mw_r[0])) mw_r = mw_r + 1;
  amount = mw_z - 39; limit = mw_t'(1) <<< 47;
  for (int k = 0; k < 8; k++) begin
    mw_prod[k] = mw_m[k]*mw_r;
    if (amount > 0) mw_full[k] = (mw_prod[k] + (mw_t'(1) <<< (amount - 1))) >>> amount;
    else if (amount == 0) mw_full[k] = mw_prod[k];
    else mw_full[k] = mw_prod[k] <<< (-amount);
    if (mw_full[k] < -limit || mw_full[k] >= limit) mw_overflow = 1;
  end
endfunction

always @(posedge clk) if (mw_enable) begin
  mw_clock++;
  if (rst == RESET_ACTIVE) begin
    mw_count = 0; mw_ready = 0; mw_second = 0; mw_prev_state = 0;
    mw_q0.delete(); mw_q1.delete(); mw_q2.delete(); mw_q3.delete();
  end else begin
    int state;
    state = int'(dut.cstate);
    if (mw_ready && state == 2) begin              // Gram registers written at the C_GRAM edge
      mw_compare("GRAM", "a", mw_t'(dut.ga), mw_gram[0], 38);
      mw_compare("GRAM", "d", mw_t'(dut.gd), mw_gram[1], 38);
      mw_compare("GRAM", "b.re", mw_t'(dut.gbr), mw_gram[2], 38);
      mw_compare("GRAM", "b.im", mw_t'(dut.gbi), mw_gram[3], 38);
      mw_gram_checks += 4;
    end
    if (mw_ready && state == 3 && dut.norm_start) begin
      mw_compare("DET", "det", mw_t'(dut.det), mw_det, 74);
      mw_det_checks++; if (mw_abs(mw_det) > mw_det_peak) mw_det_peak = mw_abs(mw_det);
    end
    if (mw_ready && dut.norm_done) begin
      if (!mw_valid_det) $fatal(1, "[RECIPROCAL] mmse2 reciprocal of a nonpositive determinant");
      if (mw_seen("RECIPROCAL", mw_t'(dut.r)) !== mw_r || int'(dut.shift) != mw_z - 15
          || mw_r < (mw_t'(1) <<< 22) || mw_r > (mw_t'(1) <<< 23))
        $fatal(1, "[RECIPROCAL] mmse2 R/shift %0d/%0d, reference %0d/%0d", dut.r, dut.shift, mw_r, mw_z - 15);
      mw_recip_checks++; mw_recip_cycles = mw_clock - mw_cfg_clock;
    end
    if (mw_ready && state == 5) begin              // M registers and the scaled products
      for (int k = 0; k < 4; k++) begin
        mw_compare("M", "M.re", mw_t'(dut.mr[k]), mw_m[2*k], 55);
        mw_compare("M", "M.im", mw_t'(dut.mi[k]), mw_m[2*k+1], 55);
        mw_compare("SCALE", "M*R re", mw_t'(dut.wprod_re[k]), mw_prod[2*k], 78);
        mw_compare("SCALE", "M*R im", mw_t'(dut.wprod_im[k]), mw_prod[2*k+1], 78);
        mw_compare("SCALE", "scaled re", mw_t'(dut.wfull_re[k]), mw_full[2*k], 78);
        mw_compare("SCALE", "scaled im", mw_t'(dut.wfull_im[k]), mw_full[2*k+1], 78);
      end
      for (int k = 0; k < 8; k++) begin
        if (mw_abs(mw_m[k]) > mw_m_peak) mw_m_peak = mw_abs(mw_m[k]);
        if (mw_abs(mw_prod[k]) > mw_prod_peak) mw_prod_peak = mw_abs(mw_prod[k]);
        if (mw_abs(mw_full[k]) > mw_scale_peak) mw_scale_peak = mw_abs(mw_full[k]);
      end
      mw_m_checks += 8; mw_prod_checks += 8; mw_scale_checks += 8;
    end
    if (mw_ready && mw_prev_state == 5) begin       // outcome of the C_WEIGHT edge
      if (mw_overflow) begin
        if (dut.error !== 1'b1 || configured !== 1'b0) $fatal(1, "[WEIGHT] mmse2 accepted an overflowing coefficient");
      end else begin
        if (configured !== 1'b1 || dut.error !== 1'b0) $fatal(1, "[WEIGHT] mmse2 rejected representable coefficients");
        for (int k = 0; k < 4; k++) begin
          mw_compare("WEIGHT", "W.re", mw_t'(dut.wr[k]), mw_full[2*k], 48);
          mw_compare("WEIGHT", "W.im", mw_t'(dut.wi[k]), mw_full[2*k+1], 48);
        end
        mw_weight_checks += 8; mw_config_cycles = mw_clock - mw_cfg_clock;
      end
    end
    mw_prev_state = state;
    if (dut.p_valid) begin                         // raw sums written at the previous o1 edge
      if (mw_q0.size() == 0) $fatal(1, "[SUM] mmse2 output sums without a reference pair");
      mw_compare("SUM", "y0.re", mw_t'(dut.y0r), mw_q0.pop_front(), 68);
      mw_compare("SUM", "y0.im", mw_t'(dut.y0i), mw_q1.pop_front(), 68);
      mw_compare("SUM", "y1.re", mw_t'(dut.y1r), mw_q2.pop_front(), 68);
      mw_compare("SUM", "y1.im", mw_t'(dut.y1i), mw_q3.pop_front(), 68);
      mw_sum_checks += 4;
    end
    if (cfg_valid && cfg_ready) begin
      mw_ready = 0;
      if (mw_count < 4) begin mw_h[2*mw_count] = mw_t'(cfg_re); mw_h[2*mw_count+1] = mw_t'(cfg_im); end
      mw_count++;
      if (cfg_last) begin
        if (mw_count == 4) begin
          mw_lambda = mw_t'({1'b0, cfg_lambda}); mw_configure(); mw_ready = 1; mw_cfg_clock = mw_clock;
        end
        mw_count = 0;
      end
    end
    if (s_valid && s_ready) begin
      if (!mw_second) begin mw_o0r = mw_t'(s_re); mw_o0i = mw_t'(s_im); end
      else begin
        mw_t w [0:7], o1r, o1i, y [0:3];
        if (!mw_ready || mw_overflow || !mw_valid_det) $fatal(1, "[SUM] mmse2 accepted a pair without valid weights");
        for (int k = 0; k < 8; k++) w[k] = mw_full[k];
        o1r = mw_t'(s_re); o1i = mw_t'(s_im);
        for (int i = 0; i < 2; i++) begin
          y[2*i] = w[4*i]*mw_o0r - w[4*i+1]*mw_o0i + w[4*i+2]*o1r - w[4*i+3]*o1i;
          y[2*i+1] = w[4*i]*mw_o0i + w[4*i+1]*mw_o0r + w[4*i+2]*o1i + w[4*i+3]*o1r;
        end
        for (int i = 0; i < 4; i++) if (mw_abs(y[i]) > mw_sum_peak) mw_sum_peak = mw_abs(y[i]);
        mw_q0.push_back(y[0]); mw_q1.push_back(y[1]); mw_q2.push_back(y[2]); mw_q3.push_back(y[3]);
      end
      mw_second = !mw_second;
    end
  end
end

task automatic check_mmse2_widths();
  if (!mw_enable) return;
  if (mw_gram_checks < 4 || mw_det_checks < 1) $fatal(1, "[GRAM] mmse2 width monitor not exercised");
  $display("PASS MMSE2 WIDTHS: %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",
           mw_gram_checks, mw_det_checks, mw_recip_checks, mw_m_checks, mw_prod_checks, mw_scale_checks,
           mw_weight_checks, mw_sum_checks, mw_det_peak, mw_m_peak, mw_prod_peak, mw_scale_peak, mw_sum_peak,
           mw_recip_cycles, mw_config_cycles);
endtask
