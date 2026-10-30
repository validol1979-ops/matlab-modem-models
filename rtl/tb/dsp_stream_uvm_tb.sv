// Port adapters for genuine RTL modules; the shared UVM sees their packed pin tuples.
`timescale 1ns/1ps
`ifndef DSP_KIND
`define DSP_KIND 1
`endif
`ifndef DSP_LOG2N
`define DSP_LOG2N 5
`endif
`ifndef DSP_CP
`define DSP_CP 8
`endif
`ifndef DSP_LOG2HOP
`define DSP_LOG2HOP 3
`endif
`ifndef DSP_LOG2LANES
`define DSP_LOG2LANES 2
`endif
`ifndef DSP_LOG2TMAX
`define DSP_LOG2TMAX 7
`endif
`ifndef DSP_LOG2M
`define DSP_LOG2M 2
`endif
`ifndef DSP_LOG2NMAX
`define DSP_LOG2NMAX 5
`endif
`ifndef DSP_LOG2MMAX
`define DSP_LOG2MMAX 6
`endif
`ifndef DSP_LOG2KMAX
`define DSP_LOG2KMAX 6
`endif
`ifndef DSP_LOG2EMAX
`define DSP_LOG2EMAX 9
`endif
`include "dsp_stream_uvm.svh"
module dsp_uvm_top;
 import uvm_pkg::*;import dsp_uvm_pkg::*;
 parameter LMS_RECIP_FILE="rtl/common/mem/lms_reciprocal.mem";
 parameter PHI_FILE="rtl/common/mem/ldpc_phi.mem";
 parameter INV_FILE="rtl/common/mem/ldpc_inv.mem";
 parameter MEM_DIR="rtl/common/mem";
 parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
 parameter TWIDDLE_FILE="rtl/common/mem/fft_twiddle_32.mem";
 parameter WINDOW_FILE="rtl/common/mem/stft_window_32.mem";
 parameter RECIP_FILE="rtl/common/mem/stft_recip_32_8.mem";
 logic clk=0;always #5 clk=!clk;
 dsp_uvm_if bus(clk);
 wire [23:0] port_re,port_im;
 wire [31:0] port_aux;
 wire [35:0] port_errors;
 if(`DSP_KIND!=20&&`DSP_KIND!=21) begin assign bus.w_valid=0;assign bus.w_last=0;assign bus.w_data=0;end
 localparam int LB=`DSP_LOG2M>0?`DSP_LOG2M:1;
 if(`DSP_KIND==20||`DSP_KIND==21) begin
  assign port_re[23:18]=0;assign port_im[23:18]=0;
  assign bus.m_data={440'd0,port_errors,port_im[17:0],port_re[17:0]};
 end else if(`DSP_KIND==18) begin
  assign port_re[23:16]=0;assign port_im=0;assign port_aux[31:1]=0;
  assign bus.m_data={495'd0,port_re[15:0],port_aux[0]};
 end else if(`DSP_KIND==19) begin
  assign port_re[23:1]=0;assign port_im=0;
  assign bus.m_data={511'd0,port_re[0]};
 end else if(`DSP_KIND==10) begin
  assign port_re[23:LB]=0;assign port_im=0;
  assign bus.m_data={{(512-LB){1'b0}},port_re[LB-1:0]};
 end else if(`DSP_KIND==13||`DSP_KIND==14) begin
  assign port_re[23:18]=0;assign port_im[23:18]=0;
  assign bus.m_data={444'd0,port_aux,port_im[17:0],port_re[17:0]};
 end else if(`DSP_KIND!=4&&`DSP_KIND!=6) begin
  assign port_re[23:18]=0;assign port_im[23:18]=0;
  assign bus.m_data={476'd0,port_im[17:0],port_re[17:0]};
 end else assign bus.m_data={464'd0,port_im,port_re};
 if(`DSP_KIND>=2&&`DSP_KIND<=5) begin
  assign bus.cfg_ready=0;assign bus.configured=bus.rst!=bus.ACTIVE;
 end
 generate
  if(`DSP_KIND==1) begin:g_fir
   fir_runtime #(.LOG2LANES(`DSP_LOG2LANES),.LOG2TMAX(`DSP_LOG2TMAX),.RESET_ACTIVE(bus.ACTIVE)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_last(bus.cfg_last),.cfg_re(bus.cfg_data[17:0]),.cfg_im(bus.cfg_data[35:18]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_ready(bus.m_ready));
  end else if(`DSP_KIND==2) begin:g_ofdm_tx
   ofdm_tx #(.LOG2N(`DSP_LOG2N),.CP(`DSP_CP),.RESET_ACTIVE(bus.ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) dut(
    .clk(clk),.rst(bus.rst),.s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_ready(bus.m_ready),.error(bus.error));
  end else if(`DSP_KIND==3) begin:g_ofdm_rx
   ofdm_rx #(.LOG2N(`DSP_LOG2N),.CP(`DSP_CP),.RESET_ACTIVE(bus.ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) dut(
    .clk(clk),.rst(bus.rst),.s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_ready(bus.m_ready),.error(bus.error));
  end else if(`DSP_KIND==4) begin:g_stft_analysis
   stft_analysis #(.LOG2N(`DSP_LOG2N),.LOG2HOP(`DSP_LOG2HOP),.RESET_ACTIVE(bus.ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE),.WINDOW_FILE(WINDOW_FILE)) dut(
    .clk(clk),.rst(bus.rst),.s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re),.m_im(port_im),.m_ready(bus.m_ready),.error(bus.error));
  end else if(`DSP_KIND==5) begin:g_stft_synthesis
   stft_synthesis #(.LOG2N(`DSP_LOG2N),.LOG2HOP(`DSP_LOG2HOP),.RESET_ACTIVE(bus.ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE),.WINDOW_FILE(WINDOW_FILE),.RECIP_FILE(RECIP_FILE)) dut(
    .clk(clk),.rst(bus.rst),.s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[23:0]),.s_im(bus.s_data[47:24]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_ready(bus.m_ready),.error(bus.error));

  end else if(`DSP_KIND==6) begin:g_pfb
   pfb_analysis #(.LOG2M(`DSP_LOG2M),.LOG2LANES(`DSP_LOG2LANES),.LOG2TMAX(`DSP_LOG2TMAX),.RESET_ACTIVE(bus.ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_last(bus.cfg_last),.cfg_tap(bus.cfg_data[17:0]),.cfg_decimation(bus.cfg_data[18+:`DSP_LOG2M+1]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re),.m_im(port_im),.m_ready(bus.m_ready));
  end else if(`DSP_KIND==7) begin:g_notch
   assign bus.error=0;
   notch_iir #(.RESET_ACTIVE(bus.ACTIVE)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_b1(bus.cfg_data[17:0]),.cfg_a1(bus.cfg_data[35:18]),.cfg_a2(bus.cfg_data[53:36]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_ready(bus.m_ready));
  end else if(`DSP_KIND==8) begin:g_kalman
   kalman_scalar #(.RESET_ACTIVE(bus.ACTIVE)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_q(bus.cfg_data[31:0]),.cfg_r(bus.cfg_data[63:32]),.cfg_p0(bus.cfg_data[95:64]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_ready(bus.m_ready));
  end else if(`DSP_KIND==9) begin:g_fsk_tx
   fsk_tx #(.LOG2M(`DSP_LOG2M),.LOG2NMAX(`DSP_LOG2NMAX),.RESET_ACTIVE(bus.ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_last(bus.cfg_last),.cfg_step(bus.cfg_data[31:0]),.cfg_n(bus.cfg_data[32+:`DSP_LOG2NMAX+1]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_label(bus.s_data[LB-1:0]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_ready(bus.m_ready));
  end else if(`DSP_KIND==10) begin:g_fsk_rx
   fsk_rx #(.LOG2M(`DSP_LOG2M),.LOG2NMAX(`DSP_LOG2NMAX),.RESET_ACTIVE(bus.ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_last(bus.cfg_last),.cfg_step(bus.cfg_data[31:0]),.cfg_n(bus.cfg_data[32+:`DSP_LOG2NMAX+1]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_label(port_re[LB-1:0]),.m_ready(bus.m_ready));

  end else if(`DSP_KIND==11) begin:g_beamform
   beamform #(.LOG2M(`DSP_LOG2M),.RESET_ACTIVE(bus.ACTIVE)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_last(bus.cfg_last),.cfg_re(bus.cfg_data[17:0]),.cfg_im(bus.cfg_data[35:18]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_ready(bus.m_ready));

  end else if(`DSP_KIND==12) begin:g_alamouti_rx
   alamouti_rx #(.RESET_ACTIVE(bus.ACTIVE)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_last(bus.cfg_last),.cfg_re(bus.cfg_data[17:0]),.cfg_im(bus.cfg_data[35:18]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_ready(bus.m_ready));

  end else if(`DSP_KIND==15) begin:g_mmse2
   mmse2 #(.RESET_ACTIVE(bus.ACTIVE)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_last(bus.cfg_last),.cfg_re(bus.cfg_data[17:0]),.cfg_im(bus.cfg_data[35:18]), .cfg_lambda(bus.cfg_data[69:36]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_ready(bus.m_ready));

  end else if(`DSP_KIND==16) begin:g_mmse3
   mmse3 #(.RESET_ACTIVE(bus.ACTIVE)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_last(bus.cfg_last),.cfg_re(bus.cfg_data[17:0]),.cfg_im(bus.cfg_data[35:18]), .cfg_lambda(bus.cfg_data[69:36]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_ready(bus.m_ready));

  end else if(`DSP_KIND==13) begin:g_costas_loop
   assign bus.error=0;
   costas_loop #(.RESET_ACTIVE(bus.ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_k1(bus.cfg_data[31:0]),.cfg_k2(bus.cfg_data[63:32]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_phase(port_aux),.m_ready(bus.m_ready));

  end else if(`DSP_KIND==14) begin:g_gardner_timing

   gardner_timing #(.RESET_ACTIVE(bus.ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_sps(bus.cfg_data[7:0]),.cfg_count(bus.cfg_data[23:8]),.cfg_position(bus.cfg_data[71:24]),.cfg_k3(bus.cfg_data[103:72]),.cfg_k4(bus.cfg_data[135:104]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_position(port_aux),.m_ready(bus.m_ready));

  end else if(`DSP_KIND==17) begin:g_omlsa
   omlsa #(.LOG2N(`DSP_LOG2N),.LOG2HOP(`DSP_LOG2HOP),.RESET_ACTIVE(bus.ACTIVE),.MEM_DIR(MEM_DIR)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_nnoise(bus.cfg_data[4:0]),.cfg_alpha(bus.cfg_data[21:5]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(port_re[17:0]),.m_im(port_im[17:0]),.m_ready(bus.m_ready));

  end else if(`DSP_KIND==18) begin:g_ldpc
   localparam int MEND=1+`DSP_LOG2MMAX+1;
   localparam int NEND=MEND+`DSP_LOG2NMAX+1;
   ldpc_decoder #(.LOG2NMAX(`DSP_LOG2NMAX),.LOG2MMAX(`DSP_LOG2MMAX),.LOG2EMAX(`DSP_LOG2EMAX),.RESET_ACTIVE(bus.ACTIVE),.PHI_FILE(PHI_FILE),.INV_FILE(INV_FILE)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_last(bus.cfg_last),.cfg_bit(bus.cfg_data[0]),
    .cfg_m(bus.cfg_data[1+:`DSP_LOG2MMAX+1]),.cfg_n(bus.cfg_data[MEND+:`DSP_LOG2NMAX+1]),
    .cfg_iterations(bus.cfg_data[NEND+:8]),.cfg_mode(bus.cfg_data[NEND+8+:2]),.cfg_alpha(bus.cfg_data[NEND+10+:9]),.cfg_beta(bus.cfg_data[NEND+19+:16]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_llr(bus.s_data[15:0]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_bit(port_aux[0]),.m_posterior(port_re[15:0]),.m_ready(bus.m_ready));
  end else if(`DSP_KIND==19) begin:g_gf2
   gf2_encoder #(.LOG2KMAX(`DSP_LOG2KMAX),.LOG2MMAX(`DSP_LOG2MMAX),.RESET_ACTIVE(bus.ACTIVE)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_last(bus.cfg_last),.cfg_bit(bus.cfg_data[0]),
    .cfg_m(bus.cfg_data[1+:`DSP_LOG2MMAX+1]),.cfg_k(bus.cfg_data[`DSP_LOG2MMAX+2+:`DSP_LOG2KMAX+1]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_bit(bus.s_data[0]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_bit(port_re[0]),.m_ready(bus.m_ready));

  end else if(`DSP_KIND==20) begin:g_lms_filter
   lms_filter #(.LOG2N(`DSP_LOG2N),.RESET_ACTIVE(bus.ACTIVE),.RECIP_FILE(LMS_RECIP_FILE)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_nlms(bus.cfg_data[0]),.cfg_taps(bus.cfg_data[1+:`DSP_LOG2N+1]),
    .cfg_mu(bus.cfg_data[`DSP_LOG2N+2+:18]),.cfg_eps(bus.cfg_data[`DSP_LOG2N+20+:34]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_dre(bus.s_data[53:36]),.s_dim(bus.s_data[71:54]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_pre(port_re[17:0]),.m_pim(port_im[17:0]),.m_ere(port_errors[17:0]),.m_eim(port_errors[35:18]),.m_ready(bus.m_ready),
    .w_valid(bus.w_valid),.w_last(bus.w_last),.w_re(bus.w_data[17:0]),.w_im(bus.w_data[35:18]),.w_ready(bus.w_ready));

  end else if(`DSP_KIND==21) begin:g_rls_filter
   rls_filter #(.LOG2N(`DSP_LOG2N),.RESET_ACTIVE(bus.ACTIVE)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_taps(bus.cfg_data[0+:`DSP_LOG2N+1]),.cfg_p0(bus.cfg_data[`DSP_LOG2N+1+:44]),
    .cfg_lambda(bus.cfg_data[`DSP_LOG2N+45+:30]),.cfg_invl(bus.cfg_data[`DSP_LOG2N+75+:32]),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_data[17:0]),.s_im(bus.s_data[35:18]),.s_dre(bus.s_data[53:36]),.s_dim(bus.s_data[71:54]),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_pre(port_re[17:0]),.m_pim(port_im[17:0]),.m_ere(port_errors[17:0]),.m_eim(port_errors[35:18]),.m_ready(bus.m_ready),
    .w_valid(bus.w_valid),.w_last(bus.w_last),.w_re(bus.w_data[17:0]),.w_im(bus.w_data[35:18]),.w_ready(bus.w_ready));
  end
 endgenerate
 initial begin uvm_config_db#(virtual dsp_uvm_if)::set(null,"*","vif",bus);run_test("dsp_test");end
 initial if($test$plusargs("INJECT_S_VALID_X")||$test$plusargs("INJECT_S_READY_X")||$test$plusargs("INJECT_INPUT_X")) begin
  wait(bus.rst!=bus.ACTIVE);wait(bus.s_valid);#1;
  if($test$plusargs("INJECT_S_VALID_X")) force bus.s_valid=1'bx;
  else if($test$plusargs("INJECT_S_READY_X")) force bus.s_ready=1'bx;else force bus.s_data='x;
 end
 logic [511:0] corrupt_cfg;
 initial if($test$plusargs("INJECT_CFG_VALID_X")||$test$plusargs("INJECT_CFG_READY_X")||$test$plusargs("INJECT_CFG_DATA")) begin
  if(`DSP_KIND>=2&&`DSP_KIND<=5) `uvm_fatal("INPUT","Configuration injection has no physical port")
  wait(bus.rst!=bus.ACTIVE);wait(bus.cfg_valid);#1;
  if($test$plusargs("INJECT_CFG_VALID_X")) force bus.cfg_valid=1'bx;
  else if($test$plusargs("INJECT_CFG_READY_X")) force bus.cfg_ready=1'bx;
  else begin corrupt_cfg=bus.cfg_data^512'd1;force bus.cfg_data=corrupt_cfg;end
 end
 logic corrupt_last;
 initial if($test$plusargs("INJECT_M_VALID_X")||$test$plusargs("INJECT_M_READY_X")||$test$plusargs("INJECT_OUTPUT_X")||$test$plusargs("INJECT_LAST")) begin
  wait(bus.rst!=bus.ACTIVE);wait(bus.m_valid);@(negedge clk);
  if($test$plusargs("INJECT_M_VALID_X")) force bus.m_valid=1'bx;
  else if($test$plusargs("INJECT_M_READY_X")) force bus.m_ready=1'bx;
  else if($test$plusargs("INJECT_OUTPUT_X")) force port_re='x;else begin corrupt_last=!bus.m_last;force bus.m_last=corrupt_last;end
 end
 logic [31:0] corrupt_aux;
 initial if($test$plusargs("INJECT_SIDEBAND")) begin
  if(`DSP_KIND!=13&&`DSP_KIND!=14&&`DSP_KIND!=18) `uvm_fatal("INPUT","Sideband injection has no physical port")
  wait(bus.rst!=bus.ACTIVE);wait(bus.m_valid);@(negedge clk);corrupt_aux=port_aux^32'd1;force port_aux=corrupt_aux;
 end
 logic [23:0] corrupt_value;
 initial if($test$plusargs("INJECT_HELD_DATA")) begin
  wait(bus.rst!=bus.ACTIVE);@(bus.sample);
  while(!(bus.sample.m_valid&&!bus.sample.m_ready)) @(bus.sample);
  @(negedge clk);force bus.m_ready=1'b0;corrupt_value=port_re^24'd1;force port_re=corrupt_value;
 end
 initial if($test$plusargs("INJECT_ERROR_X")) begin wait(bus.rst!=bus.ACTIVE);wait(bus.s_valid);@(negedge clk);force bus.error=1'bx;end

 logic [511:0] corrupt_source;
 initial if($test$plusargs("INJECT_DESIRED")) begin
  wait(bus.rst!=bus.ACTIVE);wait(bus.s_valid);#1;corrupt_source=bus.s_data^(512'd1<<36);force bus.s_data=corrupt_source;
 end
 logic [35:0] corrupt_errors;
 initial if($test$plusargs("INJECT_ERROR_DATA")) begin
  wait(bus.rst!=bus.ACTIVE);wait(bus.m_valid);@(negedge clk);corrupt_errors=port_errors^36'd1;force port_errors=corrupt_errors;
 end
 logic corrupt_weight_last;
 initial if($test$plusargs("INJECT_W_VALID_X")||$test$plusargs("INJECT_W_READY_X")||$test$plusargs("INJECT_W_DATA_X")||$test$plusargs("INJECT_W_LAST")) begin
  wait(bus.rst!=bus.ACTIVE);wait(bus.w_valid);@(negedge clk);
  if($test$plusargs("INJECT_W_VALID_X")) force bus.w_valid=1'bx;
  else if($test$plusargs("INJECT_W_READY_X")) force bus.w_ready=1'bx;
  else if($test$plusargs("INJECT_W_DATA_X")) force bus.w_data='x;
  else begin corrupt_weight_last=!bus.w_last;force bus.w_last=corrupt_weight_last;end
 end
 logic [35:0] corrupt_weight;
 initial if($test$plusargs("INJECT_W_HELD")) begin
  wait(bus.rst!=bus.ACTIVE);@(bus.sample);
  while(!(bus.sample.w_valid&&!bus.sample.w_ready)) @(bus.sample);
  @(negedge clk);force bus.w_ready=1'b0;corrupt_weight=bus.w_data^36'd1;force bus.w_data=corrupt_weight;
 end
 initial begin #100000000;`uvm_fatal("TIMEOUT","DSP UVM did not drain") end
endmodule
