// Physical IO harness for standalone block timing. Not a modem or board pinout.
module rtl_synth_top #(
  parameter int DUT_KIND=0
)(
  input logic clk,rst,load,enable,m_ready,
  input logic [17:0] seed,
  output logic [35:0] data,
  output logic [1:0] overflow,
  output logic valid,ready,last
);
  (* IOB="TRUE", KEEP="TRUE", DONT_TOUCH="TRUE", preserve=1, dont_merge=1 *) logic [35:0] data_reg;
  (* IOB="TRUE", KEEP="TRUE", DONT_TOUCH="TRUE", preserve=1, dont_merge=1 *) logic [1:0] overflow_reg;
  (* IOB="TRUE", KEEP="TRUE", DONT_TOUCH="TRUE", preserve=1, dont_merge=1 *) logic valid_reg,ready_reg,last_reg;
  assign data=data_reg;assign overflow=overflow_reg;
  assign valid=valid_reg;assign ready=ready_reg;assign last=last_reg;
  logic [17:0] state;
  // Ready is an input pin whose fanout spreads over the whole DUT; leaving it
  // unregistered made the pad route alone the worst setup path of the largest
  // blocks (10.5 ns of route to a single slice). Register it at the harness edge.
  logic m_ready_q;
  always_ff @(posedge clk) m_ready_q<=m_ready; // no reset term: rst is a pin too
  // The seed pins reach the output mix through a register: a direct pin-to-output-register
  // path with hold-compensating input delay was the worst setup path of large blocks.
  logic [17:0] seed_q;
  logic [35:0] core_data;
  logic [1:0] core_overflow;
  logic core_valid,core_ready,core_last;
  always_ff @(posedge clk) begin
    // Mix observable harness signals so small DUTs keep every physical port
    // dynamic; avoid constant pads and BRAM-output/IOB packing conflicts.
    seed_q<=seed;
    data_reg<=core_data^{state,seed_q^state};overflow_reg<=core_overflow^{load^state[1],enable^state[2]};
    valid_reg<=core_valid^m_ready_q;ready_reg<=core_ready^state[0];last_reg<=core_last^rst^state[3];
  end
  always_ff @(posedge clk) begin
    if(rst) state<=18'd1;
    else if(core_ready) begin
      if(load) state<=seed;
      else state<={state[16:0],state[17]^state[10]^state[7]^state[0]};
    end
  end
  generate
    if(DUT_KIND<3) begin : g_arithmetic
  wire signed [17:0] ar=$signed(state),ai=$signed({state[8:0],state[17:9]});
  wire signed [17:0] br=$signed(state^18'h15555),bi=$signed({state[0],state[17:1]});
    if(DUT_KIND==0) begin : g_mul
      fxp_complex_mul dut(.clk(clk),.rst(rst),.s_valid(enable),.s_ready(core_ready),.s_last(state[0]),
        .s_ar(ar),.s_ai(ai),.s_br(br),.s_bi(bi),.m_valid(core_valid),.m_ready(m_ready_q),.m_last(core_last),
        .m_re(core_data[17:0]),.m_im(core_data[35:18]),.m_overflow(core_overflow));
    end else if(DUT_KIND==1) begin : g_add
      fxp_complex_add dut(.clk(clk),.rst(rst),.s_valid(enable),.s_ready(core_ready),.s_last(state[0]),
        .s_ar(ar),.s_ai(ai),.s_br(br),.s_bi(bi),.m_valid(core_valid),.m_ready(m_ready_q),.m_last(core_last),
        .m_re(core_data[17:0]),.m_im(core_data[35:18]),.m_overflow(core_overflow));
    end else begin : g_resize
      wire signed [36:0] re_in=$signed({ar,br,ai[0]}),im_in=$signed({ai,bi,ar[0]});
      fxp_stream_resize dut(.clk(clk),.rst(rst),.s_valid(enable),.s_ready(core_ready),.s_last(state[0]),
        .s_re(re_in),.s_im(im_in),.m_valid(core_valid),.m_ready(m_ready_q),.m_last(core_last),
        .m_re(core_data[17:0]),.m_im(core_data[35:18]),.m_overflow(core_overflow));
    end
    end else if(DUT_KIND==3) begin : g_ram
      sync_ram dut(.clk(clk),.wr_en(load),.rd_en(enable),.wr_addr(state[9:0]),.rd_addr(seed[9:0]),
        .wr_data(state),.rd_data(core_data[17:0]));
      assign core_last=0;assign core_data[35:18]='0;assign core_overflow='0;assign core_ready=1;
      always_ff @(posedge clk) if(rst) core_valid<=0;else core_valid<=enable;
    end else if(DUT_KIND==4) begin : g_rom
      sync_rom dut(.clk(clk),.rd_en(enable),.rd_addr(state[7:0]),.rd_data(core_data[17:0]));
      assign core_last=0;assign core_data[35:18]='0;assign core_overflow='0;assign core_ready=1;
      always_ff @(posedge clk) if(rst) core_valid<=0;else core_valid<=enable;
    end else if(DUT_KIND==5) begin : g_bit_sync
      bit_sync dut(.clk(clk),.rst(rst),.async_bit(seed[0]),.sync_bit(core_data[0]));
      assign core_last=0;assign core_data[35:1]='0;assign core_overflow='0;assign core_ready=1;assign core_valid=!rst;
    end else if(DUT_KIND==6) begin : g_reset_sync
      reset_sync dut(.clk(clk),.async_rst(rst),.rst(core_data[0]));
      assign core_last=0;assign core_data[35:1]='0;assign core_overflow='0;assign core_ready=1;assign core_valid=!rst;
    end
    else if(DUT_KIND==32||DUT_KIND==34) begin:g_cpm_tx
      // 32 MSK, 34 GMSK transmitter.
      cpm_tx #(.GMSK(DUT_KIND==34)) dut(.clk(clk),.rst(rst),.s_valid(enable),.s_bit(seed[0]),.s_last(load),.s_ready(core_ready),
       .m_ready(m_ready_q),.m_valid(core_valid),.m_last(core_last),.m_re(core_data[17:0]),.m_im(core_data[35:18]));
      assign core_overflow=0;
    end else if(DUT_KIND==33||DUT_KIND==35) begin:g_cpm_rx
      // 33 MSK, 35 GMSK receiver; configuration, reset and samples are registered as for bpsk_rx.
      wire configured,error,cfg_ready,acq_valid,m_bit;
      wire signed [35:0] value;
      wire signed [31:0] acq_delay,acq_frequency,acq_phase;
      logic cfg_valid_q,cfg_last_q,cfg_bit_q,rst_q,sample_last_q;
      logic signed [17:0] sample_im_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load;cfg_last_q<=seed[1];cfg_bit_q<=seed[3];rst_q<=rst;sample_im_q<=$signed(seed);sample_last_q<=seed[2];end
      cpm_rx #(.GMSK(DUT_KIND==35)) dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_bit(cfg_bit_q),.cfg_last(cfg_last_q),.cfg_count(12'd768),
       .cfg_ready(cfg_ready),.configured(configured),.error(error),.s_valid(enable),.s_last(sample_last_q),.s_re($signed(state)),.s_im(sample_im_q),
       .s_ready(core_ready),.m_valid(core_valid),.m_last(core_last),.m_bit(m_bit),.m_ready(m_ready_q),.m_value(value),
       .acquisition_valid(acq_valid),.acquisition_delay(acq_delay),.acquisition_frequency(acq_frequency),.acquisition_phase(acq_phase));
      assign core_data=value^{4'd0,acq_delay}^{4'd0,acq_frequency}^{4'd0,acq_phase};
      assign core_overflow={configured^error^cfg_ready,acq_valid^m_bit};
    end else if(DUT_KIND==36) begin:g_oqpsk_tx
      oqpsk_tx dut(.clk(clk),.rst(rst),.s_valid(enable),.s_bit(seed[1:0]),.s_last(load),.s_ready(core_ready),
       .m_ready(m_ready_q),.m_valid(core_valid),.m_last(core_last),.m_re(core_data[17:0]),.m_im(core_data[35:18]));
      assign core_overflow=0;
    end else if(DUT_KIND==37) begin:g_oqpsk_rx
      // Configuration, reset and samples are registered as for cpm_rx.
      wire configured,error,cfg_ready,acq_valid;
      wire [1:0] label;
      wire signed [17:0] value_re,value_im;
      wire signed [31:0] acq_delay,acq_frequency,acq_phase;
      logic cfg_valid_q,cfg_last_q,rst_q,sample_last_q;
      logic [1:0] cfg_label_q;
      logic signed [17:0] sample_im_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load;cfg_last_q<=seed[1];cfg_label_q<=seed[4:3];rst_q<=rst;sample_im_q<=$signed(seed);sample_last_q<=seed[2];end
      oqpsk_rx dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_last(cfg_last_q),.cfg_label(cfg_label_q),.cfg_count(12'd768),
       .cfg_ready(cfg_ready),.configured(configured),.error(error),.s_valid(enable),.s_last(sample_last_q),.s_re($signed(state)),.s_im(sample_im_q),
       .s_ready(core_ready),.m_valid(core_valid),.m_last(core_last),.m_label(label),.m_ready(m_ready_q),.m_re(value_re),.m_im(value_im),
       .acquisition_valid(acq_valid),.acquisition_delay(acq_delay),.acquisition_frequency(acq_frequency),.acquisition_phase(acq_phase));
      assign core_data={value_im,value_re}^{4'd0,acq_delay}^{4'd0,acq_frequency}^{4'd0,acq_phase};
      assign core_overflow={configured^error^cfg_ready,acq_valid^label[0]^label[1]};
    end else if(DUT_KIND==38||DUT_KIND==39) begin:g_fft
      // 38: N = 64, 39: N = 1024 streaming FFT/IFFT; the 40 output bits fold into 36.
      localparam int LOG2N=DUT_KIND==38?6:10;
      wire signed [19:0] fft_re,fft_im;
      wire fft_inverse,fft_error;
      logic signed [17:0] sample_im_q;
      always_ff @(posedge clk) sample_im_q<=$signed(seed);
      fft_r2sdf #(.LOG2N(LOG2N),.TWIDDLE_FILE(DUT_KIND==38?"rtl/common/mem/fft_twiddle_64.mem":"rtl/common/mem/fft_twiddle_1024.mem")) dut(
       .clk(clk),.rst(rst),.s_valid(enable),.s_last(load),.s_inverse(seed[0]),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
       .m_valid(core_valid),.m_last(core_last),.m_inverse(fft_inverse),.m_re(fft_re),.m_im(fft_im),.m_ready(m_ready_q),.error(fft_error));
      assign core_data={fft_im[17:0],fft_re[17:0]}^{32'd0,fft_im[19:18],fft_re[19:18]};
      assign core_overflow={fft_error,fft_inverse};
    end else if(DUT_KIND==40||DUT_KIND==41) begin:g_ofdm
      // 40 transmitter, 41 receiver: N = 32, CP = 8 (the ofdm_awgn model).
      wire signed [17:0] ofdm_re,ofdm_im;
      wire ofdm_error;
      logic signed [17:0] sample_im_q;
      always_ff @(posedge clk) sample_im_q<=$signed(seed);
      if(DUT_KIND==40) begin:g_tx
        ofdm_tx #(.LOG2N(5),.CP(8)) dut(.clk(clk),.rst(rst),.s_valid(enable),.s_last(load),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_re(ofdm_re),.m_im(ofdm_im),.m_ready(m_ready_q),.error(ofdm_error));
      end else begin:g_rx
        ofdm_rx #(.LOG2N(5),.CP(8)) dut(.clk(clk),.rst(rst),.s_valid(enable),.s_last(load),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_re(ofdm_re),.m_im(ofdm_im),.m_ready(m_ready_q),.error(ofdm_error));
      end
      assign core_data={ofdm_im,ofdm_re};
      assign core_overflow={ofdm_error,1'b0};
    end else if(DUT_KIND==42||DUT_KIND==43) begin:g_stft
      // 42 analysis, 43 synthesis: N = 64, HOP = 16 (the audio/stft model).
      wire stft_error;
      logic signed [17:0] sample_im_q;
      always_ff @(posedge clk) sample_im_q<=$signed(seed);
      if(DUT_KIND==42) begin:g_analysis
        wire signed [23:0] spectrum_re,spectrum_im;
        stft_analysis #(.LOG2N(6),.LOG2HOP(4)) dut(.clk(clk),.rst(rst),.s_valid(enable),.s_last(load),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_re(spectrum_re),.m_im(spectrum_im),.m_ready(m_ready_q),.error(stft_error));
        assign core_data={spectrum_im[17:0],spectrum_re[17:0]}^{24'd0,spectrum_im[23:18],spectrum_re[23:18]};
      end else begin:g_synthesis
        wire signed [17:0] sample_re,sample_im;
        stft_synthesis #(.LOG2N(6),.LOG2HOP(4)) dut(.clk(clk),.rst(rst),.s_valid(enable),.s_last(load),
         .s_re({{6{state[17]}},state}),.s_im({sample_im_q,6'd0}),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_re(sample_re),.m_im(sample_im),.m_ready(m_ready_q),.error(stft_error));
        assign core_data={sample_im,sample_re};
      end
      assign core_overflow={stft_error,1'b0};
    end else if(DUT_KIND==44) begin:g_pfb
      // Polyphase bank of the pfb_wola model: M = 4, 4 lanes, up to 64 taps.
      wire pfb_error,pfb_cfg_ready,pfb_configured;
      wire signed [23:0] bin_re,bin_im;
      logic cfg_valid_q,cfg_last_q,rst_q;
      logic signed [17:0] sample_im_q,cfg_tap_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load&&seed[0];cfg_last_q<=seed[1];cfg_tap_q<=$signed(state);rst_q<=rst;sample_im_q<=$signed(seed);end
      pfb_analysis #(.LOG2M(2),.LOG2LANES(2),.LOG2TMAX(6)) dut(.clk(clk),.rst(rst_q),
       .cfg_valid(cfg_valid_q),.cfg_last(cfg_last_q),.cfg_tap(cfg_tap_q),.cfg_decimation(seed[4:2]),.cfg_ready(pfb_cfg_ready),.configured(pfb_configured),
       .s_valid(enable),.s_last(load&&!seed[0]),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
       .m_valid(core_valid),.m_last(core_last),.m_re(bin_re),.m_im(bin_im),.m_ready(m_ready_q),.error(pfb_error));
      assign core_data={bin_im[17:0],bin_re[17:0]}^{24'd0,bin_im[23:18],bin_re[23:18]};
      assign core_overflow={pfb_error^pfb_cfg_ready,pfb_configured};
    end else if(DUT_KIND==45) begin:g_fir
      // Runtime FIR of the windowed_sinc model: 8 lanes, up to 64 complex taps.
      wire fir_error,fir_cfg_ready,fir_configured;
      wire signed [17:0] y_re,y_im;
      logic cfg_valid_q,cfg_last_q,rst_q;
      logic signed [17:0] sample_im_q,cfg_re_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load&&seed[0];cfg_last_q<=seed[1];cfg_re_q<=$signed(state);rst_q<=rst;sample_im_q<=$signed(seed);end
      fir_runtime #(.LOG2LANES(3),.LOG2TMAX(6)) dut(.clk(clk),.rst(rst_q),
       .cfg_valid(cfg_valid_q),.cfg_last(cfg_last_q),.cfg_re(cfg_re_q),.cfg_im(sample_im_q),.cfg_ready(fir_cfg_ready),.configured(fir_configured),
       .s_valid(enable),.s_last(load&&!seed[0]),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
       .m_valid(core_valid),.m_last(core_last),.m_re(y_re),.m_im(y_im),.m_ready(m_ready_q),.error(fir_error));
      assign core_data={y_im,y_re};
      assign core_overflow={fir_error^fir_cfg_ready,fir_configured};
    end else if(DUT_KIND==46||DUT_KIND==47) begin:g_oset
      // 46 notch, 47 scalar Kalman (filters/oset); one configuration transfer.
      wire oset_cfg_ready,oset_configured,oset_error;
      wire signed [17:0] y_re,y_im;
      logic cfg_valid_q,rst_q;
      logic signed [17:0] sample_im_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load&&seed[0];rst_q<=rst;sample_im_q<=$signed(seed);end
      if(DUT_KIND==46) begin:g_notch
        notch_iir dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_b1($signed(state)),.cfg_a1(sample_im_q),.cfg_a2($signed(seed_q)),
         .cfg_ready(oset_cfg_ready),.configured(oset_configured),
         .s_valid(enable),.s_last(load&&!seed[0]),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_re(y_re),.m_im(y_im),.m_ready(m_ready_q));
        assign oset_error=1'b0;
      end else begin:g_kalman
        kalman_scalar dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_q({14'd0,state}),.cfg_r({14'd0,seed_q}),.cfg_p0({state[13:0],seed}),
         .cfg_ready(oset_cfg_ready),.configured(oset_configured),
         .s_valid(enable),.s_last(load&&!seed[0]),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_re(y_re),.m_im(y_im),.m_ready(m_ready_q),.error(oset_error));
      end
      assign core_data={y_im,y_re};
      assign core_overflow={oset_error^oset_cfg_ready,oset_configured};
    end else if(DUT_KIND==48||DUT_KIND==49) begin:g_fsk
      // 48 transmitter, 49 receiver: 4-FSK (modems/fsk_text), n <= 32.
      wire fsk_cfg_ready,fsk_configured,fsk_error;
      logic cfg_valid_q,cfg_last_q,rst_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load&&seed[0];cfg_last_q<=seed[1];rst_q<=rst;end
      if(DUT_KIND==48) begin:g_tx
        wire signed [17:0] y_re,y_im;
        fsk_tx #(.LOG2M(2),.LOG2NMAX(5)) dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_last(cfg_last_q),.cfg_step({state[13:0],seed}),.cfg_n(seed_q[5:0]),
         .cfg_ready(fsk_cfg_ready),.configured(fsk_configured),.s_valid(enable),.s_last(load&&!seed[0]),.s_label(state[1:0]),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_re(y_re),.m_im(y_im),.m_ready(m_ready_q),.error(fsk_error));
        assign core_data={y_im,y_re};
      end else begin:g_rx
        wire [1:0] label;
        logic signed [17:0] sample_im_q;
        always_ff @(posedge clk) sample_im_q<=$signed(seed);
        fsk_rx #(.LOG2M(2),.LOG2NMAX(5)) dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_last(cfg_last_q),.cfg_step({state[13:0],seed}),.cfg_n(seed_q[5:0]),
         .cfg_ready(fsk_cfg_ready),.configured(fsk_configured),.s_valid(enable),.s_last(load&&!seed[0]),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_label(label),.m_ready(m_ready_q),.error(fsk_error));
        assign core_data={34'd0,label};
      end
      assign core_overflow={fsk_error^fsk_cfg_ready,fsk_configured};
    end else if(DUT_KIND==50||DUT_KIND==51) begin:g_combiner
      // 50 beamformer (8 channels), 51 Alamouti decoder.
      wire comb_cfg_ready,comb_configured,comb_error;
      wire signed [17:0] y_re,y_im;
      logic cfg_valid_q,cfg_last_q,rst_q;
      logic signed [17:0] sample_im_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load&&seed[0];cfg_last_q<=seed[1];rst_q<=rst;sample_im_q<=$signed(seed);end
      if(DUT_KIND==50) begin:g_beam
        beamform #(.LOG2M(3)) dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_last(cfg_last_q),.cfg_re($signed(state)),.cfg_im(sample_im_q),
         .cfg_ready(comb_cfg_ready),.configured(comb_configured),.s_valid(enable),.s_last(load&&!seed[0]),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_re(y_re),.m_im(y_im),.m_ready(m_ready_q),.error(comb_error));
      end else begin:g_alamouti
        alamouti_rx dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_last(cfg_last_q),.cfg_re($signed(state)),.cfg_im(sample_im_q),
         .cfg_ready(comb_cfg_ready),.configured(comb_configured),.s_valid(enable),.s_last(load&&!seed[0]),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_re(y_re),.m_im(y_im),.m_ready(m_ready_q),.error(comb_error));
      end
      assign core_data={y_im,y_re};
      assign core_overflow={comb_error^comb_cfg_ready,comb_configured};
    end else if(DUT_KIND==52||DUT_KIND==53) begin:g_sync
      // 52 Costas loop, 53 Gardner timing loop (synchronization/symbol_timing).
      wire sync_cfg_ready,sync_configured,sync_error;
      wire signed [17:0] y_re,y_im;
      wire signed [31:0] y_aux;
      logic cfg_valid_q,rst_q;
      logic signed [17:0] sample_im_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load&&seed[0];rst_q<=rst;sample_im_q<=$signed(seed);end
      if(DUT_KIND==52) begin:g_costas
        costas_loop dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_k1({state[13:0],seed}),.cfg_k2({seed[13:0],state}),
         .cfg_ready(sync_cfg_ready),.configured(sync_configured),.s_valid(enable),.s_last(load&&!seed[0]),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_re(y_re),.m_im(y_im),.m_phase(y_aux),.m_ready(m_ready_q));
        assign sync_error=1'b0;
      end else begin:g_gardner
        gardner_timing dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_sps(seed[7:0]),.cfg_count({seed_q[15:0]}),.cfg_position({state[11:0],seed,state}),
         .cfg_k3({state[13:0],seed}),.cfg_k4({seed[13:0],state}),
         .cfg_ready(sync_cfg_ready),.configured(sync_configured),.s_valid(enable),.s_last(load&&!seed[0]),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_re(y_re),.m_im(y_im),.m_position(y_aux),.m_ready(m_ready_q),.error(sync_error));
      end
      assign core_data={y_im,y_re}^{4'd0,y_aux};
      assign core_overflow={sync_error^sync_cfg_ready,sync_configured};
    end else if(DUT_KIND==54) begin:g_lms
      // LMS/NLMS adaptive filter, up to 4 taps (adaptive/lms_nlms_rls).
      wire lms_cfg_ready,lms_configured,lms_error,w_valid,w_last;
      wire signed [17:0] p_re,p_im,e_re,e_im,w_re,w_im;
      logic cfg_valid_q,rst_q;
      logic signed [17:0] sample_im_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load&&seed[0];rst_q<=rst;sample_im_q<=$signed(seed);end
      lms_filter #(.LOG2N(2)) dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_nlms(seed[1]),.cfg_taps(seed[4:2]),.cfg_mu(state),.cfg_eps({state[15:0],seed}),
       .cfg_ready(lms_cfg_ready),.configured(lms_configured),.s_valid(enable),.s_last(load&&!seed[0]),
       .s_re($signed(state)),.s_im(sample_im_q),.s_dre($signed(seed_q)),.s_dim($signed(state^seed)),.s_ready(core_ready),
       .m_valid(core_valid),.m_last(core_last),.m_pre(p_re),.m_pim(p_im),.m_ere(e_re),.m_eim(e_im),.m_ready(m_ready_q),
       .w_valid(w_valid),.w_last(w_last),.w_re(w_re),.w_im(w_im),.w_ready(m_ready_q),.error(lms_error));
      assign core_data={p_im^e_im^w_im,p_re^e_re^w_re};
      assign core_overflow={lms_error^lms_cfg_ready^w_last,lms_configured^w_valid};
    end else if(DUT_KIND==55||DUT_KIND==56) begin:g_ldpc
      // 55 LDPC decoder (n <= 128, m <= 64, 512 edges), 56 GF(2) encoder (64 x 64).
      wire l_cfg_ready,l_configured,l_error,l_bit;
      logic cfg_valid_q,cfg_last_q,rst_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load&&seed[0];cfg_last_q<=seed[1];rst_q<=rst;end
      if(DUT_KIND==55) begin:g_decoder
        wire signed [15:0] posterior;
        ldpc_decoder dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_last(cfg_last_q),.cfg_bit(seed[2]),.cfg_m(state[6:0]),.cfg_n(seed_q[7:0]),
         .cfg_iterations(state[17:10]),.cfg_mode(seed[4:3]),.cfg_alpha(seed[13:5]),.cfg_beta(seed_q[17:2]),.cfg_ready(l_cfg_ready),.configured(l_configured),
         .s_valid(enable),.s_last(load&&!seed[0]),.s_llr($signed(state[15:0])),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_bit(l_bit),.m_posterior(posterior),.m_ready(m_ready_q),.error(l_error));
        assign core_data={19'd0,l_bit,posterior};
      end else begin:g_encoder
        gf2_encoder dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_last(cfg_last_q),.cfg_bit(seed[2]),.cfg_m(state[6:0]),.cfg_k(seed_q[6:0]),
         .cfg_ready(l_cfg_ready),.configured(l_configured),.s_valid(enable),.s_last(load&&!seed[0]),.s_bit(state[0]),.s_ready(core_ready),
         .m_valid(core_valid),.m_last(core_last),.m_bit(l_bit),.m_ready(m_ready_q),.error(l_error));
        assign core_data={35'd0,l_bit};
      end
      assign core_overflow={l_error^l_cfg_ready,l_configured};
    end else if(DUT_KIND==57) begin:g_mmse2
      // 2x2 MMSE / zero-forcing solver (mimo/dsplog).
      wire mm_cfg_ready,mm_configured,mm_error;
      wire signed [17:0] y_re,y_im;
      logic cfg_valid_q,cfg_last_q,rst_q;
      logic signed [17:0] sample_im_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load&&seed[0];cfg_last_q<=seed[1];rst_q<=rst;sample_im_q<=$signed(seed);end
      mmse2 dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_last(cfg_last_q),.cfg_re($signed(state)),.cfg_im(sample_im_q),.cfg_lambda({state[15:0],seed}),
       .cfg_ready(mm_cfg_ready),.configured(mm_configured),.s_valid(enable),.s_last(load&&!seed[0]),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
       .m_valid(core_valid),.m_last(core_last),.m_re(y_re),.m_im(y_im),.m_ready(m_ready_q),.error(mm_error));
      assign core_data={y_im,y_re};
      assign core_overflow={mm_error^mm_cfg_ready,mm_configured};
    end else if(DUT_KIND==58) begin:g_rls
      // RLS adaptive filter, up to 4 taps (adaptive/lms_nlms_rls).
      wire rls_cfg_ready,rls_configured,rls_error,w_valid,w_last;
      wire signed [17:0] p_re,p_im,e_re,e_im,w_re,w_im;
      logic cfg_valid_q,rst_q;
      logic signed [17:0] sample_im_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load&&seed[0];rst_q<=rst;sample_im_q<=$signed(seed);end
      rls_filter #(.LOG2N(2)) dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_taps(seed[3:1]),.cfg_p0({state[7:0],seed,state}),
       .cfg_lambda({state[11:0],seed}),.cfg_invl({state[13:0],seed}),.cfg_ready(rls_cfg_ready),.configured(rls_configured),.s_valid(enable),.s_last(load&&!seed[0]),
       .s_re($signed(state)),.s_im(sample_im_q),.s_dre($signed(seed_q)),.s_dim($signed(state^seed)),.s_ready(core_ready),
       .m_valid(core_valid),.m_last(core_last),.m_pre(p_re),.m_pim(p_im),.m_ere(e_re),.m_eim(e_im),.m_ready(m_ready_q),
       .w_valid(w_valid),.w_last(w_last),.w_re(w_re),.w_im(w_im),.w_ready(m_ready_q),.error(rls_error));
      assign core_data={p_im^e_im^w_im,p_re^e_re^w_re};
      assign core_overflow={rls_error^rls_cfg_ready^w_last,rls_configured^w_valid};
    end else if(DUT_KIND==59) begin:g_omlsa
      // OM-LSA enhancer, N = 32, HOP = 8 (audio/omlsa).
      wire om_cfg_ready,om_configured,om_error;
      wire signed [17:0] y_re,y_im;
      logic cfg_valid_q,rst_q;
      logic signed [17:0] sample_im_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load&&seed[0];rst_q<=rst;sample_im_q<=$signed(seed);end
      omlsa #(.LOG2N(5),.LOG2HOP(3)) dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_nnoise(seed[5:1]),.cfg_alpha(state[16:0]),
       .cfg_ready(om_cfg_ready),.configured(om_configured),.s_valid(enable),.s_last(load&&!seed[0]),.s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),
       .m_valid(core_valid),.m_last(core_last),.m_re(y_re),.m_im(y_im),.m_ready(m_ready_q),.error(om_error));
      assign core_data={y_im,y_re};
      assign core_overflow={om_error^om_cfg_ready,om_configured};
    end else if(DUT_KIND==22) begin:g_simo_rx
      // Two-branch SIMO receiver: combiner plus diagonal unit QPSK Gray-differential core.
      wire configured,error,cfg_ready,acq_valid,acq_conf,gain_ready,gain_configured,gain_error,saturated;
      wire [1:0] m_bit,m_index;
      wire signed [17:0] re,im;
      wire signed [31:0] phase,frequency,correction,acq_delay,acq_frequency,acq_phase;
      wire [24:0] gain,acq_gain;
      wire [63:0] score;
      // Configuration and reset are registered, as for the single-branch receivers.
      logic cfg_valid_q,cfg_last_q,gain_valid_q,rst_q;
      logic [1:0] cfg_bit_q;
      logic signed [17:0] gain_q[0:3];
      logic [15:0] variance_q[0:1];
      always_ff @(posedge clk) begin
        cfg_valid_q<=load&&!seed[17];cfg_last_q<=seed[1];cfg_bit_q<=seed[4:3];rst_q<=rst;gain_valid_q<=load&&seed[17];
        gain_q[0]<=$signed(state);gain_q[1]<=$signed(seed);gain_q[2]<=$signed({state[8:0],seed[17:9]});gain_q[3]<=$signed({seed[8:0],state[17:9]});
        variance_q[0]<=state[15:0];variance_q[1]<=seed[15:0];
      end
      simo_rx dut(.clk(clk),.rst(rst_q),.gain_valid(gain_valid_q),.gain_a_re(gain_q[0]),.gain_a_im(gain_q[1]),.gain_b_re(gain_q[2]),.gain_b_im(gain_q[3]),
       .variance_a(variance_q[0]),.variance_b(variance_q[1]),.gain_ready(gain_ready),.gain_configured(gain_configured),.gain_error(gain_error),.saturated(saturated),
       .cfg_valid(cfg_valid_q),.cfg_bit(cfg_bit_q),.cfg_last(cfg_last_q),.cfg_count(12'd768),.cfg_ready(cfg_ready),.configured(configured),.error(error),
       .s_valid(enable),.s_last(seed[2]),.s_a_re($signed(state)),.s_a_im($signed(seed)),.s_b_re($signed({state[0],state[17:1]})),.s_b_im($signed(state^seed)),.s_ready(core_ready),
       .m_valid(core_valid),.m_last(core_last),.m_bit(m_bit),.m_index(m_index),.m_ready(m_ready_q),.m_re(re),.m_im(im),.m_phase(phase),.m_frequency(frequency),.m_correction(correction),.m_gain(gain),
       .acquisition_valid(acq_valid),.acquisition_confidence(acq_conf),.acquisition_delay(acq_delay),.acquisition_frequency(acq_frequency),.acquisition_phase(acq_phase),.acquisition_gain(acq_gain),.acquisition_score(score));
      assign core_data={im,re}^{4'd0,phase}^{4'd0,frequency}^{4'd0,correction}^{4'd0,acq_delay}^{4'd0,acq_frequency}^{4'd0,acq_phase}^{11'd0,gain}^{11'd0,acq_gain}^{4'd0,score[31:0]}^{4'd0,score[63:32]};
      assign core_overflow={configured^error^cfg_ready^acq_valid^m_bit[1]^m_index[1]^gain_ready^gain_configured,m_bit[0]^m_index[0]^acq_conf^gain_error^saturated};
    end else if(DUT_KIND==23) begin:g_mrc
      // Two-branch combiner alone, including the weight multiplier and divider.
      wire cfg_ready,configured,error,saturated;
      logic cfg_valid_q;
      logic signed [17:0] gain_q[0:3];
      logic [15:0] variance_q[0:1];
      always_ff @(posedge clk) begin
        cfg_valid_q<=load;
        gain_q[0]<=$signed(state);gain_q[1]<=$signed(seed);gain_q[2]<=$signed({state[8:0],seed[17:9]});gain_q[3]<=$signed({seed[8:0],state[17:9]});
        variance_q[0]<=state[15:0];variance_q[1]<=seed[15:0];
      end
      fxp_mrc2 dut(.clk(clk),.rst(rst),.cfg_valid(cfg_valid_q),.cfg_gain_a_re(gain_q[0]),.cfg_gain_a_im(gain_q[1]),.cfg_gain_b_re(gain_q[2]),.cfg_gain_b_im(gain_q[3]),
       .cfg_variance_a(variance_q[0]),.cfg_variance_b(variance_q[1]),.cfg_ready(cfg_ready),.configured(configured),.error(error),.saturated(saturated),
       .s_valid(enable),.s_last(seed[2]),.s_a_re($signed(state)),.s_a_im($signed(seed)),.s_b_re($signed({state[0],state[17:1]})),.s_b_im($signed(state^seed)),.s_ready(core_ready),
       .m_valid(core_valid),.m_last(core_last),.m_ready(m_ready_q),.m_re(core_data[17:0]),.m_im(core_data[35:18]),.cfg_enable(1'b1));
      assign core_overflow={cfg_ready^configured,error^saturated};
    end
    else if(DUT_KIND==7||DUT_KIND==9||(DUT_KIND>=11&&DUT_KIND<=13)||DUT_KIND==16||DUT_KIND==17||DUT_KIND==21||DUT_KIND==24||DUT_KIND==26||DUT_KIND==30) begin:g_bpsk_tx
      // 7 BPSK; QPSK: 9 diagonal 0.7071, 11 diagonal 0.5 Gray-differential,
      // 12 unit axes Gray-differential, 13 unit axes, 21 diagonal 0.7071 Gray-differential (SIMO);
      // 8-PSK Gray-differential: 16 points at k*45 degrees, 17 at 22.5+k*45 degrees;
      // 24 pi/4-QPSK (8 points at k*45 degrees, 2-bit labels); 26 QAM16 quadrant-differential;
      // 30 QAM64 quadrant-differential.
      localparam int ORDER=DUT_KIND==7?2:DUT_KIND==30?64:DUT_KIND==26?16:DUT_KIND==16||DUT_KIND==17||DUT_KIND==24?8:4;
      localparam int BITS=DUT_KIND==24?2:ORDER==64?6:ORDER==16?4:ORDER==8?3:ORDER==4?2:1;
      bpsk_tx #(.ORDER(ORDER),.AMPLITUDE(ORDER==8?32768:DUT_KIND==7||DUT_KIND==11||DUT_KIND==26||DUT_KIND==30?16384:23170),
       .DIFFERENTIAL(DUT_KIND==7||DUT_KIND==11||DUT_KIND==12||DUT_KIND==21||DUT_KIND==26||DUT_KIND==30||ORDER==8),
       .TX_AXIS(DUT_KIND==12||DUT_KIND==13||DUT_KIND==16||DUT_KIND==24),.PI4(DUT_KIND==24)) dut(.clk(clk),.rst(rst),.s_valid(enable),.s_bit(seed[BITS-1:0]),.s_last(load),.s_ready(core_ready),
       .m_ready(m_ready_q),.m_valid(core_valid),.m_last(core_last),.m_re(core_data[17:0]),.m_im(core_data[35:18]));
      assign core_overflow=0;
    end else begin:g_bpsk_rx
      // 8 BPSK; QPSK: 10 diagonal 0.7071 (also unit axes), 14 diagonal 0.5 Gray-differential,
      // 15 unit axes Gray-differential with feedforward carrier and no timing loop;
      // 8-PSK Gray-differential: 18 feedforward without timing loop, 19 feedback with
      // timing loop, 20 feedback without timing loop; 25 pi/4-QPSK (2-bit labels); 27 QAM16;
      // QAM16 with an equalizer: 28 NLMS, 29 DFE; 31 QAM64 (T = 8192).
      localparam int ORDER=DUT_KIND==8?2:DUT_KIND==31?64:DUT_KIND>=27?16:DUT_KIND>=18?8:4;
      localparam int BITS=DUT_KIND==25?2:ORDER==64?6:ORDER==16?4:ORDER==8?3:ORDER==4?2:1,INDEX_BITS=ORDER==64?6:ORDER==16?4:ORDER==8?3:ORDER==4?2:1;
      wire configured,error,cfg_ready,acq_valid,acq_conf;
      wire [BITS-1:0] m_bit;
      wire [INDEX_BITS-1:0] m_index;
      wire [5:0] m_bit3=6'(m_bit),m_index3=6'(m_index);
      wire signed [17:0] re,im;
      wire signed [31:0] phase,frequency,correction,acq_delay,acq_frequency,acq_phase;
      wire [24:0] gain,acq_gain;
      wire [63:0] score;
      // Configuration inputs are registered: the 384-bit training store is not an IO register.
      logic cfg_valid_q,cfg_last_q;
      logic [BITS-1:0] cfg_bit_q;
      // The synchronous reset is registered as a reset synchronizer output would be.
      logic rst_q;
      // The sample input from the seed pins is registered too, as an upstream stage would drive it.
      logic signed [17:0] sample_im_q;
      logic sample_last_q;
      always_ff @(posedge clk) begin cfg_valid_q<=load;cfg_last_q<=seed[1];cfg_bit_q<=seed[BITS+2:3];rst_q<=rst;sample_im_q<=$signed(seed);sample_last_q<=seed[2];end
      bpsk_rx #(.ORDER(ORDER),.AMPLITUDE(ORDER==8?32768:DUT_KIND==31?8192:DUT_KIND==8||DUT_KIND==14||DUT_KIND>=27?16384:23170),.DIFFERENTIAL(DUT_KIND==8||DUT_KIND>=14),
       .FEEDFORWARD(DUT_KIND==15||DUT_KIND==18||DUT_KIND==25),.TIMING_LOOP(DUT_KIND!=15&&DUT_KIND!=18&&DUT_KIND!=20&&DUT_KIND!=25),.PI4(DUT_KIND==25),.EQUALIZER(DUT_KIND==28?1:DUT_KIND==29?2:0)) dut(.clk(clk),.rst(rst_q),.cfg_valid(cfg_valid_q),.cfg_bit(cfg_bit_q),.cfg_last(cfg_last_q),.cfg_count(12'd768),
       .cfg_ready(cfg_ready),.configured(configured),.error(error),.s_valid(enable),.s_last(sample_last_q),
       .s_re($signed(state)),.s_im(sample_im_q),.s_ready(core_ready),.m_valid(core_valid),.m_last(core_last),
       .m_bit(m_bit),.m_index(m_index),.m_ready(m_ready_q),.m_re(re),.m_im(im),.m_phase(phase),.m_frequency(frequency),.m_correction(correction),.m_gain(gain),
       .acquisition_valid(acq_valid),.acquisition_confidence(acq_conf),.acquisition_delay(acq_delay),.acquisition_frequency(acq_frequency),.acquisition_phase(acq_phase),.acquisition_gain(acq_gain),.acquisition_score(score),.cfg_enable(1'b1));
      // Preserve every diagnostic bit using observable XOR folds.
      assign core_data={im,re}^{4'd0,phase}^{4'd0,frequency}^{4'd0,correction}^{4'd0,acq_delay}^{4'd0,acq_frequency}^{4'd0,acq_phase}^{11'd0,gain}^{11'd0,acq_gain}^{4'd0,score[31:0]}^{4'd0,score[63:32]};
      assign core_overflow={configured^error^cfg_ready^acq_valid^m_bit3[2]^m_bit3[1]^m_index3[2]^m_index3[1],m_bit3[3]^m_index3[3]^m_bit3[0]^m_index3[0]^acq_conf^m_bit3[5]^m_bit3[4]^m_index3[5]^m_index3[4]};
    end
  endgenerate
endmodule
