// Full UVM RX pilot: BPSK, QPSK_DIFF SIMO and PSK8_FB; compile-selected widths.
// Source controls change on negedges. Clocking inputs #1step describe the
// pre-edge handshake; the monitor never reads post-NBA values as accepted data.
`timescale 1ns/1ps
`ifndef PILOT_ORDER
`define PILOT_ORDER 2
`endif
`ifndef PILOT_AMPLITUDE
`define PILOT_AMPLITUDE 16384
`endif
`ifndef PILOT_DIFFERENTIAL
`define PILOT_DIFFERENTIAL 1
`endif
`ifndef PILOT_FEEDFORWARD
`define PILOT_FEEDFORWARD 0
`endif
`ifndef PILOT_TIMING_LOOP
`define PILOT_TIMING_LOOP 1
`endif
`ifndef PILOT_SIMO
`define PILOT_SIMO 0
`endif

interface bpsk_rx_uvm_if(input logic clk);
`ifdef RTL_RESET_LOW
  localparam bit ACTIVE=0;
`else
  localparam bit ACTIVE=1;
`endif
  localparam int ORDER=`PILOT_ORDER,LABEL_BITS=ORDER==8?3:ORDER==4?2:1,INDEX_BITS=LABEL_BITS;
  localparam bit SIMO=`PILOT_SIMO;
  logic rst=ACTIVE,cfg_valid=0,cfg_last=0;
  logic [LABEL_BITS-1:0] cfg_bit=0;
  logic gain_valid=0;
  logic signed [17:0] gain_a_re=0,gain_a_im=0,gain_b_re=0,gain_b_im=0;
  logic [15:0] variance_a=1,variance_b=1;
  wire gain_ready,gain_configured,gain_error,saturated;
  logic [11:0] cfg_count=768;
  wire cfg_ready,configured,error;
  logic s_valid=0,s_last=0;
  logic signed [17:0] s_re=0,s_im=0,s_b_re=0,s_b_im=0;
  wire s_ready,m_valid,m_last;
  wire [LABEL_BITS-1:0] m_bit;
  wire [INDEX_BITS-1:0] m_index;
  logic m_ready=1;
  wire signed [17:0] m_re,m_im;
  wire signed [31:0] m_phase,m_frequency,m_correction;
  wire [24:0] m_gain;
  wire acquisition_valid,acquisition_confidence;
  wire signed [31:0] acquisition_delay,acquisition_frequency,acquisition_phase;
  wire [24:0] acquisition_gain;
  wire [63:0] acquisition_score;
  clocking sample @(posedge clk);
    default input #1step;
    input rst,cfg_valid,cfg_bit,cfg_last,cfg_count,cfg_ready,configured,error;
    input s_valid,s_last,s_re,s_im,s_b_re,s_b_im,s_ready;
    input gain_valid,gain_a_re,gain_a_im,gain_b_re,gain_b_im,variance_a,variance_b,gain_ready,gain_configured,gain_error,saturated;
    input m_valid,m_ready,m_last,m_bit,m_index,m_re,m_im,m_phase,m_frequency,m_correction,m_gain;
    input acquisition_valid,acquisition_confidence,acquisition_delay,acquisition_frequency,acquisition_phase,acquisition_gain,acquisition_score;
  endclocking
  assert property(@(posedge clk) disable iff(rst==ACTIVE)
    cfg_valid&&!cfg_ready |=> cfg_valid&&$stable({cfg_bit,cfg_last,cfg_count})) else $fatal(1,"[PROTOCOL] stalled cfg changed");
  assert property(@(posedge clk) disable iff(rst==ACTIVE)
    s_valid&&!s_ready |=> s_valid&&$stable({s_re,s_im,s_b_re,s_b_im,s_last})) else $fatal(1,"[PROTOCOL] stalled input changed");
  assert property(@(posedge clk) disable iff(rst==ACTIVE)
    m_valid&&!m_ready |=> m_valid&&$stable({m_last,m_bit,m_index,m_re,m_im,m_phase,m_frequency,m_correction,m_gain}))
    else $fatal(1,"[PROTOCOL] stalled output changed");
  assert property(@(posedge clk) disable iff(rst==ACTIVE)
    gain_valid&&!gain_ready |=> gain_valid&&$stable({gain_a_re,gain_a_im,gain_b_re,gain_b_im,variance_a,variance_b}))
    else $fatal(1,"[PROTOCOL] stalled gain configuration changed");
endinterface

`include "uvm_macros.svh"
package bpsk_rx_pilot_uvm_pkg;
  import uvm_pkg::*;
  localparam int LABEL_BITS=`PILOT_ORDER==8?3:`PILOT_ORDER==4?2:1,ALPHABET=1<<LABEL_BITS;
  `uvm_analysis_imp_decl(_expected)
  `uvm_analysis_imp_decl(_observed)
  typedef enum {CONFIGURE,PARTIAL_CONFIG,FRAME,WARM_FRAME,RESET_DUT,OUTPUT_EVENT,ACQUIRE_EVENT,RESET_EVENT,GAIN_CONFIGURE,CONFIG_EVENT,GAIN_EVENT} item_kind_t;
  typedef struct {longint signed re,im,phase,frequency,gain,correction,index,label,last,truth;} trace_t;
  typedef struct {longint signed delay,frequency,phase,gain,score,confidence;} acquisition_t;
  class pilot_item extends uvm_sequence_item;
    `uvm_object_utils(pilot_item)
    item_kind_t kind;
    int frame_id,symbols,expected_payload_errors;
    int preamble[],wave_re[],wave_im[],wave_b_re[],wave_b_im[],wave_last[],gains[],expected_partial_errors[];
    // Immutable float reference (+FLOAT_SER): decisions of the independent
    // floating receiver on the same pin waveform, its error count and denominator.
    bit float_enabled;
    int float_decisions[],float_expected_errors=-1,float_expected_symbols=-1;
    int actual_config_label,actual_config_count,actual_config_last;
    trace_t golden[],actual;
    acquisition_t acquisition;
    function new(string name="pilot_item");super.new(name);endfunction
  endclass

  class pilot_sequence extends uvm_sequence #(pilot_item);
    `uvm_object_utils(pilot_sequence)
    string directory,scenario;
    pilot_item frames[$];
    int preamble[],symbols,total_frames,gains[];
    function new(string name="pilot_sequence");super.new(name);endfunction
    task load_vectors();
      int fd,count,rc,ntrace,nacq,nwave,expected_frames,original_errors[];
      int wr,wi,wb_re,wb_im,last,frame_id,offset;
      int frame_re[$],frame_im[$],frame_b_re[$],frame_b_im[$],frame_last[$];
      trace_t row;
      acquisition_t acquisition;
      pilot_item frame;
      if(!$value$plusargs("VECTORS=%s",directory)) `uvm_fatal("INPUT","Missing vectors")
      if(!$value$plusargs("SYMBOLS=%d",symbols)||symbols<192) `uvm_fatal("INPUT","Missing valid symbol count")
      if(!$value$plusargs("SCENARIO=%s",scenario)) scenario="stream";
      fd=$fopen({directory,"/preamble.txt"},"r");
      if(!fd||$fscanf(fd,"%d",count)!=1||count!=192) `uvm_fatal("INPUT","Invalid preamble")
      preamble=new[count];
      foreach(preamble[k]) if($fscanf(fd,"%d",preamble[k])!=1||!(preamble[k]>=0&&preamble[k]<ALPHABET)) `uvm_fatal("INPUT","Invalid training bit")
      $fclose(fd);
      fd=$fopen({directory,"/payload_expected.txt"},"r");
      if(!fd||$fscanf(fd,"%d",expected_frames)!=1||expected_frames<1) `uvm_fatal("INPUT","Invalid original payload error metadata")
      original_errors=new[expected_frames];
      foreach(original_errors[k]) if($fscanf(fd,"%d",original_errors[k])!=1||original_errors[k]<0||original_errors[k]>symbols-192) `uvm_fatal("INPUT","Invalid original error count")
      $fclose(fd);
      fd=$fopen({directory,"/rx_trace.txt"},"r");
      if(!fd||$fscanf(fd,"%d",ntrace)!=1||ntrace!=symbols*expected_frames) `uvm_fatal("INPUT","Invalid trace size")
      for(int f=0;f<expected_frames;f++) begin
        frame=pilot_item::type_id::create($sformatf("frame%0d",f));frame.kind=FRAME;frame.frame_id=f;
        frame.symbols=symbols;frame.expected_payload_errors=original_errors[f];frame.golden=new[symbols];
        for(int k=0;k<symbols;k++) begin
          rc=$fscanf(fd,"%d %d %d %d %d %d %d %d %d %d",row.re,row.im,row.phase,row.frequency,row.gain,row.correction,row.index,row.label,row.last,row.truth);
          if(rc!=10||row.last!=longint'(k==symbols-1)||!(row.truth>=0&&row.truth<ALPHABET)||!(row.label>=0&&row.label<ALPHABET)||!(row.index>=0&&row.index<ALPHABET)) `uvm_fatal("INPUT","Malformed fixed trace/truth")
          frame.golden[k]=row;
        end
        frames.push_back(frame);
      end
      $fclose(fd);
      if($test$plusargs("FLOAT_SER")) begin
        int nfloat,ferrors,fsymbols;
        fd=$fopen({directory,"/float_decisions.txt"},"r");
        if(!fd||$fscanf(fd,"%d",nfloat)!=1||nfloat!=symbols*expected_frames) `uvm_fatal("INPUT","Invalid immutable float decision metadata")
        foreach(frames[f]) begin
          frames[f].float_enabled=1;frames[f].float_decisions=new[symbols];
          foreach(frames[f].float_decisions[k]) if($fscanf(fd,"%d",frames[f].float_decisions[k])!=1||!(frames[f].float_decisions[k]>=0&&frames[f].float_decisions[k]<ALPHABET))
            `uvm_fatal("INPUT","Malformed float decision")
        end
        $fclose(fd);
        fd=$fopen({directory,"/float_expected.txt"},"r");
        if(!fd||$fscanf(fd,"%d",count)!=1||count!=expected_frames) `uvm_fatal("INPUT","Invalid immutable float error metadata")
        foreach(frames[f]) begin
          if($fscanf(fd,"%d %d",ferrors,fsymbols)!=2||ferrors<0||fsymbols<0||ferrors>fsymbols) `uvm_fatal("INPUT","Malformed float error/denominator metadata")
          frames[f].float_expected_errors=ferrors;frames[f].float_expected_symbols=fsymbols;
        end
        $fclose(fd);
      end
      fd=$fopen({directory,"/rx_acquire.txt"},"r");
      if(!fd||$fscanf(fd,"%d",nacq)!=1||nacq!=expected_frames) `uvm_fatal("INPUT","Invalid acquisition count")
      for(int f=0;f<nacq;f++) begin
        rc=$fscanf(fd,"%d %d %d %d %d %d",acquisition.delay,acquisition.frequency,acquisition.phase,acquisition.gain,acquisition.score,acquisition.confidence);
        if(rc!=6) `uvm_fatal("INPUT","Malformed acquisition")
        frames[f].acquisition=acquisition;
      end
      $fclose(fd);
      if($test$plusargs("CHECK_RESET_PREFIX")) begin
        int entries,prefix,payload,errors;
        fd=$fopen({directory,"/warm_reset_expected.txt"},"r");
        if(!fd||$fscanf(fd,"%d",entries)!=1||entries!=symbols+1||frames.size()<4) `uvm_fatal("INPUT","Invalid immutable warm-reset prefix metadata")
        frames[3].expected_partial_errors=new[entries];
        for(int k=0;k<entries;k++) begin
          if($fscanf(fd,"%d %d %d",prefix,payload,errors)!=3||prefix!=k||payload!=(k>192?k-192:0)||errors<0||errors>payload)
            `uvm_fatal("INPUT","Malformed warm-reset prefix metadata")
          frames[3].expected_partial_errors[k]=errors;
        end
        $fclose(fd);
      end
      if(`PILOT_SIMO) begin
        int count;
        fd=$fopen({directory,"/gains.txt"},"r");
        if(!fd||$fscanf(fd,"%d",count)!=1||count!=1) `uvm_fatal("INPUT","Invalid SIMO gain configuration")
        gains=new[6];
        foreach(gains[k]) if($fscanf(fd,"%d",gains[k])!=1) `uvm_fatal("INPUT","Malformed SIMO gain tuple")
        $fclose(fd);
        foreach(gains[k]) if(k<4?gains[k]<-131072||gains[k]>131071:gains[k]<1||gains[k]>65535) `uvm_fatal("INPUT","Gain port range mismatch")
      end
      fd=$fopen({directory,"/rx_wave.txt"},"r");
      if(!fd||$fscanf(fd,"%d",nwave)!=1) `uvm_fatal("INPUT","Invalid waveform")
      // Each waveform is terminated by its own input TLAST; channel delay can
      // make frame lengths differ. Dynamic arrays are filled from original rows.
      frame_id=0;offset=0;
      for(int k=0;k<nwave;k++) begin
        if(`PILOT_SIMO) rc=$fscanf(fd,"%d %d %d %d %d",wr,wi,wb_re,wb_im,last);
        else begin rc=$fscanf(fd,"%d %d %d",wr,wi,last);wb_re=0;wb_im=0;end
        if(rc!=(`PILOT_SIMO?5:3)||frame_id>=expected_frames||!(last inside {0,1})) `uvm_fatal("INPUT","Malformed waveform frame")
        frame_re.push_back(wr);frame_im.push_back(wi);frame_b_re.push_back(wb_re);frame_b_im.push_back(wb_im);frame_last.push_back(last);
        offset++;
        if(last) begin
          frames[frame_id].wave_re=new[offset];frames[frame_id].wave_im=new[offset];frames[frame_id].wave_b_re=new[offset];frames[frame_id].wave_b_im=new[offset];frames[frame_id].wave_last=new[offset];
          for(int word=0;word<offset;word++) begin
            frames[frame_id].wave_re[word]=frame_re[word];frames[frame_id].wave_im[word]=frame_im[word];frames[frame_id].wave_b_re[word]=frame_b_re[word];frames[frame_id].wave_b_im[word]=frame_b_im[word];frames[frame_id].wave_last[word]=frame_last[word];
          end
          frame_re.delete();frame_im.delete();frame_b_re.delete();frame_b_im.delete();frame_last.delete();frame_id++;offset=0;
        end
      end
      $fclose(fd);
      if(frame_id!=expected_frames||offset!=0) `uvm_fatal("INPUT","Incomplete waveform")
      total_frames=expected_frames;
    endtask
    task send_control(item_kind_t kind);
      pilot_item item;
      item=pilot_item::type_id::create("control");item.kind=kind;item.preamble=preamble;item.symbols=symbols;item.gains=gains;
      start_item(item);finish_item(item);
    endtask
    task body();
      pilot_item warm;
      load_vectors();
      if(`PILOT_SIMO) send_control(GAIN_CONFIGURE);
      if(scenario=="cfgreset") begin send_control(PARTIAL_CONFIG);send_control(RESET_DUT);if(`PILOT_SIMO) send_control(GAIN_CONFIGURE);end
      send_control(CONFIGURE);
      if(scenario=="midreset") begin
        // Directed reset stress reuses existing noisy case 3 unchanged; no new
        // waveform, noise or payload truth is generated for the warmup.
        warm=pilot_item::type_id::create("warmup");warm.kind=WARM_FRAME;warm.frame_id=3;warm.symbols=symbols;
        warm.expected_partial_errors=frames[3].expected_partial_errors;warm.golden=frames[3].golden;warm.acquisition=frames[3].acquisition;warm.expected_payload_errors=frames[3].expected_payload_errors;
        warm.float_enabled=frames[3].float_enabled;warm.float_decisions=frames[3].float_decisions;warm.float_expected_errors=frames[3].float_expected_errors;warm.float_expected_symbols=frames[3].float_expected_symbols;
        warm.wave_re=frames[3].wave_re;warm.wave_im=frames[3].wave_im;warm.wave_b_re=frames[3].wave_b_re;warm.wave_b_im=frames[3].wave_b_im;warm.wave_last=frames[3].wave_last;
        start_item(warm);finish_item(warm);send_control(RESET_DUT);if(`PILOT_SIMO) send_control(GAIN_CONFIGURE);send_control(CONFIGURE);
      end
      foreach(frames[f]) begin start_item(frames[f]);finish_item(frames[f]);end
    endtask
  endclass

  class pilot_driver extends uvm_driver #(pilot_item);
    `uvm_component_utils(pilot_driver)
    virtual bpsk_rx_uvm_if vif;
    uvm_analysis_port #(pilot_item) expected;
    bit hold_output=0,stall_output=0;
    function new(string name,uvm_component parent);super.new(name,parent);expected=new("expected",this);endfunction
    function void build_phase(uvm_phase phase);
      string scenario;
      if(!uvm_config_db#(virtual bpsk_rx_uvm_if)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing interface")
      if(!$value$plusargs("SCENARIO=%s",scenario)) scenario="stream";
      stall_output=scenario=="stalled"||scenario=="midreset"||scenario=="cfgreset";
    endfunction
    task reset_dut();
      @(negedge vif.clk);vif.gain_valid=0;vif.cfg_valid=0;vif.cfg_last=0;vif.s_valid=0;vif.s_last=0;vif.rst=vif.ACTIVE;hold_output=0;
      repeat(5) @(vif.sample);
      if($isunknown({vif.sample.configured,vif.sample.s_ready,vif.sample.m_valid,vif.sample.error})||
         vif.sample.configured||vif.sample.s_ready||vif.sample.m_valid||vif.sample.error||vif.sample.gain_configured||vif.sample.gain_error) `uvm_fatal("RESET","Unknown/state/handshake survived reset")
      @(negedge vif.clk);vif.rst=!vif.ACTIVE;
    endtask
    task configure(pilot_item item,bit partial);
      int count;
      expected.write(item);count=partial?96:192;
      for(int k=0;k<count;k++) begin
        @(negedge vif.clk);vif.cfg_valid=1;vif.cfg_bit=LABEL_BITS'(item.preamble[k]);vif.cfg_last=!partial&&k==191;vif.cfg_count=12'(item.symbols);
        do @(vif.sample);while(!vif.sample.cfg_ready);
      end
      @(negedge vif.clk);vif.cfg_valid=0;vif.cfg_last=0;
      @(vif.sample);
      if(vif.sample.configured!==!partial||vif.sample.error) `uvm_fatal("CONFIG","Training configuration state mismatch")
    endtask
    task configure_gain(pilot_item item);
      int cycles;
      expected.write(item);
      @(negedge vif.clk);vif.gain_valid=1;
      vif.gain_a_re=18'(item.gains[0]);vif.gain_a_im=18'(item.gains[1]);vif.gain_b_re=18'(item.gains[2]);vif.gain_b_im=18'(item.gains[3]);
      vif.variance_a=16'(item.gains[4]);vif.variance_b=16'(item.gains[5]);
      do @(vif.sample);while(!vif.sample.gain_ready);
      @(negedge vif.clk);vif.gain_valid=0;cycles=0;
      while(!vif.sample.gain_configured) begin
        @(vif.sample);cycles++;
        if(vif.sample.gain_error||cycles>400) `uvm_fatal("CONFIG","SIMO gain configuration failed")
      end
    endtask
    task drive_frame(pilot_item item);
      int count;
      expected.write(item);
      count=item.kind==WARM_FRAME?4200:item.wave_re.size();
      if(count>item.wave_re.size()) `uvm_fatal("INPUT","Warmup exceeds waveform")
      for(int k=0;k<count;k++) begin
        @(negedge vif.clk);vif.s_valid=1;vif.s_re=18'(item.wave_re[k]);vif.s_im=18'(item.wave_im[k]);vif.s_b_re=18'(item.wave_b_re[k]);vif.s_b_im=18'(item.wave_b_im[k]);
        vif.s_last=item.kind==WARM_FRAME?0:1'(item.wave_last[k]);
        do @(vif.sample);while(!vif.sample.s_ready);
      end
      @(negedge vif.clk);vif.s_valid=0;vif.s_last=0;
      if(item.kind==WARM_FRAME) begin
        hold_output=1;repeat(30) @(vif.sample);
        if(!vif.sample.m_valid) `uvm_fatal("RESET","Midreset never had a pending output")
      end
    endtask
    task run_phase(uvm_phase phase);
      fork
        begin
          int cycles=0;
          forever begin
            @(negedge vif.clk);cycles++;
            vif.m_ready=(vif.rst==vif.ACTIVE)||(!hold_output&&(!stall_output||((cycles%7)!=0&&(cycles%31)<25)));
          end
        end
      join_none
      reset_dut();
      forever begin
        pilot_item item;
        seq_item_port.get_next_item(item);
        case(item.kind)
          GAIN_CONFIGURE:configure_gain(item);
          CONFIGURE:configure(item,0);
          PARTIAL_CONFIG:configure(item,1);
          RESET_DUT:reset_dut();
          FRAME,WARM_FRAME:drive_frame(item);
          default:`uvm_fatal("CONFIG","Unexpected source item")
        endcase
        seq_item_port.item_done();
      end
    endtask
  endclass

  class pilot_monitor extends uvm_monitor;
    `uvm_component_utils(pilot_monitor)
    virtual bpsk_rx_uvm_if vif;
    uvm_analysis_port #(pilot_item) observed;
    int stalls=0,inputs=0,configurations=0,pending_resets=0,gain_configs=0,cfg_max=0,label_max=0,index_max=0;
    function new(string name,uvm_component parent);super.new(name,parent);observed=new("observed",this);endfunction
    function void build_phase(uvm_phase phase);
      if(!uvm_config_db#(virtual bpsk_rx_uvm_if)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing monitor interface")
    endfunction
    task run_phase(uvm_phase phase);
      bit was_reset=0;
      forever begin
        pilot_item item;
        @(vif.sample);
        if($isunknown(vif.sample.rst)) `uvm_fatal("PROTOCOL","Unknown reset control")
        if(vif.sample.rst==vif.ACTIVE) begin
          if(!was_reset) begin
            item=pilot_item::type_id::create("reset_observed");item.kind=RESET_EVENT;observed.write(item);
            if(vif.sample.m_valid) pending_resets++;
          end
          was_reset=1;
        end else begin
          was_reset=0;
          if($isunknown({vif.sample.cfg_valid,vif.sample.cfg_ready,vif.sample.configured,vif.sample.error,
                         vif.sample.s_valid,vif.sample.s_ready,vif.sample.m_valid,vif.sample.m_ready,vif.sample.acquisition_valid,
                         vif.sample.gain_valid,vif.sample.gain_ready,vif.sample.gain_configured,vif.sample.gain_error,vif.sample.saturated}))
            `uvm_fatal("PROTOCOL","Unknown active handshake/error controls")
          if(vif.sample.error||vif.sample.gain_error||vif.sample.saturated) `uvm_fatal("PROTOCOL","Unexpected DUT/combiner error or saturation")
          if(vif.sample.cfg_valid&&$isunknown({vif.sample.cfg_bit,vif.sample.cfg_last,vif.sample.cfg_count})) `uvm_fatal("NUMERIC","Unknown valid training label/count")
          if(vif.sample.s_valid&&$isunknown({vif.sample.s_re,vif.sample.s_im,vif.sample.s_b_re,vif.sample.s_b_im,vif.sample.s_last})) `uvm_fatal("NUMERIC","Unknown valid branch samples")
          if(vif.sample.gain_valid&&$isunknown({vif.sample.gain_a_re,vif.sample.gain_a_im,vif.sample.gain_b_re,vif.sample.gain_b_im,vif.sample.variance_a,vif.sample.variance_b})) `uvm_fatal("NUMERIC","Unknown valid gain tuple")
          if(vif.sample.cfg_valid&&vif.sample.cfg_ready) begin
            configurations++;if(int'(vif.sample.cfg_bit)>cfg_max) cfg_max=int'(vif.sample.cfg_bit);
            item=pilot_item::type_id::create("config_observed");item.kind=CONFIG_EVENT;
            item.actual_config_label=int'(vif.sample.cfg_bit);item.actual_config_count=int'(vif.sample.cfg_count);item.actual_config_last=int'(vif.sample.cfg_last);observed.write(item);
          end
          if(vif.sample.gain_valid&&vif.sample.gain_ready) begin
            gain_configs++;item=pilot_item::type_id::create("gain_observed");item.kind=GAIN_EVENT;item.gains=new[6];
            item.gains[0]=$signed(vif.sample.gain_a_re);item.gains[1]=$signed(vif.sample.gain_a_im);item.gains[2]=$signed(vif.sample.gain_b_re);item.gains[3]=$signed(vif.sample.gain_b_im);
            item.gains[4]=int'(vif.sample.variance_a);item.gains[5]=int'(vif.sample.variance_b);observed.write(item);
          end
          if(vif.sample.s_valid&&vif.sample.s_ready) inputs++;
          if(vif.sample.m_valid&&!vif.sample.m_ready) stalls++;
          if(vif.sample.acquisition_valid) begin
            if($isunknown({vif.sample.acquisition_delay,vif.sample.acquisition_frequency,vif.sample.acquisition_phase,
                           vif.sample.acquisition_gain,vif.sample.acquisition_score,vif.sample.acquisition_confidence}))
              `uvm_fatal("NUMERIC","Unknown valid acquisition tuple")
            item=pilot_item::type_id::create("acquisition_observed");item.kind=ACQUIRE_EVENT;
            item.acquisition.delay=$signed(vif.sample.acquisition_delay);item.acquisition.frequency=$signed(vif.sample.acquisition_frequency);
            item.acquisition.phase=$signed(vif.sample.acquisition_phase);item.acquisition.gain=longint'(vif.sample.acquisition_gain);
            item.acquisition.score=longint'(vif.sample.acquisition_score);item.acquisition.confidence=longint'(vif.sample.acquisition_confidence);
            observed.write(item);
          end
          if(vif.sample.m_valid) begin
            if($isunknown({vif.sample.m_re,vif.sample.m_im,vif.sample.m_phase,vif.sample.m_frequency,vif.sample.m_gain,
                           vif.sample.m_correction,vif.sample.m_index,vif.sample.m_bit,vif.sample.m_last}))
              `uvm_fatal("NUMERIC","Unknown valid output tuple, including backpressure")
          end
          if(vif.sample.m_valid&&vif.sample.m_ready) begin
            item=pilot_item::type_id::create("output_observed");item.kind=OUTPUT_EVENT;
            item.actual.re=$signed(vif.sample.m_re);item.actual.im=$signed(vif.sample.m_im);
            item.actual.phase=$signed(vif.sample.m_phase);item.actual.frequency=$signed(vif.sample.m_frequency);
            item.actual.gain=longint'(vif.sample.m_gain);item.actual.correction=$signed(vif.sample.m_correction);
            item.actual.index=longint'(vif.sample.m_index);item.actual.label=longint'(vif.sample.m_bit);
            if(int'(vif.sample.m_bit)>label_max) label_max=int'(vif.sample.m_bit);if(int'(vif.sample.m_index)>index_max) index_max=int'(vif.sample.m_index);item.actual.last=longint'(vif.sample.m_last);
            observed.write(item);
          end
        end
      end
    endtask
  endclass

  class pilot_scoreboard extends uvm_scoreboard;
    `uvm_component_utils(pilot_scoreboard)
    uvm_analysis_imp_expected #(pilot_item,pilot_scoreboard) expected;
    uvm_analysis_imp_observed #(pilot_item,pilot_scoreboard) observed;
    pilot_item frames[$],acquisitions[$],configs[$],gains[$];
    int config_row=0;
    int row_index=0,checked=0,expected_symbols=0,discarded=0,resets=0,acquired=0,completed=0;
    int normal_frames=0,payload_errors=0,payload_symbols=0,frame_errors=0,frame_payload=0;
    int discarded_partial_payload=0;
    int discarded_partial_errors=0;
    int frame_float_errors=0,float_frames=0,float_errors=0,float_symbols=0,float_rtl_errors=0;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      expected=new("expected",this);observed=new("observed",this);
    endfunction
    function void write_expected(pilot_item item);
      if(item.kind==CONFIGURE||item.kind==PARTIAL_CONFIG) begin configs.push_back(item);return;end
      if(item.kind==GAIN_CONFIGURE) begin gains.push_back(item);return;end
      frames.push_back(item);acquisitions.push_back(item);expected_symbols+=item.symbols;
      if(item.kind==FRAME) normal_frames++;
    endfunction
    function void write_observed(pilot_item actual);
      pilot_item golden;
      trace_t e,a;
      if(actual.kind==RESET_EVENT) begin
        if(frames.size()>0) begin
          golden=frames[0];
          if(frame_payload!=(row_index>192?row_index-192:0)) `uvm_fatal("SER","Reset partial payload denominator mismatch")
          if(golden.expected_partial_errors.size()>0&&frame_errors!=golden.expected_partial_errors[row_index])
            `uvm_fatal("SER","Reset actual partial errors differ from immutable original prefix")
        end
        foreach(frames[k]) discarded+=frames[k].symbols-(k==0?row_index:0);
        discarded_partial_payload+=frame_payload;
        discarded_partial_errors+=frame_errors;
        frames.delete();acquisitions.delete();configs.delete();gains.delete();config_row=0;row_index=0;frame_errors=0;frame_payload=0;frame_float_errors=0;resets++;
      end else if(actual.kind==CONFIG_EVENT) begin
        if(configs.size()==0) `uvm_fatal("COUNT","Unexpected accepted training label")
        golden=configs[0];
        if(actual.actual_config_label!=golden.preamble[config_row]||actual.actual_config_count!=golden.symbols||actual.actual_config_last!=int'(golden.kind==CONFIGURE&&config_row==191))
          `uvm_fatal("NUMERIC","Accepted full-width training configuration differs from public sequence")
        config_row++;
        if(config_row==(golden.kind==PARTIAL_CONFIG?96:192)) begin golden=configs.pop_front();config_row=0;end
      end else if(actual.kind==GAIN_EVENT) begin
        if(gains.size()==0) `uvm_fatal("COUNT","Unexpected accepted gain tuple")
        golden=gains.pop_front();
        if(actual.gains!=golden.gains) `uvm_fatal("NUMERIC","Accepted SIMO gain tuple mismatch")
      end else if(actual.kind==ACQUIRE_EVENT) begin
        if(acquisitions.size()==0) `uvm_fatal("COUNT","Unexpected acquisition")
        golden=acquisitions.pop_front();
        if(actual.acquisition!==golden.acquisition) `uvm_fatal("NUMERIC","Acquisition tuple mismatch")
        acquired++;
      end else if(actual.kind==OUTPUT_EVENT) begin
        if(frames.size()==0) `uvm_fatal("COUNT","Unexpected accepted output")
        golden=frames[0];e=golden.golden[row_index];a=actual.actual;
        if($test$plusargs("INJECT_MISMATCH")&&golden.frame_id==0&&row_index==200) e.re++;
        if(a.re!==e.re||a.im!==e.im||a.phase!==e.phase||a.frequency!==e.frequency||a.gain!==e.gain||a.correction!==e.correction||a.index!==e.index||a.label!==e.label||a.last!==e.last)
          `uvm_fatal("NUMERIC",$sformatf("Accepted output row=%0d frame=%0d label=%0d/%0d I=%0d/%0d",row_index,golden.frame_id,a.label,e.label,a.re,e.re))
        if(row_index>=192) begin
          frame_payload++;frame_errors+=a.label!=e.truth;
          if(golden.float_enabled) frame_float_errors+=golden.float_decisions[row_index]!=e.truth;
        end
        checked++;row_index++;
        if(a.last) begin
          if(golden.kind!=FRAME||row_index!=golden.symbols||frame_payload!=golden.symbols-192) `uvm_fatal("COUNT","Incomplete/unsolicited frame completion")
          // This count is read from immutable ORIGINAL model metadata, not
          // recomputed from mutable trace truth. The separate truth negative
          // changes only column9 and must fail here while column7 still matches.
          if(frame_errors!=golden.expected_payload_errors) `uvm_fatal("SER",$sformatf("Original payload error count mismatch: %0d != %0d",frame_errors,golden.expected_payload_errors))
          $display("UVM PILOT SER frame=%0d errors=%0d symbols=%0d",golden.frame_id,frame_errors,frame_payload);
          if(golden.float_enabled) begin
            // Same accepted payload interval and same truth rows for both receivers.
            if(frame_payload!=golden.float_expected_symbols)
              `uvm_fatal("FLOAT_SER",$sformatf("Float denominator differs from actual payload interval: %0d != %0d",golden.float_expected_symbols,frame_payload))
            if(frame_float_errors!=golden.float_expected_errors)
              `uvm_fatal("FLOAT_SER",$sformatf("Float decisions give %0d errors, immutable metadata %0d",frame_float_errors,golden.float_expected_errors))
            $display("UVM PILOT FLOAT SER frame=%0d rtl_errors=%0d float_errors=%0d delta=%0d symbols=%0d",golden.frame_id,frame_errors,frame_float_errors,frame_errors-frame_float_errors,frame_payload);
            float_frames++;float_errors+=frame_float_errors;float_rtl_errors+=frame_errors;float_symbols+=frame_payload;
          end
          payload_errors+=frame_errors;payload_symbols+=frame_payload;completed++;
          golden=frames.pop_front();row_index=0;frame_errors=0;frame_payload=0;frame_float_errors=0;
        end
      end else `uvm_fatal("PROTOCOL","Unknown observed event")
    endfunction
    function void check_phase(uvm_phase phase);
      if(frames.size()!=0||acquisitions.size()!=0||configs.size()!=0||gains.size()!=0||config_row!=0||row_index!=0||completed!=normal_frames||normal_frames<1||checked+discarded!=expected_symbols)
        `uvm_error("COUNT","Expected queues/frame accounting did not drain")
      if($test$plusargs("FLOAT_SER")&&(float_frames!=completed||float_symbols!=payload_symbols||float_rtl_errors!=payload_errors))
        `uvm_error("FLOAT_SER","Float comparison did not cover every completed payload interval")
    endfunction
    function void report_phase(uvm_phase phase);
      if($test$plusargs("FLOAT_SER"))
        `uvm_info("RESULT",$sformatf("UVM PILOT FLOAT SUMMARY frames=%0d rtl_errors=%0d float_errors=%0d symbols=%0d",float_frames,float_rtl_errors,float_errors,float_symbols),UVM_LOW)
      `uvm_info("RESULT",$sformatf("UVM BPSK PILOT checked=%0d frames=%0d acquisitions=%0d errors=%0d payload=%0d discarded=%0d resets=%0d partial_payload_discarded=%0d partial_errors_discarded=%0d",checked,completed,acquired,payload_errors,payload_symbols,discarded,resets,discarded_partial_payload,discarded_partial_errors),UVM_LOW)
    endfunction
  endclass

  class pilot_env extends uvm_env;
    `uvm_component_utils(pilot_env)
    uvm_sequencer #(pilot_item) sequencer;
    pilot_driver driver;pilot_monitor monitor;pilot_scoreboard scoreboard;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      sequencer=new("sequencer",this);driver=pilot_driver::type_id::create("driver",this);
      monitor=pilot_monitor::type_id::create("monitor",this);scoreboard=pilot_scoreboard::type_id::create("scoreboard",this);
    endfunction
    function void connect_phase(uvm_phase phase);
      driver.seq_item_port.connect(sequencer.seq_item_export);
      driver.expected.connect(scoreboard.expected);monitor.observed.connect(scoreboard.observed);
    endfunction
  endclass
  class pilot_test extends uvm_test;
    `uvm_component_utils(pilot_test)
    pilot_env env;
    string scenario;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      env=pilot_env::type_id::create("env",this);
      if(!$value$plusargs("SCENARIO=%s",scenario)) scenario="stream";
    endfunction
    task run_phase(uvm_phase phase);
      pilot_sequence sequence_instance;
      phase.raise_objection(this);
      sequence_instance=pilot_sequence::type_id::create("vectors");sequence_instance.start(env.sequencer);
      wait(env.scoreboard.completed==sequence_instance.total_frames);
      repeat(100) @(env.driver.vif.sample);
      phase.drop_objection(this);
    endtask
    function void check_phase(uvm_phase phase);
      int expected_acquisitions,expected_cfg;
      expected_acquisitions=env.scoreboard.normal_frames+(scenario=="midreset"?1:0);
      expected_cfg=scenario=="midreset"?384:scenario=="cfgreset"?288:192;
      if(env.scoreboard.acquired!=expected_acquisitions||env.monitor.configurations!=expected_cfg)
        `uvm_error("COUNT","Acquisition/config handshake count mismatch")
      if(scenario!="stream"&&env.monitor.stalls<5) `uvm_error("STALL","Output backpressure was not observed")
      if((scenario=="cfgreset"||scenario=="midreset")&&env.scoreboard.resets<2) `uvm_error("RESET","Reset replay not exercised")
      if(scenario=="midreset"&&(env.scoreboard.discarded<1||env.monitor.pending_resets<1||env.scoreboard.discarded_partial_payload<1||(!($test$plusargs("CHECK_RESET_PREFIX"))&&env.scoreboard.discarded_partial_errors<1)))
        `uvm_error("RESET","Reset did not discard pending output/expected queue/nonzero partial SER counters")
    endfunction
    function void report_phase(uvm_phase phase);
      `uvm_info("COVER",$sformatf("UVM PILOT HANDSHAKES cfg=%0d input=%0d stalls=%0d pending_resets=%0d",env.monitor.configurations,env.monitor.inputs,env.monitor.stalls,env.monitor.pending_resets),UVM_LOW)
      `uvm_info("PROFILE",$sformatf("UVM PILOT PROFILE label_bits=%0d index_bits=%0d gaincfg=%0d cfg_max=%0d label_max=%0d index_max=%0d",env.driver.vif.LABEL_BITS,env.driver.vif.INDEX_BITS,env.monitor.gain_configs,env.monitor.cfg_max,env.monitor.label_max,env.monitor.index_max),UVM_LOW)
    endfunction
  endclass
endpackage

module bpsk_rx_uvm_top;
  import uvm_pkg::*;
  import bpsk_rx_pilot_uvm_pkg::*;
  parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
  logic clk=0;always #5 clk=!clk;
  bpsk_rx_uvm_if bus(clk);
  generate
  if(`PILOT_SIMO) begin:g_simo
    simo_rx #(.RESET_ACTIVE(bus.ACTIVE),.TABLE_DIR(TABLE_DIR)) dut(
      .clk(clk),.rst(bus.rst),.gain_valid(bus.gain_valid),.gain_a_re(bus.gain_a_re),.gain_a_im(bus.gain_a_im),.gain_b_re(bus.gain_b_re),.gain_b_im(bus.gain_b_im),
      .variance_a(bus.variance_a),.variance_b(bus.variance_b),.gain_ready(bus.gain_ready),.gain_configured(bus.gain_configured),.gain_error(bus.gain_error),.saturated(bus.saturated),
      .cfg_valid(bus.cfg_valid),.cfg_bit(bus.cfg_bit),.cfg_last(bus.cfg_last),.cfg_count(bus.cfg_count),.cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
      .s_valid(bus.s_valid),.s_last(bus.s_last),.s_a_re(bus.s_re),.s_a_im(bus.s_im),.s_b_re(bus.s_b_re),.s_b_im(bus.s_b_im),.s_ready(bus.s_ready),
      .m_valid(bus.m_valid),.m_last(bus.m_last),.m_bit(bus.m_bit),.m_index(bus.m_index),.m_ready(bus.m_ready),.m_re(bus.m_re),.m_im(bus.m_im),
      .m_phase(bus.m_phase),.m_frequency(bus.m_frequency),.m_correction(bus.m_correction),.m_gain(bus.m_gain),
      .acquisition_valid(bus.acquisition_valid),.acquisition_confidence(bus.acquisition_confidence),.acquisition_delay(bus.acquisition_delay),.acquisition_frequency(bus.acquisition_frequency),
      .acquisition_phase(bus.acquisition_phase),.acquisition_gain(bus.acquisition_gain),.acquisition_score(bus.acquisition_score));
  end else begin:g_single
  bpsk_rx #(.RESET_ACTIVE(bus.ACTIVE),.TABLE_DIR(TABLE_DIR),.ORDER(`PILOT_ORDER),.AMPLITUDE(`PILOT_AMPLITUDE),.DIFFERENTIAL(`PILOT_DIFFERENTIAL),.FEEDFORWARD(`PILOT_FEEDFORWARD),.TIMING_LOOP(`PILOT_TIMING_LOOP)) dut(
    .clk(clk),.rst(bus.rst),.cfg_valid(bus.cfg_valid),.cfg_bit(bus.cfg_bit),.cfg_last(bus.cfg_last),.cfg_count(bus.cfg_count),
    .cfg_ready(bus.cfg_ready),.configured(bus.configured),.error(bus.error),
    .s_valid(bus.s_valid),.s_last(bus.s_last),.s_re(bus.s_re),.s_im(bus.s_im),.s_ready(bus.s_ready),
    .m_valid(bus.m_valid),.m_last(bus.m_last),.m_bit(bus.m_bit),.m_index(bus.m_index),.m_ready(bus.m_ready),
    .m_re(bus.m_re),.m_im(bus.m_im),.m_phase(bus.m_phase),.m_frequency(bus.m_frequency),.m_correction(bus.m_correction),.m_gain(bus.m_gain),
    .acquisition_valid(bus.acquisition_valid),.acquisition_confidence(bus.acquisition_confidence),.acquisition_delay(bus.acquisition_delay),
    .acquisition_frequency(bus.acquisition_frequency),.acquisition_phase(bus.acquisition_phase),.acquisition_gain(bus.acquisition_gain),.acquisition_score(bus.acquisition_score));
    assign bus.gain_ready=0;assign bus.gain_configured=0;assign bus.gain_error=0;assign bus.saturated=0;
  end
  endgenerate
  initial begin uvm_config_db#(virtual bpsk_rx_uvm_if)::set(null,"*","vif",bus);run_test("pilot_test");end
  // Fault only a live DUT/output-sink handshake signal; neither the expected
  // sequence nor monitor receives fabricated decoded data.
  initial if($test$plusargs("INJECT_M_VALID_X")||$test$plusargs("INJECT_M_READY_X")) begin
    wait(bus.rst!=bus.ACTIVE);wait(bus.m_valid===1'b1);@(negedge clk);
    if(bus.m_valid!==1'b1) `uvm_fatal("PROTOCOL","Control-X injection missed live output")
    if($test$plusargs("INJECT_M_VALID_X")) force bus.m_valid=1'bx;
    else force bus.m_ready=1'bx;
  end
  logic [LABEL_BITS-1:0] corrupt_label;
  initial if($test$plusargs("INJECT_LABEL_HIGH_BIT")) begin
    wait(bus.rst!=bus.ACTIVE);wait(bus.m_valid===1'b1);@(negedge clk);
    corrupt_label=bus.m_bit^(LABEL_BITS'(1)<<(LABEL_BITS-1));force bus.m_bit=corrupt_label;
  end
  initial if($test$plusargs("INJECT_GAIN_READY_X")) begin
    if(!`PILOT_SIMO) `uvm_fatal("INPUT","Gain ready control not applicable to single-branch receiver")
    wait(bus.rst!=bus.ACTIVE);wait(bus.gain_valid===1'b1);@(negedge clk);force bus.gain_ready=1'bx;
  end
  initial begin #20000000;`uvm_fatal("TIMEOUT","BPSK UVM pilot did not drain") end
endmodule
