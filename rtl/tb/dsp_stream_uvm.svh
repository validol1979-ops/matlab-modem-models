// Shared UVM for a configured stream with independent input/output transaction lengths.
`timescale 1ns/1ps
`include "uvm_macros.svh"
interface dsp_uvm_if(input logic clk);
 import uvm_pkg::*;
`ifdef RTL_RESET_LOW
 localparam bit ACTIVE=0;
`else
 localparam bit ACTIVE=1;
`endif
 logic rst=ACTIVE,cfg_valid=0,cfg_last=0,s_valid=0,s_last=0,m_ready=1;
 logic [511:0] cfg_data=0,s_data=0;
 wire cfg_ready,configured,error,s_ready,m_valid,m_last;
 wire [511:0] m_data;
 logic w_ready=1;wire w_valid,w_last;wire [35:0] w_data;
 clocking sample @(posedge clk);
  default input #1step;
  input rst,cfg_valid,cfg_last,cfg_data,cfg_ready,configured,error,s_valid,s_last,s_data,s_ready,m_valid,m_last,m_data,m_ready,w_valid,w_last,w_data,w_ready;
 endclocking
 assert property(@(posedge clk) disable iff(rst==ACTIVE)
  cfg_valid&&!cfg_ready |=> cfg_valid&&$stable({cfg_data,cfg_last})) else `uvm_fatal("STALL","Held DSP configuration changed")
 assert property(@(posedge clk) disable iff(rst==ACTIVE)
  s_valid&&!s_ready |=> s_valid&&$stable({s_data,s_last})) else `uvm_fatal("STALL","Held DSP input changed")
 assert property(@(posedge clk) disable iff(rst==ACTIVE)
  m_valid&&!m_ready |=> m_valid&&$stable({m_data,m_last})) else `uvm_fatal("STALL","Held DSP output changed")
 assert property(@(posedge clk) disable iff(rst==ACTIVE)
  w_valid&&!w_ready |=> w_valid&&$stable({w_data,w_last})) else `uvm_fatal("STALL","Held DSP weights changed")
endinterface

package dsp_uvm_pkg;
 import uvm_pkg::*;
 `uvm_analysis_imp_decl(_dsp_expected)
 `uvm_analysis_imp_decl(_dsp_observed)
 typedef enum {NORMAL,PARTIAL,TERMINAL,WEIGHT_TERMINAL,CFG_PARTIAL,RESET,CONFIG_EVENT,INPUT_EVENT,OUTPUT_EVENT,WEIGHT_EVENT,FENCE} dsp_kind_t;
 typedef struct {logic [511:0] data;int last,gap;} dsp_row_t;
 class dsp_item extends uvm_sequence_item;
  `uvm_object_utils(dsp_item)
  dsp_kind_t kind;
  int frame;
  bit pending,pending_weight;
  dsp_row_t cfg[],source[],golden[],weights[],actual;
  function new(string name="dsp_item");super.new(name);endfunction
 endclass

 class dsp_sequence extends uvm_sequence #(dsp_item);
  `uvm_object_utils(dsp_sequence)
  dsp_item frames[$];string directory,scenario;
  function new(string name="dsp_sequence");super.new(name);endfunction
  task load_vectors();
   int fd,cfg_count,transactions,nin,nout,nw;
   dsp_row_t config_rows[];
   dsp_item item;
   if(!$value$plusargs("VECTORS=%s",directory)) `uvm_fatal("INPUT","Missing DSP vectors")
   if(!$value$plusargs("SCENARIO=%s",scenario)) scenario="stream";
   if(!(scenario inside {"stream","gaps","stalled","midreset","outreset","woutreset","cfgreset"})) `uvm_fatal("INPUT","Unknown DSP scenario")
   if(scenario=="woutreset"&&`DSP_KIND!=20&&`DSP_KIND!=21) `uvm_fatal("INPUT","No physical weight stream")
   fd=$fopen({directory,"/plan.txt"},"r");
   if(!fd||$fscanf(fd,"%d %d",cfg_count,transactions)!=2||cfg_count<0||transactions<1) `uvm_fatal("INPUT","Invalid DSP plan header")
   if(scenario=="cfgreset"&&(cfg_count==0||`DSP_KIND==7||`DSP_KIND==8||`DSP_KIND==13||`DSP_KIND==14||`DSP_KIND==17||`DSP_KIND==20||`DSP_KIND==21)) `uvm_fatal("INPUT","Partial configuration reset not applicable")
   config_rows=new[cfg_count];
   foreach(config_rows[k]) if($fscanf(fd,"%h %d",config_rows[k].data,config_rows[k].last)!=2||config_rows[k].last!=int'(k==cfg_count-1&&`DSP_KIND!=7&&`DSP_KIND!=8&&`DSP_KIND!=13&&`DSP_KIND!=14&&`DSP_KIND!=17&&`DSP_KIND!=20&&`DSP_KIND!=21))
    `uvm_fatal("INPUT","Invalid DSP configuration geometry")
   for(int f=0;f<transactions;f++) begin
    if($fscanf(fd,"%d %d %d",nin,nout,nw)!=3||nin<1||nout<1||nw<0||((`DSP_KIND==20||`DSP_KIND==21)?nw<1:nw!=0)) `uvm_fatal("INPUT","Invalid DSP transaction lengths")
    item=dsp_item::type_id::create($sformatf("frame%0d",f));item.kind=NORMAL;item.frame=f;
    if(f==0) item.cfg=config_rows;
    item.source=new[nin];item.golden=new[nout];
    foreach(item.source[k]) if($fscanf(fd,"%h %d %d",item.source[k].data,item.source[k].last,item.source[k].gap)!=3||
      item.source[k].last!=int'(k==nin-1)||item.source[k].gap<0) `uvm_fatal("INPUT","Invalid DSP source rows")
    foreach(item.golden[k]) if($fscanf(fd,"%h %d",item.golden[k].data,item.golden[k].last)!=2||
      item.golden[k].last!=int'(k==nout-1)) `uvm_fatal("INPUT","Invalid DSP expected rows")
    item.weights=new[nw];
    foreach(item.weights[k]) if($fscanf(fd,"%h %d",item.weights[k].data,item.weights[k].last)!=2||
      item.weights[k].last!=int'(k==nw-1)) `uvm_fatal("INPUT","Invalid DSP weight rows")
    frames.push_back(item);
   end
   $fclose(fd);
  endtask
  task body();
   dsp_item warm,reset_item;load_vectors();
   if(scenario inside {"midreset","outreset","woutreset","cfgreset"}) begin
    warm=dsp_item::type_id::create("warmup");warm.frame=0;
    warm.kind=scenario=="midreset"?PARTIAL:scenario=="outreset"?TERMINAL:scenario=="woutreset"?WEIGHT_TERMINAL:CFG_PARTIAL;
    warm.cfg=frames[0].cfg;warm.source=frames[0].source;warm.golden=frames[0].golden;warm.weights=frames[0].weights;
    start_item(warm);finish_item(warm);
    reset_item=dsp_item::type_id::create("reset");reset_item.kind=RESET;
    start_item(reset_item);finish_item(reset_item);
   end
   foreach(frames[f]) begin start_item(frames[f]);finish_item(frames[f]);end
  endtask
 endclass

 class dsp_driver extends uvm_driver #(dsp_item);
  `uvm_component_utils(dsp_driver)
  virtual dsp_uvm_if vif;uvm_analysis_port #(dsp_item) expected;
  string scenario;bit hold_last=0,hold_weight_last=0;
  function new(string name,uvm_component parent);super.new(name,parent);expected=new("expected",this);endfunction
  function void build_phase(uvm_phase phase);
   if(!uvm_config_db#(virtual dsp_uvm_if)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing DSP interface")
   if(!$value$plusargs("SCENARIO=%s",scenario)) scenario="stream";
  endfunction
  task reset_dut();
   @(negedge vif.clk);vif.rst=vif.ACTIVE;vif.cfg_valid=0;vif.cfg_last=0;vif.s_valid=0;vif.s_last=0;hold_last=0;hold_weight_last=0;
   repeat(5) @(vif.sample);
   if(vif.sample.m_valid!==1'b0||vif.sample.configured!==1'b0||vif.sample.error!==1'b0||vif.sample.w_valid!==1'b0) `uvm_fatal("RESET","DSP state survived reset fence")
   @(negedge vif.clk);vif.rst=!vif.ACTIVE;
  endtask
  task configure(dsp_item item);
   int count,guard;
   count=item.kind==CFG_PARTIAL?((item.cfg.size()>1)?item.cfg.size()/2:1):item.cfg.size();
   for(int k=0;k<count;k++) begin
    @(negedge vif.clk);vif.cfg_valid=1;vif.cfg_data=item.cfg[k].data;
    vif.cfg_last=item.kind==CFG_PARTIAL?0:1'(item.cfg[k].last);
    do @(vif.sample);while(!vif.sample.cfg_ready);
   end
   if(count>0) begin @(negedge vif.clk);vif.cfg_valid=0;vif.cfg_last=0;end
   if(item.kind==CFG_PARTIAL) begin
    @(vif.sample);
    if(vif.sample.configured!==1'b0) `uvm_fatal("CONFIG","Partial DSP configuration already completed")
   end else begin
    guard=0;
    while(vif.sample.configured!==1'b1) begin
     @(vif.sample);guard++;
     if(guard>20000||vif.sample.error) `uvm_fatal("CONFIG","DSP configuration did not complete")
    end
   end
  endtask
  task drive(dsp_item item);
   int count;expected.write(item);configure(item);
   if(item.kind==CFG_PARTIAL) return;
   count=item.kind==PARTIAL?((item.source.size()>1)?item.source.size()/2:1):item.source.size();
   if(item.kind==TERMINAL) hold_last=1;
   if(item.kind==WEIGHT_TERMINAL) hold_weight_last=1;
   for(int k=0;k<count;k++) begin
    if(scenario=="gaps"&&item.source[k].gap>0) begin
     @(negedge vif.clk);vif.s_valid=0;
     do @(vif.sample);while(!vif.sample.s_ready);
     repeat(item.source[k].gap) @(vif.sample);
    end
    @(negedge vif.clk);vif.s_valid=1;vif.s_data=item.source[k].data;
    vif.s_last=item.kind==PARTIAL?0:1'(item.source[k].last);
    do @(vif.sample);while(!vif.sample.s_ready);
   end
   @(negedge vif.clk);vif.s_valid=0;vif.s_last=0;
   if(item.kind==TERMINAL) begin
    do @(vif.sample);while(!(vif.sample.m_valid&&vif.sample.m_last&&!vif.sample.m_ready));
    repeat(5) @(vif.sample);
   end else if(item.kind==WEIGHT_TERMINAL) begin
    do @(vif.sample);while(!(vif.sample.w_valid&&vif.sample.w_last&&!vif.sample.w_ready));
    while(vif.sample.m_valid) @(vif.sample);
    repeat(5) @(vif.sample);
   end else if(item.kind==PARTIAL) repeat(3) @(vif.sample);
  endtask
  task run_phase(uvm_phase phase);
   fork
    begin
     int cycles=0,weight_pause=0;bit weight_burst=0;
     forever begin
      @(negedge vif.clk);cycles++;
      vif.m_ready=(vif.rst==vif.ACTIVE)||(!(hold_last&&vif.m_valid&&vif.m_last)&&
       (!(scenario inside {"stalled","outreset","woutreset","midreset","cfgreset"})||((cycles%7)!=0&&(cycles%31)<25)));
      if(vif.rst==vif.ACTIVE||!vif.w_valid) begin weight_burst=0;weight_pause=0;end
      else if(!weight_burst) begin weight_burst=1;weight_pause=3;end
      vif.w_ready=(vif.rst==vif.ACTIVE)||(!(hold_weight_last&&vif.w_valid&&vif.w_last)&&
       (!(scenario inside {"stalled","outreset","woutreset","midreset","cfgreset"})||((cycles%11)!=0&&(cycles%19)<15))&&
       (scenario!="stalled"||weight_pause==0));
      if(weight_pause>0) weight_pause--;
     end
    end
   join_none
   reset_dut();
   forever begin
    dsp_item item;seq_item_port.get_next_item(item);
    if(item.kind==RESET) reset_dut();else drive(item);
    seq_item_port.item_done();
   end
  endtask
 endclass

 class dsp_monitor extends uvm_monitor;
  `uvm_component_utils(dsp_monitor)
  virtual dsp_uvm_if vif;uvm_analysis_port #(dsp_item) observed;
  int configs=0,inputs=0,outputs=0,cfg_stalls=0,input_stalls=0,output_stalls=0,gaps=0,pending_resets=0;
  int weights=0,weight_stalls=0,pending_weight_resets=0;
  function new(string name,uvm_component parent);super.new(name,parent);observed=new("observed",this);endfunction
  function void build_phase(uvm_phase phase);
   if(!uvm_config_db#(virtual dsp_uvm_if)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing DSP monitor interface")
  endfunction
  task run_phase(uvm_phase phase);
   bit was_reset=0,frame_open=0;
   forever begin
    dsp_item item;@(vif.sample);
    if($isunknown(vif.sample.rst)) `uvm_fatal("PROTOCOL","Unknown DSP reset")
    if(vif.sample.rst==vif.ACTIVE) begin
     if(!was_reset) begin
      item=dsp_item::type_id::create("fence");item.kind=FENCE;item.pending=vif.sample.m_valid===1'b1;item.pending_weight=vif.sample.w_valid===1'b1;
      if(item.pending_weight) pending_weight_resets++;
      if(item.pending) pending_resets++;observed.write(item);
     end
     was_reset=1;frame_open=0;
    end else begin
     was_reset=0;
     if($isunknown({vif.sample.cfg_valid,vif.sample.cfg_ready,vif.sample.configured,vif.sample.error,
        vif.sample.s_valid,vif.sample.s_ready,vif.sample.m_valid,vif.sample.m_ready})) `uvm_fatal("PROTOCOL","Unknown DSP controls")
     if($isunknown({vif.sample.w_valid,vif.sample.w_ready})) `uvm_fatal("PROTOCOL","Unknown DSP weight controls")
     if(vif.sample.w_valid&&$isunknown({vif.sample.w_data,vif.sample.w_last})) `uvm_fatal("NUMERIC","Unknown valid DSP weights")
     if(vif.sample.w_valid&&!vif.sample.w_ready) weight_stalls++;
     if(vif.sample.w_valid&&vif.sample.w_ready) begin
      item=dsp_item::type_id::create("weight");item.kind=WEIGHT_EVENT;weights++;
      item.actual.data={476'd0,vif.sample.w_data};item.actual.last=int'(vif.sample.w_last);observed.write(item);
     end
     if(vif.sample.error) `uvm_fatal("ERROR","Unexpected DSP error")
     if(vif.sample.cfg_valid&&$isunknown({vif.sample.cfg_data,vif.sample.cfg_last})) `uvm_fatal("NUMERIC","Unknown valid DSP configuration")
     if(vif.sample.s_valid&&$isunknown({vif.sample.s_data,vif.sample.s_last})) `uvm_fatal("NUMERIC","Unknown valid DSP input")
     if(vif.sample.m_valid&&$isunknown({vif.sample.m_data,vif.sample.m_last})) `uvm_fatal("NUMERIC","Unknown valid DSP output")
     if(vif.sample.cfg_valid&&!vif.sample.cfg_ready) cfg_stalls++;
     if(vif.sample.s_valid&&!vif.sample.s_ready) input_stalls++;
     if(vif.sample.m_valid&&!vif.sample.m_ready) output_stalls++;
     if(frame_open&&!vif.sample.s_valid&&vif.sample.s_ready) gaps++;
     if(vif.sample.cfg_valid&&vif.sample.cfg_ready) begin
      item=dsp_item::type_id::create("config");item.kind=CONFIG_EVENT;configs++;
      item.actual.data=vif.sample.cfg_data;item.actual.last=int'(vif.sample.cfg_last);observed.write(item);
     end
     if(vif.sample.s_valid&&vif.sample.s_ready) begin
      item=dsp_item::type_id::create("input");item.kind=INPUT_EVENT;inputs++;
      item.actual.data=vif.sample.s_data;item.actual.last=int'(vif.sample.s_last);frame_open=!vif.sample.s_last;observed.write(item);
     end
     if(vif.sample.m_valid&&vif.sample.m_ready) begin
      item=dsp_item::type_id::create("output");item.kind=OUTPUT_EVENT;outputs++;
      item.actual.data=vif.sample.m_data;item.actual.last=int'(vif.sample.m_last);observed.write(item);
     end
    end
   end
  endtask
 endclass

 class dsp_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(dsp_scoreboard)
  uvm_analysis_imp_dsp_expected #(dsp_item,dsp_scoreboard) expected;
  uvm_analysis_imp_dsp_observed #(dsp_item,dsp_scoreboard) observed;
  dsp_item cfg_frames[$],input_frames[$],output_frames[$],weight_frames[$];
  int ci=0,si=0,mi=0,checked_cfg=0,checked_in=0,checked_out=0,expected_cfg=0,expected_in=0,expected_out=0;
  int discarded_cfg=0,discarded_in=0,discarded_out=0,resets=0,normal=0,completed=0,before_reset=0,terminal_resets=0,warm_outputs=0;
  int wi=0,checked_w=0,expected_w=0,discarded_w=0,completed_weights=0,warm_weights=0,before_weight_reset=0,terminal_weight_resets=0;
  function new(string name,uvm_component parent);super.new(name,parent);endfunction
  function void build_phase(uvm_phase phase);expected=new("expected",this);observed=new("observed",this);endfunction
  function void write_dsp_expected(dsp_item item);
   if(item.cfg.size()>0) cfg_frames.push_back(item);
   input_frames.push_back(item);output_frames.push_back(item);
   if(item.weights.size()>0) weight_frames.push_back(item);expected_w+=item.weights.size();
   expected_cfg+=item.cfg.size();expected_in+=item.source.size();expected_out+=item.golden.size();
   if(item.kind==NORMAL) normal++;
  endfunction
  function void write_dsp_observed(dsp_item item);
   dsp_item frame;dsp_row_t golden;
   if(item.kind==FENCE) begin
    before_reset+=warm_outputs;warm_outputs=0;before_weight_reset+=warm_weights;warm_weights=0;
    if(weight_frames.size()>0&&weight_frames[0].kind==WEIGHT_TERMINAL&&item.pending_weight&&wi==weight_frames[0].weights.size()-1) terminal_weight_resets++;
    foreach(weight_frames[f]) discarded_w+=weight_frames[f].weights.size()-(f==0?wi:0);
    weight_frames.delete();wi=0;
    if(output_frames.size()>0&&output_frames[0].kind==TERMINAL&&item.pending&&mi==output_frames[0].golden.size()-1) terminal_resets++;
    foreach(cfg_frames[f]) discarded_cfg+=cfg_frames[f].cfg.size()-(f==0?ci:0);
    foreach(input_frames[f]) discarded_in+=input_frames[f].source.size()-(f==0?si:0);
    foreach(output_frames[f]) discarded_out+=output_frames[f].golden.size()-(f==0?mi:0);
    cfg_frames.delete();input_frames.delete();output_frames.delete();ci=0;si=0;mi=0;resets++;
   end else if(item.kind==CONFIG_EVENT) begin
    if(cfg_frames.size()==0) `uvm_fatal("COUNT","Unexpected DSP configuration")
    frame=cfg_frames[0];golden=frame.cfg[ci];if(frame.kind==CFG_PARTIAL) golden.last=0;
    if(item.actual.data!==golden.data||item.actual.last!=golden.last) `uvm_fatal("NUMERIC","Accepted DSP configuration differs from source")
    checked_cfg++;ci++;
    if(ci==frame.cfg.size()) begin frame=cfg_frames.pop_front();ci=0;end
   end else if(item.kind==INPUT_EVENT) begin
    if(input_frames.size()==0) `uvm_fatal("COUNT","Unexpected DSP input")
    frame=input_frames[0];golden=frame.source[si];if(frame.kind==PARTIAL) golden.last=0;
    if(item.actual.data!==golden.data||item.actual.last!=golden.last) `uvm_fatal("NUMERIC","Accepted DSP input differs from source")
    checked_in++;si++;
    if(si==frame.source.size()) begin frame=input_frames.pop_front();si=0;end
   end else if(item.kind==WEIGHT_EVENT) begin
    if(weight_frames.size()==0) `uvm_fatal("COUNT","Unexpected DSP weight after reset/drain")
    frame=weight_frames[0];golden=frame.weights[wi];
    if($test$plusargs("INJECT_WEIGHT_MISMATCH")&&frame.kind==NORMAL&&frame.frame==0&&wi==0) golden.data^=512'd1;
    if(item.actual.data!==golden.data||item.actual.last!=golden.last) `uvm_fatal("NUMERIC","Final DSP weight differs from native model")
    checked_w++;if(frame.kind!=NORMAL) warm_weights++;wi++;
    if(wi==frame.weights.size()) begin
     if(frame.kind==NORMAL) begin completed_weights++;$display("UVM DSP WEIGHT_FRAME id=%0d outputs=%0d",frame.frame,frame.weights.size());end
     frame=weight_frames.pop_front();wi=0;
    end
   end else if(item.kind==OUTPUT_EVENT) begin
    if(output_frames.size()==0) `uvm_fatal("COUNT","Unexpected DSP output after reset/drain")
    frame=output_frames[0];golden=frame.golden[mi];
    if(frame.kind==PARTIAL) golden.last=0;
    if($test$plusargs("INJECT_MISMATCH")&&frame.kind==NORMAL&&frame.frame==0&&mi==0) golden.data^=512'd1;
    if(item.actual.data!==golden.data||item.actual.last!=golden.last)
     `uvm_fatal("NUMERIC",$sformatf("DSP frame=%0d row=%0d got=%h/%0d expected=%h/%0d",frame.frame,mi,item.actual.data,item.actual.last,golden.data,golden.last))
    checked_out++;if(frame.kind!=NORMAL) warm_outputs++;mi++;
    if(mi==frame.golden.size()) begin
     if(frame.kind==NORMAL) begin
      if(!item.actual.last) `uvm_fatal("COUNT","Missing terminal DSP output")
      completed++;$display("UVM DSP FRAME id=%0d inputs=%0d outputs=%0d",frame.frame,frame.source.size(),frame.golden.size());
     end
     frame=output_frames.pop_front();mi=0;
    end
   end else `uvm_fatal("PROTOCOL","Unknown DSP observation")
  endfunction
  function void check_phase(uvm_phase phase);
   if(cfg_frames.size()!=0||input_frames.size()!=0||output_frames.size()!=0||ci!=0||si!=0||mi!=0||completed!=normal||normal<1||
      checked_cfg+discarded_cfg!=expected_cfg||checked_in+discarded_in!=expected_in||checked_out+discarded_out!=expected_out||
      weight_frames.size()!=0||wi!=0||checked_w+discarded_w!=expected_w||completed_weights!=((`DSP_KIND==20||`DSP_KIND==21)?normal:0))
    `uvm_error("COUNT","DSP configuration/frame/queue conservation did not drain")
  endfunction
  function void report_phase(uvm_phase phase);
   `uvm_info("WEIGHTS",$sformatf("UVM DSP WEIGHTS checked=%0d expected=%0d discarded=%0d before_reset=%0d frames=%0d terminal_resets=%0d",checked_w,expected_w,discarded_w,before_weight_reset,completed_weights,terminal_weight_resets),UVM_LOW)
   `uvm_info("RESULT",$sformatf("UVM DSP checked=%0d inputs=%0d configs=%0d frames=%0d discarded=%0d discarded_inputs=%0d discarded_configs=%0d expected=%0d expected_inputs=%0d expected_configs=%0d resets=%0d before_reset=%0d terminal_resets=%0d",checked_out,checked_in,checked_cfg,completed,discarded_out,discarded_in,discarded_cfg,expected_out,expected_in,expected_cfg,resets,before_reset,terminal_resets),UVM_LOW)
  endfunction
 endclass

 class dsp_env extends uvm_env;
  `uvm_component_utils(dsp_env)
  uvm_sequencer #(dsp_item) sequencer;dsp_driver driver;dsp_monitor monitor;dsp_scoreboard scoreboard;
  function new(string name,uvm_component parent);super.new(name,parent);endfunction
  function void build_phase(uvm_phase phase);
   sequencer=new("sequencer",this);driver=dsp_driver::type_id::create("driver",this);monitor=dsp_monitor::type_id::create("monitor",this);scoreboard=dsp_scoreboard::type_id::create("scoreboard",this);
  endfunction
  function void connect_phase(uvm_phase phase);
   driver.seq_item_port.connect(sequencer.seq_item_export);driver.expected.connect(scoreboard.expected);monitor.observed.connect(scoreboard.observed);
  endfunction
 endclass
 class dsp_test extends uvm_test;
  `uvm_component_utils(dsp_test)
  dsp_env env;
  function new(string name,uvm_component parent);super.new(name,parent);endfunction
  function void build_phase(uvm_phase phase);env=dsp_env::type_id::create("env",this);endfunction
  task run_phase(uvm_phase phase);
   dsp_sequence seq;phase.raise_objection(this);seq=dsp_sequence::type_id::create("plan");seq.start(env.sequencer);
   wait(env.scoreboard.completed==seq.frames.size()&&env.scoreboard.completed_weights==((`DSP_KIND==20||`DSP_KIND==21)?seq.frames.size():0));repeat(100) @(env.driver.vif.sample);phase.drop_objection(this);
  endtask
  function void check_phase(uvm_phase phase);
   if(env.monitor.configs!=env.scoreboard.checked_cfg||env.monitor.inputs!=env.scoreboard.checked_in||env.monitor.outputs!=env.scoreboard.checked_out||env.monitor.weights!=env.scoreboard.checked_w)
    `uvm_error("COUNT","DSP monitor/scoreboard handshake mismatch")
  endfunction
  function void report_phase(uvm_phase phase);
   `uvm_info("WEIGHT_HANDSHAKES",$sformatf("UVM DSP WEIGHT_HANDSHAKES outputs=%0d stalls=%0d pending_resets=%0d",env.monitor.weights,env.monitor.weight_stalls,env.monitor.pending_weight_resets),UVM_LOW)
   `uvm_info("KIND",$sformatf("UVM DSP KIND id=%0d",`DSP_KIND),UVM_LOW)
   `uvm_info("PARAMETERS",$sformatf("UVM DSP PARAMETERS log2n=%0d cp=%0d log2hop=%0d lanes=%0d tmax=%0d",`DSP_LOG2N,`DSP_CP,`DSP_LOG2HOP,`DSP_LOG2LANES,`DSP_LOG2TMAX),UVM_LOW)
   `uvm_info("MEMORY",$sformatf("UVM DSP MEMORY mmax=%0d kmax=%0d emax=%0d",`DSP_LOG2MMAX,`DSP_LOG2KMAX,`DSP_LOG2EMAX),UVM_LOW)
   `uvm_info("EXTRA",$sformatf("UVM DSP EXTRA log2m=%0d log2nmax=%0d",`DSP_LOG2M,`DSP_LOG2NMAX),UVM_LOW)
   `uvm_info("HANDSHAKES",$sformatf("UVM DSP HANDSHAKES config=%0d input=%0d output=%0d cfg_stalls=%0d input_stalls=%0d output_stalls=%0d gaps=%0d pending_resets=%0d",env.monitor.configs,env.monitor.inputs,env.monitor.outputs,env.monitor.cfg_stalls,env.monitor.input_stalls,env.monitor.output_stalls,env.monitor.gaps,env.monitor.pending_resets),UVM_LOW)
  endfunction
 endclass
endpackage
