`timescale 1ns/1ps
module prbs_scrambler_tb;
  parameter int ORDER = 7;
  parameter int WORD_WIDTH = 1;
  parameter bit RESET_ACTIVE = 1;
  logic clk = 0;
  always #5 clk = ~clk;
  logic rst = RESET_ACTIVE;
  logic cfg_valid = 0, cfg_restart = 0, s_valid = 0, s_last = 0, m_ready = 0;
  logic [1:0] cfg_mode = 0;
  logic [ORDER-1:0] cfg_seed = 0;
  logic [WORD_WIDTH-1:0] s_data = 0;
  wire cfg_ready, configured, error, s_ready, m_valid, m_last;
  wire [WORD_WIDTH-1:0] m_data;
  wire [ORDER-1:0] m_state;
  prbs_scrambler #(.ORDER(ORDER), .WORD_WIDTH(WORD_WIDTH), .RESET_ACTIVE(RESET_ACTIVE)) dut(.*);

  bit scoring = 0, inject_numeric, inject_protocol, stalls;
  integer got = 0, total = 0, sent = 0, cycles = 0;
  integer holds = 0, gaps = 0, consecutive = 0, max_run = 0, prev_cycle = -2;
  integer output_hold = 0, accepted_count = 0;
  integer accept_cycles[0:39999];
  logic [31:0] rng = 32'h914ce721;
  logic [WORD_WIDTH-1:0] xs[0:39999], ys[0:39999];
  logic [ORDER-1:0] states[0:39999];
  logic lasts[0:39999];
  // Negative protocol control changes an actual payload seen by axis_check.
  wire [WORD_WIDTH-1:0] checked_data = m_data ^
    ((scoring && inject_protocol && output_hold >= 2) ? WORD_WIDTH'(1) : '0);
  axis_check #(.WIDTH(WORD_WIDTH), .RESET_ACTIVE(RESET_ACTIVE), .NAME("prbs input")) in_check(
    .clk(clk), .rst(rst), .valid(s_valid), .ready(s_ready), .last(s_last), .data(s_data));
  axis_check #(.WIDTH(WORD_WIDTH+ORDER), .RESET_ACTIVE(RESET_ACTIVE), .NAME("prbs output")) out_check(
    .clk(clk), .rst(rst), .valid(m_valid), .ready(m_ready), .last(m_last), .data({m_state,checked_data}));
  axis_check #(.WIDTH(ORDER+3), .RESET_ACTIVE(RESET_ACTIVE), .NAME("prbs cfg")) cfg_check(
    .clk(clk), .rst(rst), .valid(cfg_valid), .ready(cfg_ready), .last(1'b1),
    .data({cfg_mode,cfg_seed,cfg_restart}));

  always @(posedge clk) begin
    cycles = cycles + 1;
    if (rst == RESET_ACTIVE) output_hold = 0;
    else begin
      if (m_valid && !m_ready) output_hold = output_hold + 1;
      else output_hold = 0;
      if (cfg_valid && cfg_ready && s_ready) $fatal(1,"[PROTOCOL] cfg did not exclude input");
      if (scoring) begin
        if (error || !configured) $fatal(1,"[CONFIG] unexpected error/unconfigured");
        if (m_valid && !m_ready) holds = holds + 1;
        if (!s_valid && s_ready) gaps = gaps + 1;
        if (s_valid && s_ready) begin
          accept_cycles[accepted_count] = cycles;
          accepted_count = accepted_count + 1;
          consecutive = prev_cycle == cycles-1 ? consecutive+1 : 1;
          if (consecutive > max_run) max_run = consecutive;
          prev_cycle = cycles;
        end
        if (m_valid && m_ready) begin
          if (!stalls && cycles != accept_cycles[got]+1) $fatal(1,"[RATE] latency is not one cycle");
          if (got >= total || m_data !== (ys[got] ^ ((inject_numeric && got == 0) ? WORD_WIDTH'(1) : '0)) ||
              m_last !== lasts[got] || m_state !== states[got])
            $fatal(1,"[NUMERIC] word=%0d data=%h expected=%h state=%h expected=%h last=%b",got,m_data,ys[got],m_state,states[got],m_last);
          got = got + 1;
        end
      end
    end
  end

  task automatic reset_core;
    @(negedge clk);
    scoring = 0; rst = RESET_ACTIVE; s_valid = 0; cfg_valid = 0; m_ready = 0;
    #1;
    if (s_ready || m_valid || cfg_ready) $fatal(1,"[RESET] live handshake during reset");
    repeat(3) @(negedge clk);
    rst = !RESET_ACTIVE;
    #1;
    if (configured || error || s_ready || m_valid || !cfg_ready) $fatal(1,"[RESET] state not cleared");
  endtask

  task automatic configure(input logic [1:0] mode_arg, input logic [ORDER-1:0] seed_arg,
                           input bit restart_arg);
    @(negedge clk); cfg_mode = mode_arg; cfg_seed = seed_arg;
    cfg_restart = restart_arg; cfg_valid = 1;
    do @(posedge clk); while (!cfg_ready);
    @(negedge clk); cfg_valid = 0;
  endtask

  task automatic send_word(input logic [WORD_WIDTH-1:0] word_arg, input bit last_arg);
    @(negedge clk); s_valid = 1; s_data = word_arg; s_last = last_arg;
    do @(posedge clk); while (!s_ready);
    @(negedge clk); s_valid = 0;
  endtask

  task automatic directed;
    // All four illegal seed/mode combinations and sticky reset-only recovery.
    for (int mode_index = 0; mode_index < 4; mode_index++) begin
      reset_core();
      configure(2'(mode_index), mode_index < 2 ? ORDER'(0) : ORDER'(1), 0);
      if (!error || configured || cfg_ready || s_ready) $fatal(1,"[CONFIG] bad seed accepted");
      repeat(4) @(negedge clk);
      if (!error) $fatal(1,"[CONFIG] error not sticky");
    end
    reset_core(); configure(1, ORDER'(1), 0);
    // Reconfiguration wins independently of s_valid; the source holds its word.
    @(negedge clk); cfg_valid = 1; cfg_mode = 1; cfg_seed = '1; cfg_restart = 0;
    #1; if (s_ready || !cfg_ready) $fatal(1,"[PROTOCOL] priority with s_valid=0");
    s_valid = 1; s_data = '0; s_last = 0;
    #1; if (s_ready) $fatal(1,"[PROTOCOL] priority with s_valid=1");
    @(posedge clk);
    @(negedge clk); cfg_valid = 0;
    @(posedge clk); if (!s_ready) $fatal(1,"[PROTOCOL] held word did not resume");
    @(negedge clk); s_valid = 0;
    // An unread result must keep cfg_ready low, including on its drain edge.
    repeat(5) begin
      @(negedge clk); if (cfg_ready || !m_valid) $fatal(1,"[PROTOCOL] unread result not busy");
    end
    // A pending configuration during a source gap must not block the open frame.
    cfg_valid = 1; cfg_mode = 0; cfg_seed = ORDER'(1); m_ready = 1;
    repeat(4) begin
      @(negedge clk); if (cfg_ready || !s_ready) $fatal(1,"[PROTOCOL] gap opened config boundary");
    end
    send_word('1, 1);
    if (cfg_ready) $fatal(1,"[PROTOCOL] unread final word allowed config");
    @(posedge clk); // consume final output, config is still blocked
    @(negedge clk); if (!cfg_ready || s_ready) $fatal(1,"[PROTOCOL] pending cfg not prioritised");
    @(posedge clk);
    @(negedge clk); cfg_valid = 0; m_ready = 0;
    if (!configured || error) $fatal(1,"[CONFIG] pending config failed");
    // Reset with an accepted non-final word and a held output cancels both.
    send_word('1, 0); repeat(3) @(negedge clk);
    if (!m_valid || cfg_ready) $fatal(1,"[RESET] no accepted work to cancel");
    reset_core(); configure(3, '0, 0);
    // Separately reset while the final output is stalled.
    send_word('1, 1); repeat(3) @(negedge clk);
    if (!m_valid || !m_last || cfg_ready) $fatal(1,"[RESET] no held final word");
    reset_core();
    $display("PASS PRBS DIRECTED: priority pending_cfg sticky_error midreset outreset");
  endtask

  string vector_file;
  integer fd, count, mode_in, restart_in, nwords, last_in, ncases;
  integer compared = 0, drive_cycles;
  bit accepted;
  logic [ORDER-1:0] seed_in;
  initial begin
    inject_numeric = $test$plusargs("INJECT_NUMERIC");
    inject_protocol = $test$plusargs("INJECT_PROTOCOL");
    stalls = $test$plusargs("STALLS");
    directed();
    if (!$value$plusargs("VECTORS=%s",vector_file)) $fatal(1,"[VECTOR] missing file");
    fd = $fopen(vector_file,"r");
    if (fd == 0) $fatal(1,"[VECTOR] cannot open file");
    count = $fscanf(fd,"%d",ncases);
    if (count != 1 || ncases < 1) $fatal(1,"[VECTOR] bad case count");
    for (int ci = 0; ci < ncases; ci++) begin
      count = $fscanf(fd,"%d %h %d %d",mode_in,seed_in,restart_in,nwords);
      if (count != 4 || nwords < 1 || nwords > 40000) $fatal(1,"[VECTOR] bad header");
      for (int wi = 0; wi < nwords; wi++) begin
        count = $fscanf(fd,"%h %d %h %h",xs[wi],last_in,ys[wi],states[wi]);
        lasts[wi] = 1'(last_in);
        if (count != 4) $fatal(1,"[VECTOR] short data");
      end
      configure(2'(mode_in),seed_in,1'(restart_in));
      got = 0; sent = 0; accepted_count = 0; total = nwords; scoring = 1;
      drive_cycles = 0;
      while (got < total) begin
        rng = {rng[30:0], rng[31]^rng[21]^rng[1]^rng[0]};
        m_ready = !stalls || rng[3:0] > 3;
        if ((stalls || inject_protocol) && drive_cycles < 12) m_ready = 0;
        if (!s_valid && sent < total && (!stalls || rng[7:4] > 4)) begin
          s_valid = 1; s_data = xs[sent]; s_last = lasts[sent];
        end
        @(posedge clk);
        accepted = s_valid && s_ready;
        if (accepted) sent = sent + 1;
        @(negedge clk);
        if (accepted) s_valid = 0;
        drive_cycles = drive_cycles + 1;
      end
      scoring = 0; compared = compared + got;
      if (m_valid) $fatal(1,"[NUMERIC] extra output after case");
    end
    $fclose(fd);
    repeat(4) @(negedge clk);
    if (m_valid) $fatal(1,"[NUMERIC] extra output");
    if (max_run < 16 && !stalls) $fatal(1,"[RATE] no sustained one-word/cycle stream");
    if (stalls && (holds == 0 || gaps == 0)) $fatal(1,"[COVERAGE] no stalls/gaps");
    $display("PASS PRBS: configs=%0d outputs=%0d max_run=%0d holds=%0d gaps=%0d",ncases,compared,max_run,holds,gaps);
    $finish;
  end
  initial begin #20000000; $fatal(1,"[TIMEOUT] PRBS"); end
endmodule
