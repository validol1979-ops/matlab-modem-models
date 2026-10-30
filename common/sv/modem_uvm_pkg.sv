`include "uvm_macros.svh"
package modem_uvm_pkg;
  timeunit 1ns; timeprecision 1ps;
  import uvm_pkg::*;
  import modem_dsp_pkg::*;

  class modem_item extends uvm_sequence_item;
    `uvm_object_utils(modem_item)
    int case_id, training_count,branches;
    labels_t data, recovered;
    samples_t channel_wave, tx_wave, symbols;
    samples_t channel_wave_b;
    complex_t gain_a,gain_b;
    real delay,frequency;
    function new(string name="modem_item"); super.new(name); endfunction
  endclass

  class modem_sequence extends uvm_sequence #(modem_item);
    `uvm_object_utils(modem_sequence)
    function new(string name="modem_sequence"); super.new(name); endfunction
    task body();
      modem_item item;
      string directory,filename;
      int fd,ndata,nrx,ntx,fields;
      if(!$value$plusargs("VECTORS=%s",directory)) `uvm_fatal("INPUT","Missing VECTORS argument")
      for(int c=0;c<4;c++) begin
        item=modem_item::type_id::create($sformatf("frame_%0d",c));
        item.case_id=c;
        // Последний кадр проверяет повторяемость после очистки выходов интерфейса.
        filename=$sformatf("%s/case_%0d.txt",directory,c%3);
        fd=$fopen(filename,"r");
        if(!fd) `uvm_fatal("INPUT",$sformatf("Cannot open %s",filename))
        fields=$fscanf(fd,"%d %d %d %d %d\n",ndata,nrx,ntx,item.training_count,item.branches);
        if(fields!=5 || ndata<32 || nrx<ndata || ntx<ndata || !(item.branches inside {1,2})) `uvm_fatal("INPUT","Invalid vector header")
        item.data=new[ndata]; item.recovered=new[ndata]; item.symbols=new[ndata];
        item.channel_wave=new[nrx]; item.tx_wave=new[ntx];
        foreach(item.data[k]) if($fscanf(fd,"%d\n",item.data[k])!=1) `uvm_fatal("INPUT","Truncated data")
        foreach(item.channel_wave[k])
          if($fscanf(fd,"%f %f\n",item.channel_wave[k].re,item.channel_wave[k].im)!=2) `uvm_fatal("INPUT","Truncated channel")
        if(item.branches==2) begin
          item.channel_wave_b=new[nrx];
          foreach(item.channel_wave_b[k])
            if($fscanf(fd,"%f %f\n",item.channel_wave_b[k].re,item.channel_wave_b[k].im)!=2) `uvm_fatal("INPUT","Truncated second branch")
          if($fscanf(fd,"%f %f %f %f\n",item.gain_a.re,item.gain_a.im,item.gain_b.re,item.gain_b.im)!=4) `uvm_fatal("INPUT","Truncated branch gains")
        end
        foreach(item.tx_wave[k])
          if($fscanf(fd,"%f %f\n",item.tx_wave[k].re,item.tx_wave[k].im)!=2) `uvm_fatal("INPUT","Truncated transmit reference")
        foreach(item.recovered[k]) if($fscanf(fd,"%d\n",item.recovered[k])!=1) `uvm_fatal("INPUT","Truncated receive reference")
        foreach(item.symbols[k])
          if($fscanf(fd,"%f %f\n",item.symbols[k].re,item.symbols[k].im)!=2) `uvm_fatal("INPUT","Truncated symbol reference")
        if($fscanf(fd,"%f %f\n",item.delay,item.frequency)!=2) `uvm_fatal("INPUT","Truncated estimates")
        $fclose(fd);
        if(c==0 && $test$plusargs("INJECT_MISMATCH")) item.tx_wave[0].re+=1;
        start_item(item); finish_item(item);
      end
    endtask
  endclass

  class modem_driver extends uvm_driver #(modem_item);
    `uvm_component_utils(modem_driver)
    virtual modem_if vif;
    uvm_analysis_port #(modem_item) expected;
    function new(string name,uvm_component parent); super.new(name,parent); expected=new("expected",this); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if(!uvm_config_db#(virtual modem_if)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing interface")
    endfunction
    task run_phase(uvm_phase phase);
      modem_item item;
      vif.valid=0; vif.rst_n=0;
      repeat(3) @(negedge vif.clk); vif.rst_n=1;
      forever begin
        seq_item_port.get_next_item(item);
        if(item.case_id==3) begin
          vif.rst_n=0; repeat(2) @(negedge vif.clk);
          if(vif.done || vif.output_data.size()!=0) `uvm_error("RESET","Reset did not clear output")
          vif.rst_n=1;
        end
        expected.write(item);
        repeat(1+item.case_id%3) @(negedge vif.clk);
        vif.case_id=item.case_id; vif.training_count=item.training_count;
        vif.branches=item.branches; vif.input_wave_b=item.channel_wave_b;
        vif.gain_a=item.gain_a; vif.gain_b=item.gain_b;
        vif.input_data=item.data; vif.input_wave=item.channel_wave; vif.valid=1;
        @(negedge vif.clk); vif.valid=0;
        if(!vif.done) `uvm_fatal("PROTOCOL","Response missing after frame request")
        seq_item_port.item_done();
      end
    endtask
  endclass

  class modem_monitor extends uvm_monitor;
    `uvm_component_utils(modem_monitor)
    virtual modem_if vif;
    uvm_analysis_port #(modem_item) observed;
    function new(string name,uvm_component parent); super.new(name,parent); observed=new("observed",this); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if(!uvm_config_db#(virtual modem_if)::get(this,"","vif",vif)) `uvm_fatal("CONFIG","Missing interface")
    endfunction
    task run_phase(uvm_phase phase);
      modem_item item;
      forever begin
        @(posedge vif.clk); #1ns;
        if(vif.rst_n && vif.done) begin
          item=modem_item::type_id::create("observed_frame");
          item.case_id=vif.case_id; item.tx_wave=vif.output_wave;
          item.recovered=vif.output_data; item.symbols=vif.output_symbols;
          item.delay=vif.estimated_delay; item.frequency=vif.estimated_frequency;
          observed.write(item);
        end
      end
    endtask
  endclass

  class modem_scoreboard extends uvm_scoreboard;
    `uvm_component_utils(modem_scoreboard)
    uvm_tlm_analysis_fifo #(modem_item) expected,observed;
    int checked_frames=0,checked_samples=0;
    real maximum_error=0;
    bit covered[4];
    function new(string name,uvm_component parent);
      super.new(name,parent); expected=new("expected",this); observed=new("observed",this);
    endfunction
    function void compare_samples(string label, samples_t actual,reference);
      real error_value;
      if(actual.size()!=reference.size()) `uvm_fatal("SIZE",$sformatf("%s length mismatch",label))
      foreach(actual[k]) begin
        error_value=$sqrt(power(sub(actual[k],reference[k])));
        // Отрицательная форма также отклоняет NaN.
        if(!(error_value<=1e-7)) `uvm_fatal("NUMERIC",$sformatf("%s sample %0d error %.12g",label,k,error_value))
        if(error_value>maximum_error) maximum_error=error_value;
        checked_samples++;
      end
    endfunction
    task run_phase(uvm_phase phase);
      modem_item e,a;
      forever begin
        expected.get(e); observed.get(a);
        if(a.case_id!=e.case_id) `uvm_fatal("ORDER","Frame order mismatch")
        compare_samples("TX",a.tx_wave,e.tx_wave); compare_samples("RX",a.symbols,e.symbols);
        if(a.recovered.size()!=e.recovered.size()) `uvm_fatal("SIZE","Recovered frame length mismatch")
        foreach(a.recovered[k]) begin
          if(a.recovered[k]!=e.recovered[k]) `uvm_fatal("DATA",$sformatf("Decoded symbol mismatch at %0d",k))
          if(k>=e.training_count && a.recovered[k]!=e.data[k]) `uvm_fatal("PAYLOAD",$sformatf("Payload error at %0d",k))
        end
        if(!(a.delay-e.delay inside {[-1e-8:1e-8]})) `uvm_fatal("TIMING","Delay estimate mismatch")
        if(!(a.frequency-e.frequency inside {[-1e-10:1e-10]})) `uvm_fatal("CARRIER","Frequency estimate mismatch")
        checked_frames++; covered[a.case_id]=1;
      end
    endtask
    function void check_phase(uvm_phase phase);
      super.check_phase(phase);
      if(checked_frames!=4 || !expected.is_empty() || !observed.is_empty()) `uvm_error("COUNT","Missing or extra frames")
      foreach(covered[k]) if(!covered[k]) `uvm_error("COVERAGE","Missing frame scenario")
    endfunction
    function void report_phase(uvm_phase phase);
      `uvm_info("RESULT",$sformatf("Checked %0d frames, %0d complex samples; maximum error %.12g",checked_frames,checked_samples,maximum_error),UVM_LOW)
    endfunction
  endclass

  class modem_env extends uvm_env;
    `uvm_component_utils(modem_env)
    uvm_sequencer #(modem_item) sequencer;
    modem_driver driver;
    modem_monitor monitor;
    modem_scoreboard scoreboard;
    function new(string name,uvm_component parent); super.new(name,parent); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      sequencer=new("sequencer",this);
      driver=modem_driver::type_id::create("driver",this);
      monitor=modem_monitor::type_id::create("monitor",this);
      scoreboard=modem_scoreboard::type_id::create("scoreboard",this);
    endfunction
    function void connect_phase(uvm_phase phase);
      driver.seq_item_port.connect(sequencer.seq_item_export);
      driver.expected.connect(scoreboard.expected.analysis_export);
      monitor.observed.connect(scoreboard.observed.analysis_export);
    endfunction
  endclass

  class modem_test extends uvm_test;
    `uvm_component_utils(modem_test)
    modem_env env;
    function new(string name,uvm_component parent); super.new(name,parent); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase); env=modem_env::type_id::create("env",this);
    endfunction
    task run_phase(uvm_phase phase);
      modem_sequence seq;
      phase.raise_objection(this);
      seq=modem_sequence::type_id::create("sequence"); seq.start(env.sequencer);
      repeat(3) @(negedge env.driver.vif.clk);
      phase.drop_objection(this);
    endtask
  endclass
endpackage
