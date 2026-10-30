`timescale 1ns/1ps
module crc_stream_tb #(
  parameter int CRC_WIDTH=32, WORD_BITS=8,
  parameter bit RESET_ACTIVE=1
);
  logic clk, rst;
  initial clk=0;
  always #5 clk=~clk;
  logic cfg_valid, cfg_ready, configured, cfg_reflected, cfg_refout;
  logic [1:0] cfg_mode;
  logic [CRC_WIDTH-1:0] cfg_poly, cfg_init, cfg_xorout;
  logic s_valid, s_ready, s_last, m_valid, m_ready, m_last, m_ok, error;
  logic [WORD_BITS-1:0] s_data, m_data;
  logic [5:0] s_nbits, m_nbits;
  logic [CRC_WIDTH-1:0] m_crc;
  crc_stream #(.CRC_WIDTH(CRC_WIDTH),.WORD_BITS(WORD_BITS),.RESET_ACTIVE(RESET_ACTIVE)) dut(.*);
  axis_check #(.WIDTH(WORD_BITS+6),.RESET_ACTIVE(RESET_ACTIVE),.NAME("crc input")) ci
    (clk,rst,s_valid,s_ready,s_last,{s_nbits,s_data});
  axis_check #(.WIDTH(WORD_BITS+CRC_WIDTH+7),.RESET_ACTIVE(RESET_ACTIVE),.NAME("crc output")) co
    (clk,rst,m_valid,m_ready,m_last,{m_ok,m_crc,m_nbits,m_data});
  axis_check #(.WIDTH(3*CRC_WIDTH+4),.RESET_ACTIVE(RESET_ACTIVE),.NAME("crc config")) cc
    (clk,rst,cfg_valid,cfg_ready,1'b1,{cfg_mode,cfg_reflected,cfg_refout,cfg_poly,cfg_init,cfg_xorout});

  logic [WORD_BITS-1:0] idata[0:4095], edata[0:4095];
  logic [5:0] inbits[0:4095], enbits[0:4095];
  logic ilast[0:4095], elast[0:4095], eok[0:4095];
  logic [CRC_WIDTH-1:0] ecrc[0:4095];
  int got, expected_count, total_outputs, total_inputs, cycles;
  int input_stalls, output_stalls, collisions, pending_cycles, rate_pairs;
  int last_accept, latency_checks, due_write;
  int due_cycle[0:4095];
  bit score, transaction_open, no_stall, inject_numeric;
  logic [31:0] rng;
  function automatic logic [31:0] random_next(input logic [31:0] v);
    logic [31:0] t;
    t=v^(v<<13); t=t^(t>>17); return t^(t<<5);
  endfunction
  initial forever begin
    @(posedge clk);
    cycles=cycles+1;
    if (rst == RESET_ACTIVE) begin
      transaction_open=0; last_accept=-100;
    end else begin
      if (cfg_valid && cfg_ready && s_ready) $fatal(1,"[ARBITRATION] cfg priority");
      if (cfg_valid && cfg_ready && s_valid) collisions++;
      if (cfg_valid && !cfg_ready) pending_cycles++;
      if (transaction_open && cfg_ready) $fatal(1,"[ARBITRATION] config inside transaction");
      if (score && no_stall && s_valid && !s_ready && !(cfg_valid && cfg_ready))
        $fatal(1,"[RATE] input bubble inside unstalled transaction");
      if (s_valid && !s_ready) input_stalls++;
      if (m_valid && !m_ready) output_stalls++;
      if (s_valid && s_ready) begin
        if (score) begin
          total_inputs++;
          if (no_stall && last_accept==cycles-1) rate_pairs++;
          last_accept=cycles;
          if (no_stall) begin
            if (cfg_mode==2 || cfg_mode==1 && s_nbits!=0 || cfg_mode==0 && s_last) begin
              due_cycle[due_write]=cycles+1; due_write++;
            end
            if (cfg_mode==1 && s_last)
              for (int j=0;j<(CRC_WIDTH+WORD_BITS-1)/WORD_BITS;j++) begin
                due_cycle[due_write]=cycles+2+j; due_write++;
              end
          end
        end
        transaction_open=1;
      end
      if (m_valid && m_ready) begin
        if (score) begin
          if (got>=expected_count) $fatal(1,"[NUMERIC] extra output");
          if ({m_data,m_nbits,m_last,m_crc,m_ok} !==
              {edata[got],enbits[got],elast[got],ecrc[got] ^ CRC_WIDTH'(inject_numeric && got==0),eok[got]})
            $fatal(1,"[NUMERIC] output %0d data=%h/%h n=%0d/%0d last=%b/%b crc=%h/%h ok=%b/%b",
                   got,m_data,edata[got],m_nbits,enbits[got],m_last,elast[got],m_crc,ecrc[got],m_ok,eok[got]);
          if (no_stall) begin
            if (cycles!=due_cycle[got]) $fatal(1,"[RATE] output cycle %0d expected %0d",cycles,due_cycle[got]);
            latency_checks++;
          end
          got++; total_outputs++;
        end
        if (m_last) transaction_open=0;
      end
    end
  end

  task automatic reset_dut;
    @(negedge clk); rst=RESET_ACTIVE; cfg_valid=0; s_valid=0; m_ready=0; score=0;
    #1;
    if (s_ready || cfg_ready || m_valid) $fatal(1,"[RESET] ready/valid active");
    repeat(2) @(posedge clk);
    @(negedge clk); rst=!RESET_ACTIVE;
    @(negedge clk);
    if (configured || error || m_valid) $fatal(1,"[RESET] state not cleared");
  endtask
  task automatic configure(input logic [1:0] mode_value);
    @(negedge clk); cfg_mode=mode_value; cfg_valid=1;
    do @(posedge clk); while (!cfg_ready);
    @(negedge clk); cfg_valid=0;
  endtask
  task automatic send_word(input logic [WORD_BITS-1:0] data_value,
                           input logic [5:0] count_value, input bit last_value);
    @(negedge clk); s_valid=1; s_data=data_value; s_nbits=count_value; s_last=last_value;
    do @(posedge clk); while (!s_ready);
    @(negedge clk); s_valid=0;
  endtask

  task automatic directed_checks;
    // Reset after accepted nonfinal input, with a pending config and stalled echo.
    configure(1);
    send_word('0,6'(WORD_BITS),0);
    @(negedge clk); cfg_valid=1;
    repeat(4) begin
      @(negedge clk);
      if (cfg_ready || !m_valid) $fatal(1,"[DIRECTED] open frame config/stall");
    end
    reset_dut();
    // Reset during append tail, including an unread final result.
    configure(1);
    send_word('0,0,1);
    repeat(3) @(negedge clk);
    if (!m_valid || cfg_ready) $fatal(1,"[DIRECTED] missing stalled FCS");
    reset_dut();
    // Invalid configuration must halt until reset.
    configure(3);
    if (!error || configured || cfg_ready || s_ready) $fatal(1,"[DIRECTED] bad configuration");
    reset_dut();
    // Malformed word classes, including early partial / zero and dirty padding.
    for (int kind=0; kind<5; kind++) begin
      configure(0);
      case(kind)
        0: send_word('0,6'(WORD_BITS+1),1);
        1: send_word('0,0,0);
        2: send_word('1,0,1);
        3: begin send_word('0,6'(WORD_BITS),0); send_word('0,0,1); end
        4: send_word('0,6'(WORD_BITS-1),0);
      endcase
      if (!error || configured || s_ready || cfg_ready || m_valid)
        $fatal(1,"[DIRECTED] bad word kind=%0d",kind);
      reset_dut();
    end
    // s_ready does not depend on s_valid, both on a free boundary and under cfg.
    configure(0);
    @(negedge clk); s_valid=0; #1;
    if (!s_ready) $fatal(1,"[ARBITRATION] free ready");
    s_valid=1; s_data=0; s_nbits=6'(WORD_BITS); s_last=0; #1;
    if (!s_ready) $fatal(1,"[ARBITRATION] ready depends on valid");
    s_valid=0; cfg_valid=1; #1;
    if (s_ready || !cfg_ready) $fatal(1,"[ARBITRATION] cfg without data");
    s_valid=1; #1;
    if (s_ready) $fatal(1,"[ARBITRATION] cfg with data");
    // Explicit protocol negative control exercises the shared axis_check.
    if ($test$plusargs("INJECT_PROTOCOL")) begin
      @(posedge clk); // input is held by accepted configuration
      @(negedge clk); s_data=1;
      @(posedge clk);
      @(negedge clk);
      $fatal(1,"[CONTROL_MISSING] protocol checker missed mutation");
    end
    reset_dut();
  endtask

  initial begin : run
    string vector_path;
    int fd, count, ni, ne, expected_error, sticky, index, timeout_count;
    bit pending, accepted;
    rst=RESET_ACTIVE; cfg_valid=0; cfg_mode=0; cfg_poly='1; cfg_init='1; cfg_xorout=0;
    cfg_reflected=0; cfg_refout=0; s_valid=0; s_data=0; s_nbits=0; s_last=0; m_ready=0;
    score=0; got=0; expected_count=0; total_outputs=0; total_inputs=0; cycles=0;
    input_stalls=0; output_stalls=0; collisions=0; pending_cycles=0; rate_pairs=0;
    latency_checks=0; due_write=0; rng=32'h1948abcd;
    no_stall=$test$plusargs("NO_STALL"); inject_numeric=$test$plusargs("INJECT_MISMATCH");
    reset_dut(); directed_checks();
    input_stalls=0; output_stalls=0; collisions=0; pending_cycles=0;
    if (!$value$plusargs("VECTORS=%s",vector_path)) $fatal(1,"[VECTOR] missing file");
    fd=$fopen(vector_path,"r");
    if (fd==0 || $fscanf(fd,"%d",count)!=1 || count<1) $fatal(1,"[VECTOR] header");
    sticky=0;
    for (int frame_index=0; frame_index<count; frame_index++) begin
      if ($fscanf(fd,"%d %h %h %h %d %d %d %d %d",cfg_mode,cfg_poly,cfg_init,cfg_xorout,cfg_reflected,cfg_refout,ni,ne,expected_error)!=9)
        $fatal(1,"[VECTOR] frame header");
      if (ni<1 || ni>4096 || ne<1 || ne>4096) $fatal(1,"[VECTOR] bounds");
      for (int j=0;j<ni;j++)
        if ($fscanf(fd,"%h %d %d",idata[j],inbits[j],ilast[j])!=3) $fatal(1,"[VECTOR] input");
      for (int j=0;j<ne;j++)
        if ($fscanf(fd,"%h %d %d %h %d",edata[j],enbits[j],elast[j],ecrc[j],eok[j])!=5)
          $fatal(1,"[VECTOR] expected");
      got=0; due_write=0; expected_count=ne; score=1;
      // Held first word collides with config on every frame.
      @(negedge clk); cfg_valid=1; s_valid=1; s_data=idata[0]; s_nbits=inbits[0]; s_last=ilast[0];
      do @(posedge clk); while (!cfg_ready);
      @(negedge clk); cfg_valid=0; m_ready=1;
      index=0; timeout_count=0; pending=0;
      while (index<ni || got<ne) begin
        @(posedge clk);
        accepted=s_valid && s_ready;
        if (accepted) index++;
        @(negedge clk);
        timeout_count++;
        if (timeout_count>100000) $fatal(1,"[TIMEOUT] frame %0d in=%0d/%0d out=%0d/%0d",frame_index,index,ni,got,ne);
        // Each presented source word stays unchanged until accepted.
        if (!s_valid || accepted) begin
          rng=random_next(rng);
          s_valid=index<ni && (no_stall || rng[1:0]!=0);
          if (index<ni) begin s_data=idata[index]; s_nbits=inbits[index]; s_last=ilast[index]; end
        end
        rng=random_next(rng); m_ready=no_stall || rng[2:0]>2;
        if (ni>3 && index>0 && index<ni && !pending) begin cfg_valid=1; pending=1; end
      end
      s_valid=0; m_ready=1;
      // Last output has been consumed; only now may the pending config complete.
      if (pending) begin
        do @(posedge clk); while (!cfg_ready);
        @(negedge clk); cfg_valid=0;
      end
      sticky=sticky | expected_error;
      if (error !== 1'(sticky)) $fatal(1,"[ERROR_POLICY] sticky mismatch");
      repeat(2) @(negedge clk);
      if (m_valid) $fatal(1,"[NUMERIC] trailing output");
      score=0;
    end
    $fclose(fd);
    if (collisions==0 || pending_cycles==0 || (!no_stall && (input_stalls==0 || output_stalls==0)) ||
        (no_stall && (rate_pairs==0 || latency_checks==0))) $fatal(1,"[COVERAGE] missing protocol/rate events");
    $display("PASS CRC frames=%0d inputs=%0d outputs=%0d collisions=%0d pending=%0d istall=%0d ostall=%0d rate=%0d latency=%0d",
             count,total_inputs,total_outputs,collisions,pending_cycles,input_stalls,output_stalls,rate_pairs,latency_checks);
    $finish;
  end
  initial begin
    #100000000;
    $fatal(1,"[TIMEOUT] global");
  end
endmodule
