// Selected active OQPSK accesses. Unused cubic taps outside the captured frame are
// legal zeros; inactive/stale pipeline indices are not interpreted as accesses.
int oq_tx_checks=0,oq_capture_checks=0,oq_request_checks=0,oq_acq_checks=0,oq_costas_checks=0;
int oq_tx_expected=0,oq_reader_pending=0,oq_pair_pending=0;
int oq_pairs=0,oq_rotated=0;
bit oq_i_wait=0,oq_rot_i_wait=0,oq_output_expected=0;
int oq_bank_checks[0:7],oq_tail_checks[0:7];
int oq_mask_checks[0:4],oq_zero_checks[0:4];
int oq_pipeline_peak=0,oq_pair_peak=0,oq_tx_simultaneous=0;
// Full symbol-index history, independent of the DUT's 16-slot error ring. Check
// both readiness and the exact value selected for k-LOOP_DELAY, including CE stalls.
logic signed [31:0] oq_error_history[0:2047],oq_expected_error;
int oq_request_tick[0:2047];
int oq_feedback_tick=0,oq_errors_stored=0,oq_feedback_checks=0,oq_feedback_cold=0;
int oq_feedback_latency_min=1000000,oq_feedback_latency_max=0;
bit oq_feedback_pending=0;

always @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin
    oq_tx_checks=0;oq_capture_checks=0;oq_request_checks=0;oq_acq_checks=0;oq_costas_checks=0;
    oq_tx_expected=0;oq_reader_pending=0;oq_pair_pending=0;
    oq_pairs=0;oq_rotated=0;oq_i_wait=0;oq_rot_i_wait=0;oq_output_expected=0;
    oq_pipeline_peak=0;oq_pair_peak=0;oq_tx_simultaneous=0;
    oq_feedback_tick=0;oq_errors_stored=0;oq_feedback_checks=0;oq_feedback_cold=0;
    oq_feedback_latency_min=1000000;oq_feedback_latency_max=0;oq_feedback_pending=0;
  end else begin
    int next_tx,next_reader;
    if($isunknown({dut.buffered,dut.push,dut.pop,dut.ce,receiver.state,receiver.taking,
                   receiver.f_valid,receiver.flush,receiver.q_valid,receiver.stream_ce}))
      $fatal(1,"[BOUNDS] OQPSK unknown active controls");
    if(int'(dut.buffered)!=oq_tx_expected) $fatal(1,"[BOUNDS] OQPSK TX buffer transition");
    next_tx=int'(dut.buffered)+int'(dut.push)-int'(dut.pop);
    if(int'(dut.buffered)>2||next_tx<0||next_tx>2
       ||(dut.pop&&dut.buffered==0)||(dut.push&&dut.buffered==2))
      $fatal(1,"[BOUNDS] OQPSK TX buffer capacity/read/write");
    if(dut.push&&dut.pop&&dut.buffered!=1) $fatal(1,"[BOUNDS] OQPSK TX simultaneous slot");
    oq_tx_expected=next_tx;
    if(scoring&&(dut.push||dut.pop)) oq_tx_checks++;
    if(scoring&&dut.push&&dut.pop) oq_tx_simultaneous++;

    if(cfg_valid&&cfg_ready) begin
      if($isunknown(receiver.config_index)||int'(receiver.config_index)>=192)
        $fatal(1,"[BOUNDS] OQPSK preamble configuration index");
      if(scoring) oq_capture_checks++;
    end
    if(receiver.taking) begin
      if($isunknown({receiver.input_count,receiver.input_frame})
         ||int'(receiver.input_count)>=16480)
        $fatal(1,"[BOUNDS] OQPSK capture input index");
      if(scoring) oq_capture_checks++;
    end
    if(receiver.f_valid) begin
      int observed;
      observed=int'(receiver.out_count);
      if(scoring&&$test$plusargs("INJECT_BOUND_MISMATCH")) observed=16512;
      if($isunknown({receiver.out_count,receiver.out_frame})||observed<0||observed>=16512)
        $fatal(1,"[BOUNDS] OQPSK active capture RAM write index");
      if(!receiver.occupied[receiver.out_frame]
         ||int'(receiver.written[receiver.out_frame])!=int'(receiver.out_count))
        $fatal(1,"[BOUNDS] OQPSK capture frame ownership/written count");
      if(scoring) oq_capture_checks++;
    end

    if(receiver.stream_ce) begin
      next_reader=oq_reader_pending+int'(receiver.q_valid)-int'(receiver.samples_valid);
      if(next_reader<0||next_reader>7) $fatal(1,"[BOUNDS] OQPSK reader in-flight requests");
      oq_reader_pending=next_reader;
      if(next_reader>oq_pipeline_peak) oq_pipeline_peak=next_reader;
      if(receiver.q_valid) begin
        if($isunknown({receiver.q_tag,receiver.q_position,receiver.process_frame})
           ||!receiver.occupied[receiver.process_frame]
           ||int'(receiver.written[receiver.process_frame])>16512)
          $fatal(1,"[BOUNDS] OQPSK reader request frame/length");
        if(receiver.pass1) begin
          if(receiver.q_tag[14:11]!=0||receiver.p1_i>10)
            $fatal(1,"[BOUNDS] OQPSK pass1 request symbol/offset");
        end else if(receiver.pass2) begin
          if(receiver.q_tag[14:8]!=0) $fatal(1,"[BOUNDS] OQPSK pass2 request tag");
        end else if(receiver.state==4'd13) begin // DATA
          if(receiver.q_tag[14:13]!=0||receiver.data_k>=receiver.symbol_count)
            $fatal(1,"[BOUNDS] OQPSK data request symbol");
        end else $fatal(1,"[BOUNDS] OQPSK request in inactive state");
        if(scoring) oq_request_checks++;
      end
      if(receiver.p1_valid) begin
        if(receiver.samples_tag[14:11]!=0||receiver.r1_i>10
           ||2*int'(receiver.r1_k)+1>=384)
          $fatal(1,"[BOUNDS] OQPSK pass1 training/offset access");
        if(scoring) oq_acq_checks++;
      end
      if(receiver.p2_valid) begin
        if(receiver.samples_tag[14:8]!=0||2*int'(receiver.r2_k)+1>=384)
          $fatal(1,"[BOUNDS] OQPSK pass2 training access");
        if(scoring) oq_acq_checks++;
      end
    end
    if(receiver.e_run) begin
      if($isunknown(receiver.ej)||receiver.ej>=18) $fatal(1,"[BOUNDS] OQPSK snapshot read lag");
      if(scoring) oq_acq_checks++;
    end
    if(receiver.e1_valid&&($isunknown(receiver.e1_index)||receiver.e1_index>=18))
      $fatal(1,"[BOUNDS] OQPSK energy stage1 lag");
    if(receiver.e2_valid&&($isunknown(receiver.e2_index)||receiver.e2_index>=18))
      $fatal(1,"[BOUNDS] OQPSK energy stage2 lag");
    if(receiver.e3_valid) begin
      if($isunknown(receiver.e3_index)||receiver.e3_index>=18)
        $fatal(1,"[BOUNDS] OQPSK active energy write lag");
      if(scoring) oq_acq_checks++;
    end
    if(receiver.state==4'd3) begin // PEAK: energy[scan] (or energy[0]).
      if($isunknown(receiver.scan)||receiver.scan>=18) $fatal(1,"[BOUNDS] OQPSK peak scan lag");
      if(scoring) oq_acq_checks++;
    end
    if(receiver.state==4'd4) begin // FRACTION: best and conditionally best +/- 1.
      if($isunknown(receiver.best)||receiver.best>=18) $fatal(1,"[BOUNDS] OQPSK parabola energy lag");
      if(scoring) oq_acq_checks++;
    end
    if(receiver.block_valid) begin
      if(receiver.angle_tag[3]!==1'b1||receiver.phases_seen>=8)
        $fatal(1,"[BOUNDS] OQPSK acquisition block phase");
      if(scoring) oq_acq_checks++;
    end

    if(receiver.costas.m_valid!==oq_output_expected)
      $fatal(1,"[BOUNDS] OQPSK output slot transition");
    if(receiver.costas_start) begin
      if(oq_pair_pending!=0||oq_i_wait||oq_rot_i_wait)
        $fatal(1,"[BOUNDS] OQPSK new frame with live symbol reservation");
      oq_pairs=0;oq_rotated=0;
      oq_errors_stored=0;oq_feedback_pending=0;
    end
    if(receiver.costas.ce) begin
      int next_pairs;
      bit emit_symbol;
      oq_feedback_tick++;
      if(oq_feedback_pending) begin
        logic signed [31:0] observed;
        observed=receiver.costas.error_q;
        if(scoring&&$test$plusargs("INJECT_FEEDBACK_VALUE")) observed=observed^32'sd1;
        if(observed!==oq_expected_error) $fatal(1,"[FEEDBACK] OQPSK wrong delayed error value");
      end
      oq_feedback_pending=0;
      if(receiver.state==4'd13&&receiver.q_valid&&receiver.data_phase==0) begin
        int needed;
        needed=int'(receiver.data_k)-LOOP_DELAY;
        if(needed>=0&&needed>=oq_errors_stored)
          $fatal(1,"[FEEDBACK] OQPSK request before delayed error is ready");
        oq_request_tick[receiver.data_k]=oq_feedback_tick;
      end
      emit_symbol=receiver.costas.rot_valid&&receiver.costas.r_sel;
      next_pairs=oq_pair_pending+int'(receiver.costas.pair)-int'(emit_symbol);
      if(next_pairs<0||next_pairs>16) $fatal(1,"[BOUNDS] OQPSK symbol pipeline reservations");
      oq_pair_pending=next_pairs;
      if(next_pairs>oq_pair_peak) oq_pair_peak=next_pairs;
      if(receiver.costas.s_valid) begin
        if($isunknown({receiver.costas.s_symbol,receiver.costas.s_sel})
           ||receiver.costas.s_symbol>=receiver.symbol_count||int'(receiver.costas.s_symbol)!=oq_pairs)
          $fatal(1,"[BOUNDS] OQPSK active timing symbol tag");
        if(!receiver.costas.s_sel) begin
          if(oq_i_wait) $fatal(1,"[BOUNDS] OQPSK duplicated I instant");
          oq_i_wait=1;
        end else begin
          if(!oq_i_wait) $fatal(1,"[BOUNDS] OQPSK Q instant without I");
          oq_i_wait=0;oq_pairs++;
          oq_expected_error=0;oq_feedback_pending=1;
          if(int'(receiver.costas.s_symbol)>=LOOP_DELAY) begin
            int needed;
            needed=int'(receiver.costas.s_symbol)-LOOP_DELAY;
            if(oq_errors_stored<=needed||oq_errors_stored-needed>16)
              $fatal(1,"[FEEDBACK] OQPSK delayed loop error missing/overwritten");
            oq_expected_error=oq_error_history[needed];
            if(scoring) oq_feedback_checks++;
          end else if(scoring) oq_feedback_cold++;
        end
        if(scoring) oq_costas_checks++;
      end
      if(receiver.costas.rot_valid) begin
        if($isunknown(receiver.costas.rot_tag)||receiver.costas.rot_tag[31:13]!=0
           ||int'(receiver.costas.r_symbol)!=oq_rotated||receiver.costas.r_symbol>=receiver.symbol_count)
          $fatal(1,"[BOUNDS] OQPSK active rotator symbol tag");
        if(receiver.costas.r_symbol<188&&int'(receiver.costas.train_index)+1>=384)
          $fatal(1,"[BOUNDS] OQPSK declared preamble target access");
        if(!receiver.costas.r_sel) begin
          if(oq_rot_i_wait) $fatal(1,"[BOUNDS] OQPSK duplicated rotated I");
          oq_rot_i_wait=1;
        end else begin
          if(!oq_rot_i_wait) $fatal(1,"[BOUNDS] OQPSK rotated Q without I");
          oq_rot_i_wait=0;oq_rotated++;
        end
        if(scoring) oq_costas_checks++;
      end
      if(receiver.costas.angle_valid&&receiver.costas.angle_tag[4]) begin
        int latency;
        if($isunknown(receiver.costas.angle_tag)||int'(receiver.costas.angle_tag[3:0])!=(int'(receiver.error_count)&15))
          $fatal(1,"[BOUNDS] OQPSK active error ring write tag");
        if(oq_errors_stored>=oq_pairs) $fatal(1,"[FEEDBACK] OQPSK error without symbol");
        oq_error_history[oq_errors_stored]=32'(($signed({receiver.costas.e_i_hold[31],receiver.costas.e_i_hold})
                                             +$signed({receiver.costas.clipped[31],receiver.costas.clipped}))>>>1);
        latency=oq_feedback_tick-oq_request_tick[oq_errors_stored];
        if(scoring) begin
          if(latency<oq_feedback_latency_min) oq_feedback_latency_min=latency;
          if(latency>oq_feedback_latency_max) oq_feedback_latency_max=latency;
        end
        oq_errors_stored++;
        if(scoring) oq_costas_checks++;
      end
      oq_output_expected=emit_symbol;
    end
  end
end

// Constant bank hierarchy references validate physical writes and only the read
// taps actually present in the frame. Masked read ports may legally wrap.
for(genvar bank=0;bank<8;bank++) begin:g_oq_bounds_bank
  bit selected_valid=0,expected_tail=0;
  always @(posedge clk) begin
    if(rst==RESET_ACTIVE) begin
      oq_bank_checks[bank]=0;oq_tail_checks[bank]=0;selected_valid=0;expected_tail=0;
    end
    else begin
      if(receiver.samples.wr_en&&receiver.samples.wr_index[2:0]==3'(bank)) begin
        if(receiver.samples.g_bank[bank].main_memory.wr_en!==!receiver.samples.wr_index[14]
           ||receiver.samples.g_bank[bank].tail_memory.wr_en!==receiver.samples.wr_index[14])
          $fatal(1,"[BOUNDS] OQPSK sample bank write enable");
        if(!receiver.samples.wr_index[14]) begin
          if(receiver.samples.g_bank[bank].main_memory.wr_addr!=={receiver.samples.wr_frame,receiver.samples.wr_index[13:3]})
            $fatal(1,"[BOUNDS] OQPSK main sample write address");
        end else if(receiver.samples.g_bank[bank].tail_memory.wr_addr!=={receiver.samples.wr_frame,receiver.samples.wr_index[6:3]})
          $fatal(1,"[BOUNDS] OQPSK tail sample write address");
        if(scoring) oq_bank_checks[bank]++;
      end
      if(receiver.samples.ce) begin
        int index,row,expected_address;
        if(selected_valid&&receiver.samples.g_bank[bank].select_tail!==expected_tail)
          $fatal(1,"[BOUNDS] OQPSK sample bank main/tail selector pipeline");
        selected_valid=0;
        index=int'(receiver.samples.base)+((bank-(int'(receiver.samples.base)&7))&7);
        if(receiver.samples.p_valid&&index>=int'(receiver.samples.base)&&index<=int'(receiver.samples.base)+4
           &&index>=0&&index<int'(receiver.samples.p_length)) begin
          selected_valid=1;expected_tail=index>=16384;
          if(index>=16512||receiver.samples.p_length>16512)
            $fatal(1,"[BOUNDS] OQPSK active interpolator sample index");
          row=index>>3;
          if(index<16384) begin
            expected_address=int'(receiver.samples.p_frame)*2048+row;
            if(!receiver.samples.g_bank[bank].main_memory.rd_en
               ||int'(receiver.samples.g_bank[bank].main_memory.rd_addr)!=expected_address)
              $fatal(1,"[BOUNDS] OQPSK active main sample read address");
          end else begin
            expected_address=int'(receiver.samples.p_frame)*16+(row&15);
            if(!receiver.samples.g_bank[bank].tail_memory.rd_en
               ||int'(receiver.samples.g_bank[bank].tail_memory.rd_addr)!=expected_address)
              $fatal(1,"[BOUNDS] OQPSK active tail sample read address");
            if(scoring) oq_tail_checks[bank]++;
          end
          if(scoring) oq_bank_checks[bank]++;
        end
      end
    end
  end
end

for(genvar tap=0;tap<5;tap++) begin:g_oq_bounds_mask
  bit present_valid=0,ordered_valid=0,expected_present=0,expected_order_present=0;
  // Corrupt actual DUT data only once this tap is a real out-of-frame zero.
  // Constant generate references avoid variable hierarchy indices in Questa.
  always @(negedge clk) begin
    if(rst!=RESET_ACTIVE&&scoring&&ordered_valid&&!expected_order_present
       &&$test$plusargs("INJECT_ZERO_DATA"))
      force receiver.samples.ordered_re[tap]=18'sd1;
  end
  always @(posedge clk) begin
    if(rst==RESET_ACTIVE) begin
      oq_mask_checks[tap]=0;oq_zero_checks[tap]=0;present_valid=0;ordered_valid=0;expected_present=0;expected_order_present=0;
    end else if(receiver.samples.ce) begin
      if(present_valid&&receiver.samples.present[tap]!==expected_present)
        $fatal(1,"[BOUNDS] OQPSK interpolator present-mask pipeline");
      if(ordered_valid&&!expected_order_present
         &&(receiver.samples.ordered_re[tap]!==18'sd0||receiver.samples.ordered_im[tap]!==18'sd0))
        $fatal(1,"[BOUNDS] OQPSK out-of-frame tap did not substitute zero");
      if(scoring&&present_valid) oq_mask_checks[tap]++;
      if(scoring&&ordered_valid&&!expected_order_present) oq_zero_checks[tap]++;
      ordered_valid=present_valid;expected_order_present=expected_present;
      present_valid=receiver.samples.p_valid;
      expected_present=int'(receiver.samples.base)+tap>=0
                       &&int'(receiver.samples.base)+tap<int'(receiver.samples.p_length);
    end
  end
end

task automatic check_oqpsk_bounds();
  int banks,tails,masks,zeros;
  banks=0;tails=0;masks=0;zeros=0;
  for(int bank=0;bank<8;bank++) begin
    if(oq_bank_checks[bank]<1) $fatal(1,"[BOUNDS] OQPSK sample bank not exercised");
    banks+=oq_bank_checks[bank];tails+=oq_tail_checks[bank];
  end
  for(int tap=0;tap<5;tap++) begin
    if(oq_mask_checks[tap]<1) $fatal(1,"[BOUNDS] OQPSK interpolator mask not exercised");
    masks+=oq_mask_checks[tap];zeros+=oq_zero_checks[tap];
  end
  if(oq_tx_checks<1||oq_capture_checks<1||oq_request_checks<1||oq_acq_checks<1||oq_costas_checks<1)
    $fatal(1,"[BOUNDS] OQPSK selected active monitors not exercised");
  if(dut.buffered!=0||oq_reader_pending!=0||oq_pair_pending!=0||oq_i_wait||oq_rot_i_wait)
    $fatal(1,"[BOUNDS] OQPSK buffers/reservations not drained");
  if(oq_feedback_checks<1||oq_feedback_cold<1||oq_feedback_latency_min<1
     ||oq_feedback_latency_max<oq_feedback_latency_min)
    $fatal(1,"[FEEDBACK] OQPSK feedback monitor not exercised");
  $display("PASS FEEDBACK OQPSK: %0d %0d %0d %0d %0d",LOOP_DELAY,oq_feedback_checks,oq_feedback_cold,
           oq_feedback_latency_min,oq_feedback_latency_max);
  $display("PASS BOUNDS OQPSK: %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",
           oq_tx_checks,oq_capture_checks,oq_request_checks,oq_acq_checks,oq_costas_checks,
           banks,masks,tails,zeros,oq_pipeline_peak,oq_pair_peak,oq_tx_simultaneous);
endtask
