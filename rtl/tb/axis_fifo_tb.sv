`timescale 1ns/1ps
module axis_fifo_tb;
  parameter int WIDTH=37,DEPTH=16;
  parameter bit RESET_ACTIVE=1;
  localparam int CW=DEPTH>1?$clog2(DEPTH+1):1;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  logic s_valid=0,s_last=0,s_ready,m_valid,m_last,m_ready=0;
  logic [WIDTH-1:0] s_data=0,m_data;
  logic [CW-1:0] level;
  axis_fifo #(.WIDTH(WIDTH),.DEPTH(DEPTH),.RESET_ACTIVE(RESET_ACTIVE)) dut(.*);
  axis_check #(.WIDTH(WIDTH),.RESET_ACTIVE(RESET_ACTIVE),.NAME("FIFO input")) input_check(
    .clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data(s_data));
  axis_check #(.WIDTH(WIDTH),.RESET_ACTIVE(RESET_ACTIVE),.NAME("FIFO output")) output_check(
    .clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data(m_data));
  logic [WIDTH:0] pending[$];
  longint arrivals[$];
  longint cycle=0,pushed=0,popped=0,discarded=0,simultaneous=0,full_swaps=0;
  longint full_wait=0,empty_wait=0,stalled_output=0,wrap_writes=0,wrap_reads=0;
  longint backlog_bubbles=0;
  int phase=0,next_id=1,maximum=0,reset_nonempty=0;
  logic [31:0] random_state=32'h86a31c07;
  bit accepted=0,inject_data,inject_last,inject_level,expect_single_backlog_bubble=0;
  function automatic logic [WIDTH-1:0] payload(input int id);
    logic [WIDTH-1:0] result;
    for(int k=0;k<WIDTH;k++) result[k]=1'((id>>(k%31))^(id*17+k/31));
    return result;
  endfunction
  initial begin
    inject_data=$test$plusargs("INJECT_DATA");inject_last=$test$plusargs("INJECT_LAST");inject_level=$test$plusargs("INJECT_LEVEL");
  end
  always @(posedge clk) begin
    logic [WIDTH:0] expected,observed;
    longint arrival;
    cycle++;accepted=0;
    if(rst==RESET_ACTIVE) begin
      if(s_ready!==0||m_valid!==0) $fatal(1,"[RESET] FIFO handshake during reset");
      if(pending.size()>0) reset_nonempty++;
      discarded+=pending.size();pending.delete();arrivals.delete();expect_single_backlog_bubble=0;
    end else begin
      if(expect_single_backlog_bubble) begin
        if(m_valid!==0) $fatal(1,"[BACKLOG] missing one-word pop+push output bubble");
        backlog_bubbles++;expect_single_backlog_bubble=0;
      end
      if($isunknown({level,s_ready,m_valid})||int'(level)+(inject_level?1:0)!=pending.size()||int'(level)>DEPTH)
        $fatal(1,"[LEVEL] FIFO occupancy differs from accepted transactions");
      if(s_ready!==(pending.size()<DEPTH||(m_valid&&m_ready))) $fatal(1,"[CAPACITY] FIFO ready at full/empty boundary");
      if(pending.size()>maximum) maximum=pending.size();
      if(pending.size()>0&&cycle-arrivals[0]>=2&&!m_valid) $fatal(1,"[LATENCY] FIFO omitted an available output");
      if(dut.read_word&&dut.push&&dut.rd_ptr==dut.wr_ptr) $fatal(1,"[MEMORY] same-address RAM read/write");
      if(int'(dut.wr_ptr)>=DEPTH||int'(dut.rd_ptr)>=DEPTH) $fatal(1,"[MEMORY] nonpower address wrap");
      if(s_valid&&!s_ready) full_wait++;
      if(!m_valid&&m_ready) empty_wait++;
      if(m_valid&&!m_ready) stalled_output++;
      if(phase==2&&(!s_valid||!s_ready||!m_valid||!m_ready)) $fatal(1,"[THROUGHPUT] bubble at full FIFO");
      if(m_valid&&m_ready) begin
        if(pending.size()==0) $fatal(1,"[NUMERIC] FIFO produced an unaccepted word");
        expected=pending.pop_front();arrival=arrivals.pop_front();observed={m_last,m_data};
        if(inject_data) observed[0]=!observed[0];
        if(inject_last) observed[WIDTH]=!observed[WIDTH];
        if(observed!==expected) $fatal(1,"[NUMERIC] FIFO data/TLAST order");
        if(cycle-arrival<2) $fatal(1,"[LATENCY] FIFO bypassed synchronous RAM");
        popped++;
      end
      if(s_valid&&s_ready) begin pending.push_back({s_last,s_data});arrivals.push_back(cycle);pushed++;accepted=1;end
      if(s_valid&&s_ready&&m_valid&&m_ready) begin
        simultaneous++;
        if(int'(level)==DEPTH) full_swaps++;
        if(int'(level)==1) expect_single_backlog_bubble=1;
      end
      if(dut.push&&int'(dut.wr_ptr)==DEPTH-1) wrap_writes++;
      if(dut.read_word&&int'(dut.rd_ptr)==DEPTH-1) wrap_reads++;
    end
  end
  // Change only a consumed/idle source word; a blocked source holds all fields.
  task automatic drive(input int mode,input int count);
    repeat(count) begin
      @(negedge clk);
      random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
      m_ready=mode==1||mode==2||mode==4||(mode==3&&random_state[2:0]!=0);
      if(!s_valid||accepted) begin
        s_valid=mode==0||mode==2||(mode==3&&random_state[5:4]!=0);
        if(s_valid) begin s_data=payload(next_id);s_last=next_id%7==0||next_id%13==0;next_id++;end
      end
    end
  endtask
  task automatic drain;
    // Finish a possibly held source word before stopping the source.
    m_ready=1;
    if(s_valid) begin do @(posedge clk);while(!s_ready);end
    @(negedge clk);s_valid=0;
    while(pending.size()>0) @(negedge clk);
    repeat(3) @(negedge clk);
    if(m_valid||level!=0) $fatal(1,"[RESET] FIFO did not drain");
  endtask
  task automatic reset_fifo;
    @(negedge clk);rst=RESET_ACTIVE;s_valid=0;m_ready=0;
    repeat(3) @(negedge clk);rst=!RESET_ACTIVE;
    @(negedge clk);
    if(m_valid||level!=0) $fatal(1,"[RESET] stale word after reset");
  endtask
  initial begin
    reset_fifo();
    phase=1;drive(0,DEPTH+8);
    // The last drive's edge has not happened yet: switch phase at a negedge.
    @(negedge clk);m_ready=1;phase=2;
    drive(2,4*DEPTH+32);
    @(negedge clk);phase=3;
    drain();
    // With one stored word, simultaneous pop+push leaves no older word to
    // fetch; the replacement appears after one empty output cycle.
    reset_fifo();
    @(negedge clk);m_ready=0;s_data=payload(next_id);s_last=0;s_valid=1;next_id++;
    @(negedge clk);if(level!=1) $fatal(1,"[BACKLOG] directed setup did not store one word");
    s_valid=0;
    // Present one replacement only after synchronous RAM has made the old word
    // visible; the next edge is therefore a level-one simultaneous pop+push.
    while(!m_valid) @(negedge clk);
    s_data=payload(next_id);s_valid=1;next_id++;m_ready=1;
    @(negedge clk);if(!accepted) $fatal(1,"[BACKLOG] replacement was not accepted");
    s_valid=0;
    while(backlog_bubbles==0) @(negedge clk);
    if(backlog_bubbles!=1) $fatal(1,"[BACKLOG] directed one-word bubble was not observed");
    drain();drive(3,2000+4*DEPTH);drain();
    // Reset full, with a stalled output; old RAM data must never reappear.
    drive(0,DEPTH+8);reset_fifo();drive(3,800+2*DEPTH);drain();
    // Reset after both address pointers have wrapped, then exercise a long burst.
    drive(0,DEPTH+8);reset_fifo();drive(2,4*DEPTH+64);drain();
    if(pending.size()!=0||pushed!=popped+discarded||maximum!=DEPTH||reset_nonempty<2||full_swaps<4*DEPTH||
       full_wait<1||empty_wait<1||stalled_output<1||wrap_writes<4||wrap_reads<4||backlog_bubbles<1)
      $fatal(1,"[COVERAGE] FIFO corners not exercised");
    $display("PASS AXIS FIFO width=%0d depth=%0d pushed=%0d popped=%0d discarded=%0d peak=%0d swaps=%0d full_swaps=%0d resets=%0d write_wraps=%0d read_wraps=%0d backlog_bubbles=%0d",WIDTH,DEPTH,pushed,popped,discarded,maximum,simultaneous,full_swaps,reset_nonempty,wrap_writes,wrap_reads,backlog_bubbles);
    $finish;
  end
  initial begin #5000000;$fatal(1,"[TIMEOUT] FIFO test did not finish");end
endmodule
