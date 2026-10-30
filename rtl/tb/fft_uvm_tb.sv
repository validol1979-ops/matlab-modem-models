// FFT UVM: expected frames precede pin traffic; monitor samples pre-edge handshakes.
`timescale 1ns/1ps
`include "uvm_macros.svh"
`ifndef FFT_LOG2N
`define FFT_LOG2N 6
`endif
`ifndef FFT_IN_WIDTH
`define FFT_IN_WIDTH 18
`endif
`ifndef FFT_WIDTH
`define FFT_WIDTH 20
`endif
interface fft_uvm_if(input logic clk);
 import uvm_pkg::*;
`ifdef RTL_RESET_LOW
 localparam bit ACTIVE=0;
`else
 localparam bit ACTIVE=1;
`endif
 localparam int N=1<<`FFT_LOG2N;
 logic rst=ACTIVE,s_valid=0,s_last=0,s_inverse=0,m_ready=1,allow_error=0;
 logic signed [`FFT_IN_WIDTH-1:0] s_re=0,s_im=0;
 wire s_ready,m_valid,m_last,m_inverse,error;
 wire signed [`FFT_WIDTH-1:0] m_re,m_im;
 clocking sample @(posedge clk);
  default input #1step;
  input rst,s_valid,s_ready,s_last,s_inverse,s_re,s_im,m_valid,m_ready,m_last,m_inverse,m_re,m_im,error,allow_error;
 endclocking
 assert property(@(posedge clk) disable iff(rst==ACTIVE)
  s_valid&&!s_ready |=> s_valid&&$stable({s_re,s_im,s_inverse,s_last})) else `uvm_fatal("STALL","FFT held input changed")
 assert property(@(posedge clk) disable iff(rst==ACTIVE)
  m_valid&&!m_ready |=> m_valid&&$stable({m_re,m_im,m_inverse,m_last})) else `uvm_fatal("STALL","FFT held output changed")
endinterface

package fft_uvm_pkg;
 import uvm_pkg::*;
 `uvm_analysis_imp_decl(_fft_expected)
 `uvm_analysis_imp_decl(_fft_actual)
 localparam int N=1<<`FFT_LOG2N;
 typedef enum {FRAME,MID,TERMINAL,BAD,RESET,INPUT,OUTPUT,FENCE} fft_kind_t;
 typedef struct {int re,im,inverse,last,gap;} fft_row_t;
 class fft_item extends uvm_sequence_item;
  `uvm_object_utils(fft_item)
  fft_kind_t kind;
  int frame;
  bit pending;
  fft_row_t source[],golden[],actual;
  function new(string name="fft_item");super.new(name);endfunction
 endclass

 class fft_sequence extends uvm_sequence #(fft_item);
  `uvm_object_utils(fft_sequence)
  fft_item frames[$];string scenario,directory;
  function new(string name="fft_sequence");super.new(name);endfunction
  task load_vectors();
   int fd,ofd,count,outputs;
   fft_item item;
   if(!$value$plusargs("VECTORS=%s",directory)) `uvm_fatal("INPUT","Missing FFT vectors")
   if(!$value$plusargs("SCENARIO=%s",scenario)) scenario="stream";
   if(!(scenario inside {"stream","gaps","stalled","midreset","outreset","badlast"})) `uvm_fatal("INPUT","Invalid FFT scenario")
   fd=$fopen({directory,"/in.txt"},"r");ofd=$fopen({directory,"/out.txt"},"r");
   if(!fd||!ofd||$fscanf(fd,"%d",count)!=1||$fscanf(ofd,"%d",outputs)!=1||count!=outputs||count%N!=0||count<2*N)
    `uvm_fatal("INPUT","Invalid FFT input/output geometry")
   for(int f=0;f<count/N;f++) begin
    item=fft_item::type_id::create($sformatf("frame%0d",f));item.kind=FRAME;item.frame=f;
    item.source=new[N];item.golden=new[N];
    for(int k=0;k<N;k++) begin
     if($fscanf(fd,"%d %d %d %d %d",item.source[k].re,item.source[k].im,item.source[k].inverse,item.source[k].last,item.source[k].gap)!=5||
        $fscanf(ofd,"%d %d %d %d",item.golden[k].re,item.golden[k].im,item.golden[k].inverse,item.golden[k].last)!=4||
        item.source[k].last!=int'(k==N-1)||item.golden[k].last!=int'(k==N-1)||
        !(item.source[k].inverse inside {0,1})||item.golden[k].inverse!=item.source[k].inverse||item.source[k].gap<0)
      `uvm_fatal("INPUT","Malformed FFT frame/TLAST/direction")
    end
    frames.push_back(item);
   end
   $fclose(fd);$fclose(ofd);
  endtask
  task body();
   fft_item warm,reset_item;load_vectors();
   if(scenario inside {"midreset","outreset","badlast"}) begin
    warm=fft_item::type_id::create("warm");warm.frame=0;
    warm.kind=scenario=="midreset"?MID:scenario=="outreset"?TERMINAL:BAD;
    warm.source=frames[0].source;warm.golden=frames[0].golden;
    start_item(warm);finish_item(warm);
    reset_item=fft_item::type_id::create("reset");reset_item.kind=RESET;
    start_item(reset_item);finish_item(reset_item);
   end
   foreach(frames[f]) begin start_item(frames[f]);finish_item(frames[f]);end
  endtask
 endclass

 class fft_driver extends uvm_driver #(fft_item);
  `uvm_component_utils(fft_driver)
  virtual fft_uvm_if vif;uvm_analysis_port #(fft_item) expected;
  string scenario;bit hold_last=0;
  function new(string name,uvm_component parent);super.new(name,parent);expected=new("expected",this);endfunction
  function void build_phase(uvm_phase phase);
   if(!uvm_config_db#(virtual fft_uvm_if)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing FFT interface")
   if(!$value$plusargs("SCENARIO=%s",scenario)) scenario="stream";
  endfunction
  task reset_dut();
   @(negedge vif.clk);vif.rst=vif.ACTIVE;vif.s_valid=0;vif.s_last=0;vif.allow_error=0;hold_last=0;
   repeat(5) @(vif.sample);
   if(vif.sample.m_valid!==1'b0||vif.sample.s_ready!==1'b0||vif.sample.error!==1'b0) `uvm_fatal("RESET","FFT state survived reset")
   @(negedge vif.clk);vif.rst=!vif.ACTIVE;
  endtask
  task drive(fft_item item);
   int count;expected.write(item);count=item.kind==MID?N/2:N;
   if(item.kind==TERMINAL) hold_last=1;
   if(item.kind==BAD) vif.allow_error=1;
   for(int k=0;k<count;k++) begin
    if(scenario=="gaps"&&item.source[k].gap>0) begin
     @(negedge vif.clk);vif.s_valid=0;repeat(item.source[k].gap) @(vif.sample);
    end
    @(negedge vif.clk);vif.s_valid=1;vif.s_re=`FFT_IN_WIDTH'(item.source[k].re);vif.s_im=`FFT_IN_WIDTH'(item.source[k].im);
    vif.s_inverse=1'(item.source[k].inverse);vif.s_last=item.kind==BAD?1'(k==N-2):1'(item.source[k].last);
    do @(vif.sample);while(!vif.sample.s_ready);
   end
   // Ordinary items leave valid asserted: the next frame replaces the tuple on
   // the very next negedge, preserving a back-to-back FFT burst.
   if(item.kind!=FRAME) begin
    @(negedge vif.clk);vif.s_valid=0;vif.s_last=0;
    if(item.kind==TERMINAL) begin
     do @(vif.sample);while(!(vif.sample.m_valid&&vif.sample.m_last&&!vif.sample.m_ready));
     repeat(5) @(vif.sample);
    end else if(item.kind==BAD) begin
     do @(vif.sample);while(!(vif.sample.m_valid&&vif.sample.m_last&&vif.sample.m_ready));
     repeat(5) @(vif.sample);
     if(vif.sample.error!==1'b1) `uvm_fatal("ERROR","FFT failed to retain malformed-TLAST error")
    end else repeat(3) @(vif.sample);
   end
  endtask
  task run_phase(uvm_phase phase);
   fork
    begin
     int cycles=0;
     forever begin
      @(negedge vif.clk);cycles++;
      vif.m_ready=(vif.rst==vif.ACTIVE)||(!(hold_last&&vif.m_valid&&vif.m_last)&&
       (!(scenario inside {"stalled","outreset","badlast"})||((cycles%7)!=0&&(cycles%31)<25)));
     end
    end
   join_none
   reset_dut();
   forever begin
    fft_item item;seq_item_port.get_next_item(item);
    if(item.kind==RESET) reset_dut();else drive(item);
    seq_item_port.item_done();
   end
  endtask
 endclass

 class fft_monitor extends uvm_monitor;
  `uvm_component_utils(fft_monitor)
  virtual fft_uvm_if vif;uvm_analysis_port #(fft_item) observed;
  int inputs=0,outputs=0,input_stalls=0,output_stalls=0,gaps=0,pending_resets=0,error_cycles=0;
  function new(string name,uvm_component parent);super.new(name,parent);observed=new("observed",this);endfunction
  function void build_phase(uvm_phase phase);
   if(!uvm_config_db#(virtual fft_uvm_if)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing FFT monitor interface")
  endfunction
  task run_phase(uvm_phase phase);
   bit was_reset=0,was_error=0,frame_open=0;
   forever begin
    fft_item item;@(vif.sample);
    if($isunknown(vif.sample.rst)) `uvm_fatal("PROTOCOL","Unknown FFT reset")
    if(vif.sample.rst==vif.ACTIVE) begin
     if(!was_reset) begin
      item=fft_item::type_id::create("fence");item.kind=FENCE;item.pending=vif.sample.m_valid===1'b1;
      if(item.pending) pending_resets++;observed.write(item);
     end
     was_reset=1;was_error=0;frame_open=0;
    end else begin
     was_reset=0;
     if($isunknown({vif.sample.s_valid,vif.sample.s_ready,vif.sample.m_valid,vif.sample.m_ready,vif.sample.error})) `uvm_fatal("PROTOCOL","Unknown FFT controls")
     if(vif.sample.error&&!vif.sample.allow_error) `uvm_fatal("ERROR","Unexpected FFT sticky error")
     if(was_error&&!vif.sample.error) `uvm_fatal("ERROR","FFT sticky error cleared without reset")
     was_error=vif.sample.error;if(vif.sample.error) error_cycles++;
     if(vif.sample.s_valid&&$isunknown({vif.sample.s_re,vif.sample.s_im,vif.sample.s_inverse,vif.sample.s_last})) `uvm_fatal("NUMERIC","Unknown valid FFT input")
     if(vif.sample.m_valid&&$isunknown({vif.sample.m_re,vif.sample.m_im,vif.sample.m_inverse,vif.sample.m_last})) `uvm_fatal("NUMERIC","Unknown valid FFT output")
     if(vif.sample.s_valid&&!vif.sample.s_ready) input_stalls++;
     if(vif.sample.m_valid&&!vif.sample.m_ready) output_stalls++;
     if(frame_open&&!vif.sample.s_valid&&vif.sample.s_ready) gaps++;
     if(vif.sample.s_valid&&vif.sample.s_ready) begin
      item=fft_item::type_id::create("input");item.kind=INPUT;inputs++;
      item.actual.re=$signed(vif.sample.s_re);item.actual.im=$signed(vif.sample.s_im);
      item.actual.inverse=int'(vif.sample.s_inverse);item.actual.last=int'(vif.sample.s_last);
      frame_open=!vif.sample.s_last;observed.write(item);
     end
     if(vif.sample.m_valid&&vif.sample.m_ready) begin
      item=fft_item::type_id::create("output");item.kind=OUTPUT;outputs++;
      item.actual.re=$signed(vif.sample.m_re);item.actual.im=$signed(vif.sample.m_im);
      item.actual.inverse=int'(vif.sample.m_inverse);item.actual.last=int'(vif.sample.m_last);observed.write(item);
     end
    end
   end
  endtask
 endclass

 class fft_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(fft_scoreboard)
  uvm_analysis_imp_fft_expected #(fft_item,fft_scoreboard) expected;
  uvm_analysis_imp_fft_actual #(fft_item,fft_scoreboard) observed;
  fft_item input_frames[$],output_frames[$];
  int in_index=0,out_index=0,checked_in=0,checked_out=0,expected_in=0,expected_out=0;
  int discarded_in=0,discarded_out=0,resets=0,normal=0,completed=0,bad_completed=0;
  int before_reset=0,terminal_resets=0,mode_mask=0;
  function new(string name,uvm_component parent);super.new(name,parent);endfunction
  function void build_phase(uvm_phase phase);expected=new("expected",this);observed=new("observed",this);endfunction
  function void write_fft_expected(fft_item item);
   input_frames.push_back(item);output_frames.push_back(item);expected_in+=N;expected_out+=N;
   if(item.kind==FRAME) normal++;
  endfunction
  function void write_fft_actual(fft_item item);
   fft_item frame;fft_row_t golden;
   if(item.kind==FENCE) begin
    before_reset+=out_index;
    if(output_frames.size()>0&&output_frames[0].kind==TERMINAL&&item.pending&&out_index==N-1) terminal_resets++;
    foreach(input_frames[f]) discarded_in+=N-(f==0?in_index:0);
    foreach(output_frames[f]) discarded_out+=N-(f==0?out_index:0);
    input_frames.delete();output_frames.delete();in_index=0;out_index=0;resets++;
   end else if(item.kind==INPUT) begin
    if(input_frames.size()==0) `uvm_fatal("COUNT","Unexpected FFT input")
    frame=input_frames[0];golden=frame.source[in_index];
    if(frame.kind==BAD) golden.last=int'(in_index==N-2);
    if(item.actual.re!=golden.re||item.actual.im!=golden.im||item.actual.inverse!=golden.inverse||item.actual.last!=golden.last)
     `uvm_fatal("NUMERIC","FFT accepted input differs from source frame")
    checked_in++;in_index++;
    if(in_index==N) begin frame=input_frames.pop_front();in_index=0;end
   end else if(item.kind==OUTPUT) begin
    if(output_frames.size()==0) `uvm_fatal("COUNT","Unexpected FFT output after reset/drain")
    frame=output_frames[0];golden=frame.golden[out_index];
    if($test$plusargs("INJECT_MISMATCH")&&frame.kind==FRAME&&frame.frame==0&&out_index==0) golden.re++;
    if(item.actual.re!=golden.re||item.actual.im!=golden.im||item.actual.inverse!=golden.inverse||item.actual.last!=golden.last)
     `uvm_fatal("NUMERIC",$sformatf("FFT frame=%0d row=%0d got(%0d,%0d,%0d,%0d) expected(%0d,%0d,%0d,%0d)",frame.frame,out_index,item.actual.re,item.actual.im,item.actual.inverse,item.actual.last,golden.re,golden.im,golden.inverse,golden.last))
    checked_out++;out_index++;
    if(item.actual.last) begin
     if(out_index!=N||!(frame.kind inside {FRAME,BAD})) `uvm_fatal("COUNT","Unexpected FFT frame boundary")
     if(frame.kind==BAD) bad_completed++;
     else begin completed++;mode_mask|=1<<item.actual.inverse;$display("UVM FFT FRAME id=%0d samples=%0d inverse=%0d",frame.frame,out_index,item.actual.inverse);end
     frame=output_frames.pop_front();out_index=0;
    end
   end else `uvm_fatal("PROTOCOL","Unexpected FFT observation")
  endfunction
  function void check_phase(uvm_phase phase);
   if(input_frames.size()!=0||output_frames.size()!=0||in_index!=0||out_index!=0||completed!=normal||normal<2||
      checked_in+discarded_in!=expected_in||checked_out+discarded_out!=expected_out)
    `uvm_error("COUNT","FFT frame/queue conservation did not drain")
  endfunction
  function void report_phase(uvm_phase phase);
   `uvm_info("RESULT",$sformatf("UVM FFT checked=%0d inputs=%0d frames=%0d discarded=%0d discarded_inputs=%0d expected=%0d expected_inputs=%0d resets=%0d before_reset=%0d terminal_resets=%0d bad_completed=%0d modes=%0d",checked_out,checked_in,completed,discarded_out,discarded_in,expected_out,expected_in,resets,before_reset,terminal_resets,bad_completed,mode_mask),UVM_LOW)
  endfunction
 endclass

 class fft_env extends uvm_env;
  `uvm_component_utils(fft_env)
  uvm_sequencer #(fft_item) sequencer;fft_driver driver;fft_monitor monitor;fft_scoreboard scoreboard;
  function new(string name,uvm_component parent);super.new(name,parent);endfunction
  function void build_phase(uvm_phase phase);
   sequencer=new("sequencer",this);driver=fft_driver::type_id::create("driver",this);
   monitor=fft_monitor::type_id::create("monitor",this);scoreboard=fft_scoreboard::type_id::create("scoreboard",this);
  endfunction
  function void connect_phase(uvm_phase phase);
   driver.seq_item_port.connect(sequencer.seq_item_export);driver.expected.connect(scoreboard.expected);monitor.observed.connect(scoreboard.observed);
  endfunction
 endclass
 class fft_test extends uvm_test;
  `uvm_component_utils(fft_test)
  fft_env env;
  function new(string name,uvm_component parent);super.new(name,parent);endfunction
  function void build_phase(uvm_phase phase);env=fft_env::type_id::create("env",this);endfunction
  task run_phase(uvm_phase phase);
   fft_sequence seq;phase.raise_objection(this);seq=fft_sequence::type_id::create("frames");seq.start(env.sequencer);
   @(negedge env.driver.vif.clk);env.driver.vif.s_valid=0;env.driver.vif.s_last=0;
   wait(env.scoreboard.completed==seq.frames.size());repeat(100) @(env.driver.vif.sample);phase.drop_objection(this);
  endtask
  function void check_phase(uvm_phase phase);
   if(env.monitor.inputs!=env.scoreboard.checked_in||env.monitor.outputs!=env.scoreboard.checked_out) `uvm_error("COUNT","FFT monitor/scoreboard handshakes differ")
  endfunction
  function void report_phase(uvm_phase phase);
   `uvm_info("WIDTH",$sformatf("UVM FFT WIDTH log2n=%0d input=%0d output=%0d",`FFT_LOG2N,`FFT_IN_WIDTH,`FFT_WIDTH),UVM_LOW)
   `uvm_info("HANDSHAKES",$sformatf("UVM FFT HANDSHAKES input=%0d output=%0d input_stalls=%0d output_stalls=%0d gaps=%0d pending_resets=%0d error_cycles=%0d",env.monitor.inputs,env.monitor.outputs,env.monitor.input_stalls,env.monitor.output_stalls,env.monitor.gaps,env.monitor.pending_resets,env.monitor.error_cycles),UVM_LOW)
  endfunction
 endclass
endpackage

module fft_uvm_top;
 import uvm_pkg::*;import fft_uvm_pkg::*;
 parameter TWIDDLE_FILE="rtl/common/mem/fft_twiddle_64.mem";
 logic clk=0;always #5 clk=!clk;
 fft_uvm_if bus(clk);
 fft_r2sdf #(.LOG2N(`FFT_LOG2N),.IN_WIDTH(`FFT_IN_WIDTH),.WIDTH(`FFT_WIDTH),.RESET_ACTIVE(bus.ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) dut(
  .clk(clk),.rst(bus.rst),.s_valid(bus.s_valid),.s_last(bus.s_last),.s_inverse(bus.s_inverse),.s_re(bus.s_re),.s_im(bus.s_im),.s_ready(bus.s_ready),
  .m_valid(bus.m_valid),.m_last(bus.m_last),.m_inverse(bus.m_inverse),.m_re(bus.m_re),.m_im(bus.m_im),.m_ready(bus.m_ready),.error(bus.error));
 initial begin uvm_config_db#(virtual fft_uvm_if)::set(null,"*","vif",bus);run_test("fft_test");end
 initial if($test$plusargs("INJECT_S_VALID_X")||$test$plusargs("INJECT_S_READY_X")||$test$plusargs("INJECT_INPUT_X")) begin
  wait(bus.rst!=bus.ACTIVE);wait(bus.s_valid);@(negedge clk);
  if($test$plusargs("INJECT_S_VALID_X")) force bus.s_valid=1'bx;
  else if($test$plusargs("INJECT_S_READY_X")) force bus.s_ready=1'bx;else force bus.s_re='x;
 end
 logic corrupt_mode;logic signed [`FFT_WIDTH-1:0] corrupt_value;
 initial if($test$plusargs("INJECT_M_VALID_X")||$test$plusargs("INJECT_M_READY_X")||$test$plusargs("INJECT_OUTPUT_X")||
            $test$plusargs("INJECT_DIRECTION")||$test$plusargs("INJECT_LAST")) begin
  wait(bus.rst!=bus.ACTIVE);wait(bus.m_valid);@(negedge clk);
  if($test$plusargs("INJECT_M_VALID_X")) force bus.m_valid=1'bx;
  else if($test$plusargs("INJECT_M_READY_X")) force bus.m_ready=1'bx;
  else if($test$plusargs("INJECT_OUTPUT_X")) force bus.m_re='x;
  else if($test$plusargs("INJECT_DIRECTION")) begin corrupt_mode=!bus.m_inverse;force bus.m_inverse=corrupt_mode;end
  else force bus.m_last=1'b1;
 end
 initial if($test$plusargs("INJECT_HELD_DATA")) begin
  wait(bus.rst!=bus.ACTIVE);@(bus.sample);
  while(!(bus.sample.m_valid&&!bus.sample.m_ready)) @(bus.sample);
  @(negedge clk);force bus.m_ready=1'b0;
  corrupt_value=bus.m_re^`FFT_WIDTH'(1);force bus.m_re=corrupt_value;
 end
 initial if($test$plusargs("INJECT_ERROR_CLEAR")) begin wait(bus.error);@(negedge clk);force bus.error=1'b0;end
 initial begin #20000000;`uvm_fatal("TIMEOUT","FFT UVM did not drain") end
endmodule
