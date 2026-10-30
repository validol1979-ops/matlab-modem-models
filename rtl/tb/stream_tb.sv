`timescale 1ns/1ps
interface rtl_stream_if(input logic clk);
`ifdef RTL_RESET_LOW
  localparam bit ACTIVE=1'b0;
`else
  localparam bit ACTIVE=1'b1;
`endif
  logic rst=ACTIVE, s_valid=0, s_ready, s_last=0;
  logic m_valid, m_ready=1, m_last;
  logic signed [36:0] s_ar=0,s_ai=0,s_br=0,s_bi=0;
  logic signed [17:0] m_re,m_im;
  logic [1:0] m_overflow;
  longint unsigned cycle=0;
  always @(posedge clk) cycle<=cycle+1;
  clocking sample @(posedge clk);
    default input #1step;
    input rst,s_valid,s_ready,s_ar,s_ai,s_br,s_bi,s_last;
    input m_valid,m_ready,m_re,m_im,m_overflow,m_last,cycle;
  endclocking
  assert property (@(posedge clk) disable iff (rst==ACTIVE)
    s_valid && !s_ready |=> s_valid && $stable({s_ar,s_ai,s_br,s_bi,s_last}))
    else $fatal(1,"Input stream changed while stalled");
  assert property (@(posedge clk) disable iff (rst==ACTIVE)
    m_valid && !m_ready |=> m_valid && $stable({m_re,m_im,m_last,m_overflow}))
    else $fatal(1,"Output stream changed while stalled");
  assert property (@(posedge clk) disable iff (rst==ACTIVE)
    m_valid |-> !$isunknown({m_re,m_im,m_last,m_overflow}))
    else $fatal(1,"Unknown valid output");
endinterface

`include "uvm_macros.svh"
package rtl_stream_uvm_pkg;
  import uvm_pkg::*;
  `uvm_analysis_imp_decl(_expected)
  `uvm_analysis_imp_decl(_observed)
  class sample_item extends uvm_sequence_item;
    `uvm_object_utils(sample_item)
    longint signed ar,ai,br,bi,re,im;
    longint unsigned cycle;
    int overflow,bubbles;
    bit last,reset_before,clear,exact_latency;
    function new(string name="sample");super.new(name);endfunction
  endclass
  class vector_sequence extends uvm_sequence #(sample_item);
    `uvm_object_utils(vector_sequence)
    function new(string name="vectors");super.new(name);endfunction
    task body();
      string filename;int fd,count,fields,reset_bit,last_bit;sample_item item;
      if(!$value$plusargs("VECTORS=%s",filename)) `uvm_fatal("INPUT","Missing vectors")
      // Two passes: the second has no resets, checking consecutive frames.
      for(int pass=0;pass<2;pass++) begin
        fd=$fopen(filename,"r");if(!fd) `uvm_fatal("INPUT","Cannot open vectors")
        if($fscanf(fd,"%d",count)!=1 || count<128) `uvm_fatal("INPUT","Invalid case count")
        for(int k=0;k<count;k++) begin
          item=sample_item::type_id::create("sample");
          fields=$fscanf(fd,"%d %d %d %d %d %d %d %d %d %d",item.ar,item.ai,item.br,item.bi,item.re,item.im,item.overflow,last_bit,reset_bit,item.bubbles);
          if(fields!=10) `uvm_fatal("INPUT","Truncated vector")
          item.exact_latency=pass==0 && k<16;
          item.last=last_bit!=0;item.reset_before=pass==0 && reset_bit!=0;
          if(pass==0 && k==0 && $test$plusargs("INJECT_MISMATCH")) item.re^=1;
          start_item(item);finish_item(item);
        end
        $fclose(fd);
      end
    endtask
  endclass
  class stream_driver extends uvm_driver #(sample_item);
    `uvm_component_utils(stream_driver)
    virtual rtl_stream_if vif;
    uvm_analysis_port #(sample_item) expected;
    function new(string name,uvm_component parent);super.new(name,parent);expected=new("expected",this);endfunction
    function void build_phase(uvm_phase phase);
      if(!uvm_config_db#(virtual rtl_stream_if)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing interface")
    endfunction
    task reset_dut();
      sample_item reset_item;
      @(negedge vif.clk);vif.s_valid=0;vif.rst=vif.ACTIVE;
      reset_item=sample_item::type_id::create("reset");reset_item.clear=1;expected.write(reset_item);
      repeat(3) @(vif.sample);
      if(vif.sample.m_valid || vif.sample.s_ready) `uvm_fatal("RESET","Handshake during reset")
      @(negedge vif.clk);vif.rst=!vif.ACTIVE;
    endtask
    task run_phase(uvm_phase phase);
      sample_item item;reset_dut();
      forever begin
        seq_item_port.get_next_item(item);
        if(item.reset_before) reset_dut();
        repeat(item.bubbles) begin @(negedge vif.clk);vif.s_valid=0;end
        @(negedge vif.clk);
        vif.s_ar=item.ar[36:0];vif.s_ai=item.ai[36:0];vif.s_br=item.br[36:0];vif.s_bi=item.bi[36:0];
        vif.s_last=item.last;vif.s_valid=1;
        do @(vif.sample); while(!vif.sample.s_ready);
        item.cycle=vif.sample.cycle;expected.write(item);
        seq_item_port.item_done();
        // Stop this sample being accepted a second time while obtaining the next.
        vif.s_valid=0;
      end
    endtask
  endclass
  class stream_monitor extends uvm_monitor;
    `uvm_component_utils(stream_monitor)
    virtual rtl_stream_if vif;
    uvm_analysis_port #(sample_item) observed;
    int stalls=0;
    function new(string name,uvm_component parent);super.new(name,parent);observed=new("observed",this);endfunction
    function void build_phase(uvm_phase phase);
      if(!uvm_config_db#(virtual rtl_stream_if)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing interface")
    endfunction
    task run_phase(uvm_phase phase);
      sample_item item;
      forever begin
        @(vif.sample);
        if(vif.sample.rst!=vif.ACTIVE) begin
          if(vif.sample.m_valid && !vif.sample.m_ready) stalls++;
          if(vif.sample.m_valid && vif.sample.m_ready) begin
            item=sample_item::type_id::create("observed");
            item.re=$signed(vif.sample.m_re);item.im=$signed(vif.sample.m_im);
            item.last=vif.sample.m_last;item.overflow=int'(vif.sample.m_overflow);item.cycle=vif.sample.cycle;
            observed.write(item);
          end
        end
      end
    endtask
  endclass
  class stream_scoreboard extends uvm_scoreboard;
    `uvm_component_utils(stream_scoreboard)
    uvm_analysis_imp_expected #(sample_item,stream_scoreboard) expected;
    uvm_analysis_imp_observed #(sample_item,stream_scoreboard) observed;
    sample_item queue[$];
    int checked=0,sent=0,discarded=0,resets=0,lasts=0,saturations=0,latency,full_rate=0;
    longint unsigned previous_cycle;
    covergroup arithmetic_coverage with function sample(int flags,bit last);
      option.per_instance=1;
      saturation: coverpoint flags {bins masks[]={0,1,2,3};}
      frame_end: coverpoint last;
    endgroup
    function new(string name,uvm_component parent);super.new(name,parent);arithmetic_coverage=new();endfunction
    function void build_phase(uvm_phase phase);
      expected=new("expected",this);observed=new("observed",this);
      if(!$value$plusargs("LATENCY=%d",latency) || latency<1) `uvm_fatal("CONFIG","Missing latency")
    endfunction
    function void write_expected(sample_item item);
      if(item.clear) begin discarded+=queue.size();queue.delete();resets++;end
      else begin queue.push_back(item);sent++;end
    endfunction
    function void write_observed(sample_item actual);
      sample_item golden;
      if(queue.size()==0) `uvm_fatal("COUNT","Unexpected output")
      golden=queue.pop_front();
      if(actual.re!=golden.re || actual.im!=golden.im || actual.overflow!=golden.overflow)
        `uvm_fatal("NUMERIC",$sformatf("Output %0d: expected (%0d,%0d,%0d), got (%0d,%0d,%0d)",checked,golden.re,golden.im,golden.overflow,actual.re,actual.im,actual.overflow))
      if(actual.last!=golden.last) `uvm_fatal("PROTOCOL","TLAST mismatch")
      if(actual.cycle-golden.cycle<longint'(latency)) `uvm_fatal("LATENCY","Response too early")
      if(golden.exact_latency) begin
        if(actual.cycle-golden.cycle!=longint'(latency)) `uvm_fatal("LATENCY","Wrong unstalled latency")
        if(full_rate>0 && actual.cycle!=previous_cycle+1) `uvm_fatal("THROUGHPUT","Expected one output each clock")
        previous_cycle=actual.cycle;full_rate++;
      end
      arithmetic_coverage.sample(actual.overflow,actual.last);
      checked++;lasts+=actual.last;saturations+=actual.overflow!=0;
    endfunction
    function void check_phase(uvm_phase phase);
      if(queue.size()!=0 || checked+discarded!=sent || checked<256 || discarded==0 || resets<3 || lasts<2 || saturations==0 || full_rate!=16)
        `uvm_error("COUNT","Incomplete arithmetic/reset/frame coverage")
    endfunction
    function void report_phase(uvm_phase phase);
      `uvm_info("RESULT",$sformatf("Checked %0d RTL samples, discarded %0d on reset; %0d saturations",checked,discarded,saturations),UVM_LOW)
    endfunction
  endclass
  class stream_env extends uvm_env;
    `uvm_component_utils(stream_env)
    uvm_sequencer #(sample_item) sequencer;
    stream_driver driver;stream_monitor monitor;stream_scoreboard scoreboard;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      sequencer=new("sequencer",this);driver=stream_driver::type_id::create("driver",this);
      monitor=stream_monitor::type_id::create("monitor",this);scoreboard=stream_scoreboard::type_id::create("scoreboard",this);
    endfunction
    function void connect_phase(uvm_phase phase);
      driver.seq_item_port.connect(sequencer.seq_item_export);
      driver.expected.connect(scoreboard.expected);monitor.observed.connect(scoreboard.observed);
    endfunction
    function void check_phase(uvm_phase phase);
      if(monitor.stalls<5) `uvm_error("STALL","Backpressure was not exercised")
    endfunction
  endclass
  class stream_test extends uvm_test;
    `uvm_component_utils(stream_test)
    stream_env env;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);env=stream_env::type_id::create("env",this);endfunction
    task run_phase(uvm_phase phase);
      vector_sequence sequence_instance;phase.raise_objection(this);
      sequence_instance=vector_sequence::type_id::create("vectors");sequence_instance.start(env.sequencer);
      repeat(100) @(env.driver.vif.sample);
      phase.drop_objection(this);
    endtask
  endclass
endpackage

module rtl_stream_top;
  import uvm_pkg::*;
  import rtl_stream_uvm_pkg::*;
  logic clk=0;
  always #5ns clk=~clk;
  rtl_stream_if bus(clk);
  int cycles=0;
  always @(negedge clk) begin
    cycles++;
    bus.m_ready=cycles<32 || ((cycles%97<17 || cycles%97>=31) && cycles%7!=0);
  end
`ifdef DUT_RESIZE
  fxp_stream_resize #(.RESET_ACTIVE(bus.ACTIVE)) dut(
    .clk(clk),.rst(bus.rst),.s_valid(bus.s_valid),.s_ready(bus.s_ready),.s_last(bus.s_last),
    .s_re(bus.s_ar),.s_im(bus.s_ai),.m_valid(bus.m_valid),.m_ready(bus.m_ready),.m_last(bus.m_last),
    .m_re(bus.m_re),.m_im(bus.m_im),.m_overflow(bus.m_overflow));
`else
`ifdef DUT_ADD
  fxp_complex_add
`else
  fxp_complex_mul
`endif
  #(.RESET_ACTIVE(bus.ACTIVE)) dut(
    .clk(clk),.rst(bus.rst),.s_valid(bus.s_valid),.s_ready(bus.s_ready),.s_last(bus.s_last),
    .s_ar(bus.s_ar[17:0]),.s_ai(bus.s_ai[17:0]),.s_br(bus.s_br[17:0]),.s_bi(bus.s_bi[17:0]),
    .m_valid(bus.m_valid),.m_ready(bus.m_ready),.m_last(bus.m_last),
    .m_re(bus.m_re),.m_im(bus.m_im),.m_overflow(bus.m_overflow));
`endif
  initial begin
    uvm_config_db#(virtual rtl_stream_if)::set(null,"*","vif",bus);
    run_test("stream_test");
  end
  initial begin #1ms; $fatal(1,"RTL simulation timeout");end
endmodule
