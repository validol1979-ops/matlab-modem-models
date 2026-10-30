`timescale 1ns/1ps
// Independent file scoreboard, one worker per elaborated geometry.
module cic_case_tb #(
  parameter int STAGES=3, DELAY=1, ACC_WIDTH=33,
  parameter bit NORMALIZE=0, RESET_ACTIVE=1
)(output bit done);
  localparam int OW=NORMALIZE?18:ACC_WIDTH;
  localparam bit CONTROL=STAGES==1 && DELAY==1 && !NORMALIZE;
  logic clk=0;
  always #5 clk=~clk;
  logic rst=RESET_ACTIVE, cv=0, sv=0, sl=0, mr=0;
  logic [5:0] rate=1;
  logic signed [17:0] xr=0, xi=0;
  wire cr, sr, configured, error, mv, ml;
  wire signed [OW-1:0] yr, yi;
  cic_decimator #(.STAGES(STAGES),.DELAY(DELAY),.ACC_WIDTH(ACC_WIDTH),
    .NORMALIZE(NORMALIZE),.RESET_ACTIVE(RESET_ACTIVE)) dut(
    .clk(clk),.rst(rst),.cfg_valid(cv),.cfg_rate(rate),.cfg_ready(cr),.configured(configured),
    .s_valid(sv),.s_last(sl),.s_re(xr),.s_im(xi),.s_ready(sr),
    .m_valid(mv),.m_last(ml),.m_re(yr),.m_im(yi),.m_ready(mr),.error(error));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("cic input")) in_check(
    .clk(clk),.rst(rst),.valid(sv),.ready(sr),.last(sl),.data({xr,xi}));
  axis_check #(.WIDTH(2*OW),.RESET_ACTIVE(RESET_ACTIVE),.NAME("cic output")) out_check(
    .clk(clk),.rst(rst),.valid(mv),.ready(mr),.last(ml),.data({yr,yi}));
  axis_check #(.WIDTH(6),.RESET_ACTIVE(RESET_ACTIVE),.NAME("cic config")) cfg_check(
    .clk(clk),.rst(rst),.valid(cv),.ready(cr),.last(1'b1),.data(rate));

  longint signed er[0:2047], ei[0:2047];
  bit el[0:2047];
  int signed ir[0:2047], ii[0:2047];
  bit il[0:2047];
  int got=0, expected_count=0, total=0, cycle=0, group_cycle[0:2047];
  int pushed=0, groups=0, current_rate=1, phase_count=0;
  int case_count=0, stalls_in=0, stalls_out=0, adjacent=0, previous_accept=-2;
  bit score=0, stalled=0;
  logic [31:0] rng=32'(STAGES*813+DELAY*127+int'(NORMALIZE)*79+ACC_WIDTH);
  always @(posedge clk) begin
    cycle=cycle+1;
    rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
    if (rst!=RESET_ACTIVE) begin
      if (sv && !sr) stalls_in=stalls_in+1;
      if (mv && !mr) stalls_out=stalls_out+1;
      if (score) begin
        if (error) $fatal(1,"[NUMERIC] unexpected DUT error");
        if (mv && mr) begin
          if (got>=expected_count) $fatal(1,"[NUMERIC] extra output");
          if (yr!==OW'(er[got]) ||
              yi!==OW'(ei[got]) || ml!==el[got])
            $fatal(1,"[NUMERIC] N=%0d M=%0d norm=%0d AW=%0d word=%0d got=(%0d,%0d,%0b) expected=(%0d,%0d,%0b)",
              STAGES,DELAY,NORMALIZE,ACC_WIDTH,got,yr,yi,ml,er[got],ei[got],el[got]);
          if (!stalled && cycle-group_cycle[got]!=1)
            $fatal(1,"[RATE] group-to-output latency is not one clock");
          got=got+1; total=total+1;
        end
        if (sv && sr) begin
          if (previous_accept==cycle-1) adjacent=adjacent+1;
          previous_accept=cycle;
          phase_count=phase_count+1;
          pushed=pushed+1;
          if (phase_count==current_rate) begin
            group_cycle[groups]=cycle; groups=groups+1; phase_count=0;
          end
        end
      end
    end
  end

  task automatic reset_core;
    @(negedge clk); score=0;rst=RESET_ACTIVE;cv=0;sv=0;mr=0;
    #1; if(sr || cr || mv) $fatal(1,"[PROTOCOL] reset did not gate ports");
    repeat(3) @(negedge clk);
    rst=!RESET_ACTIVE;
    #1; if(error || configured || mv || sr || !cr)
      $fatal(1,"[PROTOCOL] bad reset state");
  endtask
  task automatic config_core(input int r);
    @(negedge clk); cv=1;rate=6'(r);
    #1; if(!cr || sr) $fatal(1,"[PROTOCOL] configuration priority/availability");
    @(posedge clk);
    @(negedge clk);cv=0;
  endtask
  task automatic send_word(input int a,input int b,input bit last);
    // Caller enters at a falling edge; source must hold through stalls.
    xr=18'(a);xi=18'(b);sl=last;sv=1;
    #1;
    if(score && !stalled && !sr) $fatal(1,"[RATE] input throughput below 1/clock");
    do @(posedge clk); while(!sr);
    @(negedge clk);sv=0;
  endtask
  task automatic quiet(input int clocks);
    repeat(clocks) begin
      @(negedge clk);
      if(mv) $fatal(1,"[PROTOCOL] unexpected pending output");
    end
  endtask

  // Directed assertions are about externally visible protocol; state snapshots
  // additionally establish atomic rejection of a bad TLAST.
  task automatic protocol_cases;
    logic signed [ACC_WIDTH-1:0] saved_i[0:1][0:STAGES-1];
    logic signed [ACC_WIDTH-1:0] saved_h[0:1][0:STAGES-1][0:DELAY-1];
    logic [5:0] saved_phase;
    reset_core();config_core(1);
    // Already configured collision; toggle s_valid without changing ready.
    @(negedge clk);cv=1;rate=1;sv=0;
    #1;if(!cr || sr) $fatal(1,"[PROTOCOL] cfg priority with s_valid=0");
    sv=1;xr=11;xi=-13;sl=1;
    #1;if(sr) $fatal(1,"[PROTOCOL] ready depends on s_valid");
    @(posedge clk);
    @(negedge clk);cv=0;
    #1;if(!sr) $fatal(1,"[PROTOCOL] held data did not resume");
    @(posedge clk);
    @(negedge clk);sv=0;
    if(!mv || !ml) $fatal(1,"[PROTOCOL] lost collision sample");
    // A pending last result forbids cfg even though input frame is closed.
    cv=1;rate=2;
    repeat(5) begin
      #1;if(cr || !mv) $fatal(1,"[PROTOCOL] cfg accepted before output drain");
      @(negedge clk);
    end
    mr=1;@(posedge clk);@(negedge clk);
    #1;if(!cr || sr) $fatal(1,"[PROTOCOL] cfg not eligible after drain");
    @(posedge clk);@(negedge clk);cv=0;
    // Pending cfg in an open frame must not block the final R-group.
    send_word(7,-9,0);
    cv=1;rate=1;
    repeat(4) begin
      #1;if(cr || !sr) $fatal(1,"[PROTOCOL] mid-frame cfg blocked data");
      @(negedge clk);
    end
    send_word(17,19,1);
    #1;if(cr) $fatal(1,"[PROTOCOL] unread output allowed cfg");
    @(posedge clk);@(negedge clk);
    #1;if(!cr || sr) $fatal(1,"[PROTOCOL] pending cfg failed to resume");
    @(posedge clk);@(negedge clk);cv=0;
    // Reset in a partial group; next numeric vectors establish zero state.
    config_core(32);mr=1;
    send_word(131071,-131072,0);send_word(-131072,131071,0);
    reset_core();
    // Reset while a valid output is held.
    config_core(1);mr=0;send_word(99,-101,1);
    if(!mv) $fatal(1,"[PROTOCOL] output reset test not exercised");
    reset_core();quiet(3);
    // Invalid full 6-bit rate encodings; errors remain sticky until reset.
    for(int bad=0;bad<3;bad=bad+1) begin
      reset_core();config_core(bad==0?0:bad==1?33:63);
      #1;if(!error || sr || cr || configured) $fatal(1,"[PROTOCOL] invalid rate accepted");
      repeat(3) @(negedge clk);
      if(!error) $fatal(1,"[PROTOCOL] nonsticky cfg error");
    end
    reset_core();config_core(4);mr=1;
    send_word(11,-13,0);send_word(17,19,0);
    saved_phase=dut.phase;
    for(int c=0;c<2;c=c+1) for(int k=0;k<STAGES;k=k+1) begin
      saved_i[c][k]=dut.integ[c][k];
      for(int d=0;d<DELAY;d=d+1) saved_h[c][k][d]=dut.history[c][k][d];
    end
    send_word(5,-7,1);
    #1;if(!error || sr || cr || configured || dut.phase!=saved_phase)
      $fatal(1,"[PROTOCOL] premature TLAST not rejected atomically");
    for(int c=0;c<2;c=c+1) for(int k=0;k<STAGES;k=k+1) begin
      if(saved_i[c][k]!==dut.integ[c][k]) $fatal(1,"[PROTOCOL] rejected input changed integrator");
      for(int d=0;d<DELAY;d=d+1)
        if(saved_h[c][k][d]!==dut.history[c][k][d]) $fatal(1,"[PROTOCOL] rejected input changed comb");
    end
    repeat(4) @(negedge clk);
    if(!error) $fatal(1,"[PROTOCOL] nonsticky TLAST error");
    reset_core();config_core(1);mr=0;
    if(CONTROL && $test$plusargs("INJECT_PROTOCOL")) begin
      send_word(1,2,1); // Fill the output register, then break input holding.
      xr=3;xi=4;sv=1;sl=1;
      @(posedge clk);@(negedge clk);xr=5;
      repeat(3) @(negedge clk);
      $fatal(1,"[CONTROL_MISSED] protocol corruption survived axis_check");
    end
    reset_core();
  endtask

  initial begin : run
    string folder,path;
    int fd,rc,r,ni,no,a,b,l;
    longint signed ea,eb;
    done=0;stalled=$test$plusargs("STALL");
    if(!$value$plusargs("VECTORS=%s",folder)) $fatal(1,"[VECTOR] missing VECTORS");
    path=$sformatf("%s/n%0d_m%0d_norm%0d_aw%0d.txt",folder,STAGES,DELAY,NORMALIZE,ACC_WIDTH);
    fd=$fopen(path,"r");if(fd==0) $fatal(1,"[VECTOR] open %s",path);
    protocol_cases();
    while(!$feof(fd)) begin
      rc=$fscanf(fd,"%d %d %d\n",r,ni,no);
      if(rc==-1) break;
      if(rc!=3 || ni<1 || ni>2048 || no<1 || no>2048 || ni!=r*no)
        $fatal(1,"[VECTOR] invalid header");
      for(int j=0;j<ni;j=j+1) begin
        rc=$fscanf(fd,"%d %d %d\n",a,b,l);
        if(rc!=3) $fatal(1,"[VECTOR] input parse");
        ir[j]=a;ii[j]=b;il[j]=1'(l);
      end
      for(int j=0;j<no;j=j+1) begin
        rc=$fscanf(fd,"%d %d %d\n",ea,eb,l);
        if(rc!=3) $fatal(1,"[VECTOR] expected parse");
        er[j]=ea;ei[j]=eb;el[j]=1'(l);
        if(CONTROL && case_count==0 && j==0 && $test$plusargs("INJECT_MISMATCH")) er[j]=ea+1;
      end
      config_core(r);
      got=0;groups=0;phase_count=0;pushed=0;expected_count=no;current_rate=r;
      score=1;mr=1;
      for(int j=0;j<ni;j=j+1) begin
        if(stalled) begin
          repeat(int'(rng[2:0])%3) @(negedge clk);
        end
        send_word(ir[j],ii[j],il[j]);
      end
      while(got<no) @(negedge clk);
      if(pushed!=ni || groups!=no || phase_count!=0)
        $fatal(1,"[NUMERIC] count/phase mismatch");
      quiet(3);score=0;case_count=case_count+1;
    end
    $fclose(fd);
    if(case_count!=161 || total!=2564 || adjacent==0 || (stalled && (stalls_in==0 || stalls_out==0)))
      $fatal(1,"[COVERAGE] missing cases/words/rate/stalls %0d %0d %0d %0d %0d",case_count,total,adjacent,stalls_in,stalls_out);
    $display("PASS CIC profile=n%0d_m%0d_norm%0d_aw%0d reset=%0d cases=%0d outputs=%0d adjacent=%0d stalls_in=%0d stalls_out=%0d",STAGES,DELAY,NORMALIZE,ACC_WIDTH,RESET_ACTIVE,case_count,total,adjacent,stalls_in,stalls_out);
    done=1;
  end
  // Receiver includes long forced pauses as well as pseudo-random stalls.
  always @(negedge clk) begin
    if(score && stalled) mr=(cycle%97<23)?0:((rng[7:4]!=0) && rng[9]);
  end
  initial begin
    #100000000;
    $fatal(1,"[TIMEOUT] CIC worker");
  end
endmodule

module cic_decimator_tb;
  parameter bit RESET_ACTIVE=1;
  wire [17:0] done;
  for(genvar n=0;n<4;n=n+1) begin:g_n
    localparam int N=n==0?1:n==1?2:n==2?3:5;
    for(genvar m=0;m<2;m=m+1) begin:g_m
      for(genvar norm=0;norm<2;norm=norm+1) begin:g_norm
        cic_case_tb #(.STAGES(N),.DELAY(m+1),.ACC_WIDTH(18+N*(5+m)),
          .NORMALIZE(1'(norm)),.RESET_ACTIVE(RESET_ACTIVE)) test_case(.done(done[n*4+m*2+norm]));
      end
    end
  end
  for(genvar norm=0;norm<2;norm=norm+1) begin:g_wrap
    cic_case_tb #(.STAGES(5),.DELAY(2),.ACC_WIDTH(18),.NORMALIZE(1'(norm)),
      .RESET_ACTIVE(RESET_ACTIVE)) test_case(.done(done[16+norm]));
  end
  initial begin
    wait(&done);
    $display("PASS CIC ALL reset=%0d profiles=18",RESET_ACTIVE);
    $finish;
  end
endmodule
