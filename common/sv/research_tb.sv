interface research_if(input logic clk);
  import modem_dsp_pkg::*;
  logic rst_n=0,valid=0,done=0;
  int operation,case_id;
  taps_t parameters;
  samples_t signal_in,auxiliary,result;
endinterface

module research_model(research_if bus);
  import research_dsp_pkg::*;
  // Поведенческая обработка одного блока; ожидаемые ответы отсутствуют на интерфейсе.
  always @(posedge bus.clk) begin
    bus.done<=0;
    if(!bus.rst_n) bus.result.delete();
    else if(bus.valid) begin
      bus.result=execute(bus.operation,bus.parameters,bus.signal_in,bus.auxiliary);bus.done<=1;
    end
  end
endmodule

`include "uvm_macros.svh"
package research_uvm_pkg;
  import uvm_pkg::*;
  import modem_dsp_pkg::*;
  class dsp_item extends uvm_sequence_item;
    `uvm_object_utils(dsp_item)
    int operation,case_id,total_cases;
    taps_t parameters;
    samples_t signal_in,auxiliary,result;
    function new(string name="item");super.new(name);endfunction
  endclass
  class dsp_sequence extends uvm_sequence #(dsp_item);
    `uvm_object_utils(dsp_sequence)
    function new(string name="sequence");super.new(name);endfunction
    task body();
      string filename;int fd,n,np,nx,na,ny,op;dsp_item item;
      if(!$value$plusargs("VECTORS=%s",filename)) `uvm_fatal("INPUT","Missing VECTORS")
      for(int repeat_index=0;repeat_index<2;repeat_index++) begin
        fd=$fopen(filename,"r");if(!fd) `uvm_fatal("INPUT","Cannot open vectors")
        if($fscanf(fd,"%d",n)!=1) `uvm_fatal("INPUT","Missing case count")
        for(int k=0;k<n;k++) begin
          item=dsp_item::type_id::create("transaction");item.case_id=repeat_index*n+k;item.total_cases=n;
          if($fscanf(fd,"%d %d %d %d %d",op,np,nx,na,ny)!=5) `uvm_fatal("INPUT","Invalid header")
          item.operation=op;item.parameters=new[np];item.signal_in=new[nx];item.auxiliary=new[na];item.result=new[ny];
          foreach(item.parameters[j]) if($fscanf(fd,"%f",item.parameters[j])!=1) `uvm_fatal("INPUT","Truncated parameters")
          foreach(item.signal_in[j]) if($fscanf(fd,"%f %f",item.signal_in[j].re,item.signal_in[j].im)!=2) `uvm_fatal("INPUT","Truncated signal")
          foreach(item.auxiliary[j]) if($fscanf(fd,"%f %f",item.auxiliary[j].re,item.auxiliary[j].im)!=2) `uvm_fatal("INPUT","Truncated auxiliary")
          foreach(item.result[j]) if($fscanf(fd,"%f %f",item.result[j].re,item.result[j].im)!=2) `uvm_fatal("INPUT","Truncated expectation")
          if(k==0 && $test$plusargs("INJECT_MISMATCH")) item.result[0].re+=1+$sqrt(power(item.result[0]));
          start_item(item);finish_item(item);
        end
        $fclose(fd);
      end
    endtask
  endclass
  class dsp_driver extends uvm_driver #(dsp_item);
    `uvm_component_utils(dsp_driver)
    virtual research_if vif;uvm_analysis_port #(dsp_item) expected;
    function new(string name,uvm_component parent);super.new(name,parent);expected=new("expected",this);endfunction
    function void build_phase(uvm_phase phase);
      if(!uvm_config_db#(virtual research_if)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing interface")
    endfunction
    task run_phase(uvm_phase phase);
      dsp_item item;vif.valid=0;vif.rst_n=0;repeat(3) @(negedge vif.clk);vif.rst_n=1;
      forever begin
        seq_item_port.get_next_item(item);
        if(item.case_id==item.total_cases) begin
          vif.rst_n=0;repeat(2) @(negedge vif.clk);
          if(vif.done || vif.result.size()!=0) `uvm_fatal("RESET","Reset did not clear output")
          vif.rst_n=1;
        end
        expected.write(item);repeat(1+item.case_id%3) @(negedge vif.clk);
        vif.case_id=item.case_id;vif.operation=item.operation;vif.parameters=item.parameters;
        vif.signal_in=item.signal_in;vif.auxiliary=item.auxiliary;vif.valid=1;
        @(negedge vif.clk);vif.valid=0;if(!vif.done) `uvm_fatal("PROTOCOL","Missing response")
        seq_item_port.item_done();
      end
    endtask
  endclass
  class dsp_monitor extends uvm_monitor;
    `uvm_component_utils(dsp_monitor)
    virtual research_if vif;uvm_analysis_port #(dsp_item) observed;
    function new(string name,uvm_component parent);super.new(name,parent);observed=new("observed",this);endfunction
    function void build_phase(uvm_phase phase);
      if(!uvm_config_db#(virtual research_if)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing interface")
    endfunction
    task run_phase(uvm_phase phase);
      dsp_item item;
      forever begin
        @(posedge vif.clk);#1ns;
        if(vif.rst_n && vif.done) begin
          item=dsp_item::type_id::create("observed");item.case_id=vif.case_id;item.operation=vif.operation;item.result=vif.result;observed.write(item);
        end
      end
    endtask
  endclass
  class dsp_scoreboard extends uvm_scoreboard;
    `uvm_component_utils(dsp_scoreboard)
    uvm_tlm_analysis_fifo #(dsp_item) expected,observed;
    int checked=0,values=0,expected_count=0;real maximum_error=0;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);expected=new("expected",this);observed=new("observed",this);endfunction
    task run_phase(uvm_phase phase);
      dsp_item e,a;real err,limit;
      forever begin
        expected.get(e);observed.get(a);expected_count=2*e.total_cases;
        if(a.case_id!=e.case_id || a.operation!=e.operation || a.result.size()!=e.result.size()) `uvm_fatal("TRANSACTION","Metadata or length mismatch")
        foreach(e.result[k]) begin
          err=$sqrt(power(sub(a.result[k],e.result[k])));limit=1e-8*(1+$sqrt(power(e.result[k])));
          if(!(err<=limit)) `uvm_fatal("NUMERIC",$sformatf("Case %0d op %0d sample %0d error %.12g",e.case_id,e.operation,k,err))
          if(err>maximum_error) maximum_error=err;values++;
        end
        checked++;
      end
    endtask
    function void check_phase(uvm_phase phase);
      if(checked!=expected_count || checked==0 || !expected.is_empty() || !observed.is_empty()) `uvm_error("COUNT","Missing or extra transactions")
    endfunction
    function void report_phase(uvm_phase phase);
      `uvm_info("RESULT",$sformatf("Checked %0d DSP transactions, %0d complex values; maximum error %.12g",checked,values,maximum_error),UVM_LOW)
    endfunction
  endclass
  class dsp_test extends uvm_test;
    `uvm_component_utils(dsp_test)
    uvm_sequencer #(dsp_item) sequencer;dsp_driver driver;dsp_monitor monitor;dsp_scoreboard scoreboard;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      sequencer=new("sequencer",this);driver=dsp_driver::type_id::create("driver",this);
      monitor=dsp_monitor::type_id::create("monitor",this);scoreboard=dsp_scoreboard::type_id::create("scoreboard",this);
    endfunction
    function void connect_phase(uvm_phase phase);
      driver.seq_item_port.connect(sequencer.seq_item_export);driver.expected.connect(scoreboard.expected.analysis_export);monitor.observed.connect(scoreboard.observed.analysis_export);
    endfunction
    task run_phase(uvm_phase phase);
      dsp_sequence seq;phase.raise_objection(this);seq=dsp_sequence::type_id::create("sequence");seq.start(sequencer);
      repeat(3) @(negedge driver.vif.clk);phase.drop_objection(this);
    endtask
  endclass
endpackage
module research_tb;
  timeunit 1ns;timeprecision 1ps;
  import uvm_pkg::*;import research_uvm_pkg::*;
  logic clk=0;always #5ns clk=~clk;
  research_if bus(clk);
`ifdef TYPED_VARIANT
  dsp_variant dut(bus);
`else
  research_model dut(bus);
`endif
  initial begin uvm_config_db#(virtual research_if)::set(null,"*","vif",bus);run_test("dsp_test");end
  initial begin #1ms;$fatal(1,"DSP testbench watchdog expired");end
endmodule
