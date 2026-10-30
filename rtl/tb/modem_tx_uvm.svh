// Shared streaming TX UVM: labels and waveform geometry are set by the wrapper.
// Source changes on negedge; pins are sampled #1step before the active edge.
`timescale 1ns/1ps
`include "uvm_macros.svh"
interface `TX_INTERFACE(input logic clk);
  import uvm_pkg::*;
`ifdef RTL_RESET_LOW
  localparam bit ACTIVE=0;
`else
  localparam bit ACTIVE=1;
`endif
  logic rst=ACTIVE,s_valid=0,s_last=0,m_ready=1;
  logic [`TX_LABEL_BITS-1:0] s_bit=0;
  wire s_ready,m_valid,m_last;
  wire signed [17:0] m_re,m_im;
  clocking sample @(posedge clk);
    default input #1step;
    input rst,s_valid,s_ready,s_bit,s_last,m_valid,m_ready,m_last,m_re,m_im;
  endclocking
  assert property(@(posedge clk) disable iff(rst==ACTIVE)
    s_valid&&!s_ready |=> s_valid&&$stable({s_bit,s_last}))
    else `uvm_fatal("STALL","Held input changed")
  assert property(@(posedge clk) disable iff(rst==ACTIVE)
    m_valid&&!m_ready |=> m_valid&&$stable({m_re,m_im,m_last}))
    else `uvm_fatal("STALL","Held output changed")
endinterface

package `TX_PACKAGE;
  import uvm_pkg::*;
  `uvm_analysis_imp_decl(_tx_expected)
  `uvm_analysis_imp_decl(_tx_observed)
  typedef enum {FRAME,WARM_PARTIAL,WARM_LAST,RESET_DUT,INPUT_EVENT,OUTPUT_EVENT,RESET_EVENT} tx_kind_t;
  typedef struct {int re,im,last;} tx_sample_t;
  class tx_item extends uvm_sequence_item;
    `uvm_object_utils(tx_item)
    tx_kind_t kind;
    int frame_id,bits[],bit_last[],observed_bit,observed_last;
    bit pending;
    tx_sample_t golden[],actual;
    function new(string name="tx_item");super.new(name);endfunction
  endclass

  class tx_sequence extends uvm_sequence #(tx_item);
    `uvm_object_utils(tx_sequence)
    tx_item frames[$];
    int normal_frames;
    string directory,scenario;
    function new(string name="tx_sequence");super.new(name);endfunction
    task load_vectors();
      int fd,n,bit_value,last,rc,frame_bits[$],frame_lasts[$],frame_id;
      tx_sample_t sample_value;
      tx_item frame;
      if(!$value$plusargs("VECTORS=%s",directory)) `uvm_fatal("INPUT","Missing TX vectors")
      if(!$value$plusargs("SCENARIO=%s",scenario)) scenario="stream";
      if(!(scenario inside {"stream","gaps","stalled","midreset","outreset"})) `uvm_fatal("INPUT","Invalid TX scenario; transmitter has no config ports")
      fd=$fopen({directory,`TX_INPUT_FILE},"r");
      if(!fd||$fscanf(fd,"%d",n)!=1||n<1) `uvm_fatal("INPUT","Invalid label vector header")
      for(int k=0;k<n;k++) begin
        if($fscanf(fd,"%d %d",bit_value,last)!=2||!(bit_value inside {[0:(1<<`TX_LABEL_BITS)-1]})||!(last inside {0,1})) `uvm_fatal("INPUT","Invalid TX input row")
        frame_bits.push_back(bit_value);frame_lasts.push_back(last);
        if(last) begin
          frame=tx_item::type_id::create($sformatf("frame%0d",frames.size()));frame.kind=FRAME;frame.frame_id=frames.size();
          frame.bits=new[frame_bits.size()];frame.bit_last=new[frame_lasts.size()];
          foreach(frame.bits[j]) begin frame.bits[j]=frame_bits[j];frame.bit_last[j]=frame_lasts[j];end
          frames.push_back(frame);frame_bits.delete();frame_lasts.delete();
        end
      end
      $fclose(fd);
      if(frame_bits.size()!=0||frames.size()!=5) `uvm_fatal("INPUT","Incomplete TX input frames")
      fd=$fopen({directory,`TX_OUTPUT_FILE},"r");
      if(!fd||$fscanf(fd,"%d",n)!=1) `uvm_fatal("INPUT","Invalid TX reference header")
      rc=0;
      foreach(frames[f]) begin
        frame=frames[f];frame.golden=new[8*frame.bits.size()+`TX_TAIL];
        foreach(frame.golden[k]) begin
          if($fscanf(fd,"%d %d %d",sample_value.re,sample_value.im,sample_value.last)!=3||sample_value.last!=int'(k==frame.golden.size()-1))
            `uvm_fatal("INPUT","Malformed TX waveform/TLAST reference")
          frame.golden[k]=sample_value;rc++;
        end
      end
      $fclose(fd);
      if(rc!=n) `uvm_fatal("INPUT","TX reference count differs from independent waveform geometry")
      normal_frames=frames.size();
    endtask
    task body();
      tx_item warm,reset_item;
      load_vectors();
      if(scenario=="midreset"||scenario=="outreset") begin
        warm=tx_item::type_id::create("reset_warmup");
        warm.kind=scenario=="midreset"?WARM_PARTIAL:WARM_LAST;
        warm.frame_id=scenario=="midreset"?4:2;
        warm.bits=frames[warm.frame_id].bits;warm.bit_last=frames[warm.frame_id].bit_last;warm.golden=frames[warm.frame_id].golden;
        start_item(warm);finish_item(warm);
        reset_item=tx_item::type_id::create("reset");reset_item.kind=RESET_DUT;
        start_item(reset_item);finish_item(reset_item);
      end
      foreach(frames[f]) begin start_item(frames[f]);finish_item(frames[f]);end
    endtask
  endclass

  class tx_driver extends uvm_driver #(tx_item);
    `uvm_component_utils(tx_driver)
    virtual `TX_INTERFACE vif;
    uvm_analysis_port #(tx_item) expected;
    bit hold_output=0,hold_last=0;
    string scenario;
    function new(string name,uvm_component parent);super.new(name,parent);expected=new("expected",this);endfunction
    function void build_phase(uvm_phase phase);
      if(!uvm_config_db#(virtual `TX_INTERFACE)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing TX interface")
      if(!$value$plusargs("SCENARIO=%s",scenario)) scenario="stream";
    endfunction
    task reset_dut();
      @(negedge vif.clk);vif.s_valid=0;vif.s_last=0;vif.rst=vif.ACTIVE;hold_output=0;hold_last=0;
      repeat(5) @(vif.sample);
      if($isunknown({vif.sample.s_ready,vif.sample.m_valid})||vif.sample.s_ready||vif.sample.m_valid) `uvm_fatal("RESET","TX handshake survived reset fence")
      @(negedge vif.clk);vif.rst=!vif.ACTIVE;
    endtask
    task drive_frame(tx_item item);
      int count;
      expected.write(item);count=item.kind==WARM_PARTIAL?16:item.bits.size();
      if(item.kind==WARM_LAST) hold_last=1;
      for(int k=0;k<count;k++) begin
        @(negedge vif.clk);vif.s_valid=1;vif.s_bit=`TX_LABEL_BITS'(item.bits[k]);
        vif.s_last=item.kind==WARM_PARTIAL?0:1'(item.bit_last[k]);
        do @(vif.sample);while(!vif.sample.s_ready);
        if(scenario=="gaps"&&k%17==8) begin
          @(negedge vif.clk);vif.s_valid=0;
          do @(vif.sample);while(!vif.sample.s_ready);
          repeat(3) @(vif.sample);
        end
      end
      @(negedge vif.clk);vif.s_valid=0;vif.s_last=0;
      if(item.kind==WARM_PARTIAL) begin
        hold_output=1;
        do @(vif.sample);while(!(vif.sample.m_valid&&!vif.sample.m_ready));
        repeat(5) @(vif.sample);
      end
      if(item.kind==WARM_LAST) begin
        do @(vif.sample);while(!(vif.sample.m_valid&&vif.sample.m_last&&!vif.sample.m_ready));
        repeat(5) @(vif.sample);
      end
    endtask
    task run_phase(uvm_phase phase);
      fork
        begin
          int cycles=0;
          forever begin
            @(negedge vif.clk);cycles++;
            vif.m_ready=(vif.rst==vif.ACTIVE)||(!hold_output&&!(hold_last&&vif.m_valid&&vif.m_last)&&
                        (scenario!="stalled"||((cycles%7)!=0&&(cycles%31)<25)));
          end
        end
      join_none
      reset_dut();
      forever begin
        tx_item item;seq_item_port.get_next_item(item);
        case(item.kind)
          FRAME,WARM_PARTIAL,WARM_LAST:drive_frame(item);
          RESET_DUT:reset_dut();
          default:`uvm_fatal("CONFIG","Unexpected TX sequence item")
        endcase
        seq_item_port.item_done();
      end
    endtask
  endclass

  class tx_monitor extends uvm_monitor;
    `uvm_component_utils(tx_monitor)
    virtual `TX_INTERFACE vif;
    uvm_analysis_port #(tx_item) observed;
    int inputs=0,outputs=0,input_stalls=0,output_stalls=0,pending_resets=0,input_gaps=0;
    longint unsigned labels_seen=0;
    function new(string name,uvm_component parent);super.new(name,parent);observed=new("observed",this);endfunction
    function void build_phase(uvm_phase phase);
      if(!uvm_config_db#(virtual `TX_INTERFACE)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing TX monitor interface")
    endfunction
    task run_phase(uvm_phase phase);
      bit was_reset=0,input_held=0,output_held=0,input_frame_open=0;
      logic [`TX_LABEL_BITS-1:0] held_bit;
      logic held_input_last,held_output_last;
      logic signed [17:0] held_re,held_im;
      forever begin
        tx_item item;@(vif.sample);
        if($isunknown(vif.sample.rst)) `uvm_fatal("PROTOCOL","Unknown TX reset control")
        if(vif.sample.rst==vif.ACTIVE) begin
          if(!was_reset) begin
            item=tx_item::type_id::create("reset_observed");item.kind=RESET_EVENT;item.pending=vif.sample.m_valid===1'b1;
            observed.write(item);if(item.pending) pending_resets++;
          end
          was_reset=1;input_held=0;output_held=0;input_frame_open=0;
        end else begin
          was_reset=0;
          if(input_held&&(vif.sample.s_valid!==1'b1||vif.sample.s_bit!==held_bit||vif.sample.s_last!==held_input_last))
            `uvm_fatal("STALL","Observed held source tuple changed")
          if(output_held&&(vif.sample.m_valid!==1'b1||vif.sample.m_re!==held_re||vif.sample.m_im!==held_im||vif.sample.m_last!==held_output_last))
            `uvm_fatal("STALL","Observed held sink tuple changed")
          if($isunknown({vif.sample.s_valid,vif.sample.s_ready,vif.sample.m_valid,vif.sample.m_ready})) `uvm_fatal("PROTOCOL","Unknown active TX handshake control")
          if(vif.sample.s_valid&&$isunknown({vif.sample.s_bit,vif.sample.s_last})) `uvm_fatal("NUMERIC","Unknown valid TX input data")
          if(vif.sample.m_valid&&$isunknown({vif.sample.m_re,vif.sample.m_im,vif.sample.m_last})) `uvm_fatal("NUMERIC","Unknown valid TX output data, including backpressure")
          if(vif.sample.s_valid&&!vif.sample.s_ready) input_stalls++;
          if(vif.sample.m_valid&&!vif.sample.m_ready) output_stalls++;
          if(input_frame_open&&!vif.sample.s_valid&&vif.sample.s_ready) input_gaps++;
          input_held=vif.sample.s_valid&&!vif.sample.s_ready;
          output_held=vif.sample.m_valid&&!vif.sample.m_ready;
          held_bit=vif.sample.s_bit;held_input_last=vif.sample.s_last;
          held_re=vif.sample.m_re;held_im=vif.sample.m_im;held_output_last=vif.sample.m_last;
          if(vif.sample.s_valid&&vif.sample.s_ready) begin
            item=tx_item::type_id::create("input_observed");item.kind=INPUT_EVENT;item.observed_bit=int'(vif.sample.s_bit);item.observed_last=int'(vif.sample.s_last);
            inputs++;labels_seen|=64'd1<<item.observed_bit;input_frame_open=!item.observed_last;observed.write(item);
          end
          if(vif.sample.m_valid&&vif.sample.m_ready) begin
            item=tx_item::type_id::create("output_observed");item.kind=OUTPUT_EVENT;
            item.actual.re=$signed(vif.sample.m_re);item.actual.im=$signed(vif.sample.m_im);item.actual.last=int'(vif.sample.m_last);
            outputs++;observed.write(item);
          end
        end
      end
    endtask
  endclass

  class tx_scoreboard extends uvm_scoreboard;
    `uvm_component_utils(tx_scoreboard)
    uvm_analysis_imp_tx_expected #(tx_item,tx_scoreboard) expected;
    uvm_analysis_imp_tx_observed #(tx_item,tx_scoreboard) observed;
    tx_item output_frames[$],input_frames[$];
    int input_index=0,output_index=0,checked=0,inputs_checked=0,completed=0,normal_frames=0;
    int expected_outputs=0,expected_inputs=0,discarded_outputs=0,discarded_inputs=0,resets=0,before_reset=0;
    int reset_pending=0,held_last_resets=0;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);expected=new("expected",this);observed=new("observed",this);endfunction
    function void write_tx_expected(tx_item item);
      output_frames.push_back(item);input_frames.push_back(item);
      expected_outputs+=8*item.bits.size()+`TX_TAIL;expected_inputs+=item.bits.size();
      if(item.kind==FRAME) normal_frames++;
    endfunction
    function void write_tx_observed(tx_item actual);
      tx_item frame;
      tx_sample_t golden;
      if(actual.kind==RESET_EVENT) begin
        if(output_frames.size()>0) begin
          before_reset+=output_index;
          if(actual.pending) reset_pending++;
          if(output_frames[0].kind==WARM_LAST&&actual.pending&&output_index==output_frames[0].golden.size()-1) held_last_resets++;
        end
        foreach(output_frames[f]) discarded_outputs+=output_frames[f].golden.size()-(f==0?output_index:0);
        foreach(input_frames[f]) discarded_inputs+=input_frames[f].bits.size()-(f==0?input_index:0);
        output_frames.delete();input_frames.delete();output_index=0;input_index=0;resets++;
      end else if(actual.kind==INPUT_EVENT) begin
        if(input_frames.size()==0) `uvm_fatal("COUNT","Unexpected TX accepted input")
        frame=input_frames[0];
        if(actual.observed_bit!=frame.bits[input_index]||actual.observed_last!=(frame.kind==WARM_PARTIAL?0:frame.bit_last[input_index]))
          `uvm_fatal("NUMERIC","TX pin input differs from sequence")
        inputs_checked++;input_index++;
        if(actual.observed_last) begin
          if(input_index!=frame.bits.size()) `uvm_fatal("COUNT","Early TX input TLAST")
          frame=input_frames.pop_front();input_index=0;
        end
      end else if(actual.kind==OUTPUT_EVENT) begin
        if(output_frames.size()==0) `uvm_fatal("COUNT","Unexpected TX accepted output after reset/drain")
        frame=output_frames[0];
        if(output_index>=frame.golden.size()) `uvm_fatal("COUNT","Extra TX output")
        golden=frame.golden[output_index];
        if($test$plusargs("INJECT_MISMATCH")&&frame.kind==FRAME&&frame.frame_id==0&&output_index==0) golden.re++;
        if($test$plusargs("INJECT_IM_MISMATCH")&&frame.kind==FRAME&&frame.frame_id==0&&output_index==0) golden.im++;
        if(actual.actual!==golden) `uvm_fatal("NUMERIC",$sformatf("TX frame%0d row%0d got(%0d,%0d,%0d) expected(%0d,%0d,%0d)",frame.frame_id,output_index,actual.actual.re,actual.actual.im,actual.actual.last,golden.re,golden.im,golden.last))
        checked++;output_index++;
        if(actual.actual.last) begin
          if(frame.kind!=FRAME||output_index!=8*frame.bits.size()+`TX_TAIL) `uvm_fatal("COUNT","Unexpected TX completed warm frame or bad output length")
          completed++;$display("UVM TX FRAME frame=%0d inputs=%0d samples=%0d",frame.frame_id,frame.bits.size(),output_index);
          frame=output_frames.pop_front();output_index=0;
        end
      end else `uvm_fatal("PROTOCOL","Unknown TX observed item")
    endfunction
    function void check_phase(uvm_phase phase);
      if(output_frames.size()!=0||input_frames.size()!=0||output_index!=0||input_index!=0||completed!=normal_frames||normal_frames!=5||
         checked+discarded_outputs!=expected_outputs||inputs_checked+discarded_inputs!=expected_inputs)
        `uvm_error("COUNT","TX queues/conservation did not drain")
    endfunction
    function void report_phase(uvm_phase phase);
      `uvm_info("RESULT",$sformatf({"UVM ",`TX_NAME," TX checked=%0d frames=%0d input=%0d discarded=%0d discarded_inputs=%0d expected=%0d expected_inputs=%0d resets=%0d before_reset=%0d pending_resets=%0d held_last_resets=%0d"},checked,completed,inputs_checked,discarded_outputs,discarded_inputs,expected_outputs,expected_inputs,resets,before_reset,reset_pending,held_last_resets),UVM_LOW)
    endfunction
  endclass

  class tx_env extends uvm_env;
    `uvm_component_utils(tx_env)
    uvm_sequencer #(tx_item) sequencer;tx_driver driver;tx_monitor monitor;tx_scoreboard scoreboard;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      sequencer=new("sequencer",this);driver=tx_driver::type_id::create("driver",this);monitor=tx_monitor::type_id::create("monitor",this);scoreboard=tx_scoreboard::type_id::create("scoreboard",this);
    endfunction
    function void connect_phase(uvm_phase phase);
      driver.seq_item_port.connect(sequencer.seq_item_export);driver.expected.connect(scoreboard.expected);monitor.observed.connect(scoreboard.observed);
    endfunction
  endclass
  class tx_test extends uvm_test;
    `uvm_component_utils(tx_test)
    tx_env env;string scenario;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      env=tx_env::type_id::create("env",this);if(!$value$plusargs("SCENARIO=%s",scenario)) scenario="stream";
    endfunction
    task run_phase(uvm_phase phase);
      tx_sequence sequence_instance;phase.raise_objection(this);
      sequence_instance=tx_sequence::type_id::create("vectors");sequence_instance.start(env.sequencer);
      wait(env.scoreboard.completed==sequence_instance.normal_frames);
      repeat(100) @(env.driver.vif.sample);phase.drop_objection(this);
    endtask
    function void check_phase(uvm_phase phase);
      if(env.monitor.inputs!=env.scoreboard.inputs_checked||env.monitor.outputs!=env.scoreboard.checked||env.monitor.input_stalls<5) `uvm_error("COUNT","TX accepted handshake/held source coverage mismatch")
      if(scenario=="gaps"&&env.monitor.input_gaps<20) `uvm_error("GAPS","TX ready source gaps not exercised")
      if(scenario=="stalled"&&env.monitor.output_stalls<5) `uvm_error("STALL","TX held output not exercised")
      if(scenario=="midreset"||scenario=="outreset") begin
        if(env.scoreboard.resets!=2||env.scoreboard.before_reset<1||env.scoreboard.discarded_outputs<1||env.scoreboard.reset_pending!=1||env.monitor.pending_resets!=1||env.monitor.output_stalls<5)
          `uvm_error("RESET","TX pending output reset fence not exercised")
        if(scenario=="outreset"&&env.scoreboard.held_last_resets!=1) `uvm_error("RESET","TX outreset did not hold/drop terminal output")
      end
    endfunction
    function void report_phase(uvm_phase phase);
`ifdef TX_PSK
      `uvm_info("PARAMETERS",$sformatf("UVM PSK TX PARAMETERS order=%0d amplitude=%0d differential=%0d axis=%0d pi4=%0d",`PSK_ORDER,`PSK_AMPLITUDE,`PSK_DIFFERENTIAL,`PSK_TX_AXIS,`PSK_PI4),UVM_LOW)
`endif
      `uvm_info("LABELS",$sformatf("UVM TX LABELS bits=%0d mask=%0d",`TX_LABEL_BITS,env.monitor.labels_seen),UVM_LOW)
      `uvm_info("COVER",$sformatf("UVM TX HANDSHAKES input=%0d output=%0d input_stalls=%0d output_stalls=%0d ready_gaps=%0d pending_resets=%0d",env.monitor.inputs,env.monitor.outputs,env.monitor.input_stalls,env.monitor.output_stalls,env.monitor.input_gaps,env.monitor.pending_resets),UVM_LOW)
    endfunction
  endclass
endpackage

module `TX_TOP;
  import uvm_pkg::*;import `TX_PACKAGE::*;
  logic clk=0;always #5 clk=!clk;
`ifdef TX_CPM
  parameter TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables";
`endif
  `TX_INTERFACE bus(clk);
  logic signed [17:0] corrupt_value;
  initial if($test$plusargs("INJECT_INPUT_HIGH_BIT")) begin
    wait(bus.rst!=bus.ACTIVE);force bus.s_bit=`TX_LABEL_BITS'(1<<(`TX_LABEL_BITS-1));
  end
  `TX_DUT #(.RESET_ACTIVE(bus.ACTIVE)
`ifdef TX_PSK
    ,.ORDER(`PSK_ORDER),.AMPLITUDE(`PSK_AMPLITUDE),.DIFFERENTIAL(`PSK_DIFFERENTIAL),.TX_AXIS(`PSK_TX_AXIS),.PI4(`PSK_PI4)
`endif
`ifdef TX_CPM
    ,.TABLE_DIR(TABLE_DIR),.GMSK(`TX_GMSK)
`endif
  ) dut(.clk(clk),.rst(bus.rst),.s_valid(bus.s_valid),.s_bit(bus.s_bit),.s_last(bus.s_last),.s_ready(bus.s_ready),
                                         .m_ready(bus.m_ready),.m_valid(bus.m_valid),.m_last(bus.m_last),.m_re(bus.m_re),.m_im(bus.m_im));
  initial begin uvm_config_db#(virtual `TX_INTERFACE)::set(null,"*","vif",bus);run_test("tx_test");end
  initial if($test$plusargs("INJECT_S_VALID_X")||$test$plusargs("INJECT_S_READY_X")) begin
    wait(bus.rst!=bus.ACTIVE);wait(bus.s_valid===1'b1);@(negedge clk);
    if($test$plusargs("INJECT_S_VALID_X")) force bus.s_valid=1'bx;else force bus.s_ready=1'bx;
  end
  initial if($test$plusargs("INJECT_M_VALID_X")||$test$plusargs("INJECT_M_READY_X")||$test$plusargs("INJECT_M_DATA_X")) begin
    wait(bus.rst!=bus.ACTIVE);wait(bus.m_valid===1'b1);@(negedge clk);
    if($test$plusargs("INJECT_M_VALID_X")) force bus.m_valid=1'bx;
    else if($test$plusargs("INJECT_M_READY_X")) force bus.m_ready=1'bx;
    else force bus.m_re='x;
  end
  initial if($test$plusargs("INJECT_HELD_DATA")) begin
    wait(bus.rst!=bus.ACTIVE);@(bus.sample);
    while(!(bus.sample.m_valid&&!bus.sample.m_ready)) @(bus.sample);
    @(negedge clk);force bus.m_ready=1'b0;corrupt_value=bus.m_re^18'sd1;force bus.m_re=corrupt_value;
  end
  initial begin #20000000;`uvm_fatal("TIMEOUT","Streaming TX UVM did not drain") end
endmodule
