// Vector scoreboard is independent of DUT arithmetic; raw values come from Python.
module sos_iir_tb #(
  parameter int COEF_FRAC=28,
  parameter int STATE_BITS=64,
  parameter bit RESET_ACTIVE=1
);
  localparam int AW=(STATE_BITS>51 ? STATE_BITS : 51)+1;
  localparam int MAX_SAMPLES=8192;
  // Numeric observation points avoid a Verilator 5.050 internal error on a
  // hierarchical enum-item reference when RESET_ACTIVE=0. Not DUT control logic.
  localparam logic [3:0] P_IDLE=0, P_ROUND_Y=3, P_UPDATE1=7, P_UPDATE2=11;
  logic clk, rst;
  logic cfg_valid, cfg_last, cfg_ready, configured;
  logic signed [31:0] cfg_b0, cfg_b1, cfg_b2, cfg_a1, cfg_a2;
  logic s_valid, s_last, s_ready, m_valid, m_last, m_ready, error, saturated;
  logic signed [17:0] s_re, s_im, m_re, m_im;
  sos_iir #(.COEF_FRAC(COEF_FRAC),.STATE_BITS(STATE_BITS),.RESET_ACTIVE(RESET_ACTIVE)) dut(.*);
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("SOS input")) input_check(
    .clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im}));
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("SOS output")) output_check(
    .clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}));
  axis_check #(.WIDTH(160),.RESET_ACTIVE(RESET_ACTIVE),.NAME("SOS config")) config_check(
    .clk(clk),.rst(rst),.valid(cfg_valid),.ready(cfg_ready),.last(cfg_last),
    .data({cfg_b0,cfg_b1,cfg_b2,cfg_a1,cfg_a2}));

  int input_re[0:MAX_SAMPLES-1], input_im[0:MAX_SAMPLES-1], lasts[0:MAX_SAMPLES-1];
  int expected_re[0:MAX_SAMPLES-1], expected_im[0:MAX_SAMPLES-1], clips[0:MAX_SAMPLES-1];
  logic signed [AW-1:0] trace[0:MAX_SAMPLES-1][0:1][0:3][0:5];
  int coeffs[0:3][0:4];
  int ns, length, accepted, emitted, total, checks, cycle_number, accept_cycle;
  int input_stalls, output_stalls, cfg_blocked, collisions, stage;
  int measured_latency[0:4], measured_interval[0:4], previous_accept;
  int fd, count, ncases, dummy, seed;
  bit checking, stalled, force_stall, inject_numeric, inject_protocol;
  logic [31:0] lfsr;
  string vector_path;
  string integer_token;
  // Decimal parsing into AW bits avoids simulators truncating negative %d values
  // to 64 bits before assigning an AW=65 destination.
  function automatic logic signed [AW-1:0] decimal_integer(input string token);
    logic signed [AW-1:0] value;
    bit negative;
    int first;
    value=0; negative=token.len()>0 && token.getc(0)==8'd45;
    first=negative ? 1 : 0;
    for (int i=first; i<token.len(); i=i+1) begin
      if (token.getc(i)<8'd48 || token.getc(i)>8'd57) $fatal(1,"[VECTOR] invalid integer");
      value=value*AW'(10)+AW'(int'(token.getc(i))-48);
    end
    return negative ? -value : value;
  endfunction
  initial begin clk=0; forever #5 clk=~clk; end
  always @(negedge clk) begin
    lfsr = {lfsr[30:0],lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
    m_ready = !force_stall && (!stalled || lfsr[2:0] != 0);
  end
  always @(posedge clk) begin
    if (rst != RESET_ACTIVE) begin
      cycle_number = cycle_number+1;
      if (cfg_valid && cfg_ready && s_ready) $fatal(1,"[ARBITRATION] cfg/data collision");
      if (cfg_valid && cfg_ready && s_valid) collisions=collisions+1;
      if (cfg_valid && !cfg_ready) cfg_blocked=cfg_blocked+1;
      if (s_valid && !s_ready) input_stalls=input_stalls+1;
      if (m_valid && !m_ready) output_stalls=output_stalls+1;
      if (error && (s_ready || cfg_ready || configured)) $fatal(1,"[ERROR_POLICY] input enabled after error");
    end
    if (!checking || rst == RESET_ACTIVE) begin
      accepted=0; emitted=0; previous_accept=-1;
    end else begin
      if (s_valid && s_ready) begin
        if (accepted>=length) $fatal(1,"[NUMERIC] extra input");
        if (!stalled && previous_accept>=0 && cycle_number-previous_accept != 11*ns+2)
          $fatal(1,"[RATE] unexpected initiation interval");
        if (!stalled && previous_accept>=0) measured_interval[ns]=cycle_number-previous_accept;
        previous_accept=cycle_number; accept_cycle=cycle_number; accepted=accepted+1;
      end
      if (dut.phase == P_ROUND_Y || dut.phase == P_UPDATE1 || dut.phase == P_UPDATE2) begin
        stage=int'(dut.section);
        for (int c=0; c<2; c=c+1) begin
          if (dut.phase == P_ROUND_Y) begin
            if (dut.rounded_y[c] !== trace[accepted-1][c][stage][3]
                || AW'(dut.clip_output(dut.rounded_y[c])) !== trace[accepted-1][c][stage][0])
              $fatal(1,"[RAW_STAGE] y sample=%0d channel=%0d section=%0d got=%0d/%0d expected=%0d/%0d x=%0d p=%0d s1=%0d",accepted-1,c,stage,
                dut.rounded_y[c],dut.clip_output(dut.rounded_y[c]),trace[accepted-1][c][stage][3],trace[accepted-1][c][stage][0],dut.x[c],dut.product[c],dut.state1[c][stage]);
          end else begin
            dummy=dut.phase == P_UPDATE1 ? 1 : 2;
            if (dut.raw_state[c] !== trace[accepted-1][c][stage][dummy+3]
                || AW'(dut.clip_state(dut.raw_state[c])) !== trace[accepted-1][c][stage][dummy])
              $fatal(1,"[RAW_STAGE] state sample=%0d channel=%0d section=%0d",accepted-1,c,stage);
          end
          checks=checks+1;
        end
      end
      if (m_valid && m_ready) begin
        if (emitted>=accepted || emitted>=length) $fatal(1,"[NUMERIC] extra output");
        if (int'(m_re)!==expected_re[emitted]+int'(inject_numeric && total==0)
            || int'(m_im)!==expected_im[emitted] || int'(m_last)!==lasts[emitted]
            || int'(saturated)!==clips[emitted])
          $fatal(1,"[NUMERIC] sample=%0d got=(%0d,%0d,%0d,%0d) expected=(%0d,%0d,%0d,%0d)",
            emitted,m_re,m_im,m_last,saturated,expected_re[emitted],expected_im[emitted],lasts[emitted],clips[emitted]);
        for (int c=0; c<2; c=c+1)
          for (int j=0; j<ns; j=j+1)
            if (AW'(dut.state1[c][j]) !== trace[emitted][c][j][1]
                || AW'(dut.state2[c][j]) !== trace[emitted][c][j][2])
              $fatal(1,"[RAW_STATE] sample=%0d channel=%0d section=%0d",emitted,c,j);
        if (!stalled && cycle_number-accept_cycle != 11*ns+1) $fatal(1,"[LATENCY] unexpected latency");
        if (!stalled) measured_latency[ns]=cycle_number-accept_cycle;
        emitted=emitted+1; total=total+1;
      end
    end
  end

  task automatic cycle;
    @(posedge clk); @(negedge clk); #1;
  endtask
  task automatic reset_dut;
    checking=0; rst=RESET_ACTIVE; s_valid=0; cfg_valid=0;
    #1;
    if (s_ready || cfg_ready || m_valid) $fatal(1,"[RESET] handshake during reset");
    repeat(2) cycle();
    if (configured || error || saturated) $fatal(1,"[RESET] status not cleared");
    for (int c=0; c<2; c=c+1)
      for (int j=0; j<4; j=j+1)
        if (dut.state1[c][j]!=0 || dut.state2[c][j]!=0) $fatal(1,"[RESET] state not cleared");
    rst=!RESET_ACTIVE; cycle();
  endtask
  task automatic row(input int b0,b1,b2,a1,a2,input bit last);
    cfg_b0=32'(b0); cfg_b1=32'(b1); cfg_b2=32'(b2); cfg_a1=32'(a1); cfg_a2=32'(a2);
    cfg_last=last; cfg_valid=1; #1;
    while (!cfg_ready) cycle();
    cycle(); cfg_valid=0; #1;
  endtask
  task automatic sample(input int re,im,input bit last);
    s_re=18'(re); s_im=18'(im); s_last=last; s_valid=1; #1;
    while (!s_ready) cycle();
    cycle(); s_valid=0; #1;
  endtask
  task automatic drain;
    while (dut.phase!=P_IDLE || m_valid) cycle();
    cycle();
  endtask
  task automatic expect_error;
    if (!error || configured || s_ready || cfg_ready) $fatal(1,"[CONFIG] bad configuration accepted");
    repeat(3) cycle();
    if (!error) $fatal(1,"[CONFIG] error not sticky");
  endtask
  task automatic protocols;
    // Configuration/data collision, then held cfg through gaps and the final output stall.
    reset_dut();
    if (s_ready) $fatal(1,"[CONFIG] data before configuration");
    s_valid=1; s_re=100; s_im=-100; s_last=0;
    row(1<<COEF_FRAC,0,0,-(1<<(COEF_FRAC-1)),0,1);
    while (!s_ready) cycle();
    cycle(); s_valid=0; drain();
    cfg_valid=1; cfg_last=1; #1;
    repeat(5) begin
      if (cfg_ready || !s_ready) $fatal(1,"[CONFIG] cfg admitted in open frame or blocked data");
      cycle();
    end
    force_stall=1; m_ready=0;
    sample(10,-10,1);
    while (!m_valid) cycle();
    repeat(12) begin
      if (cfg_ready) $fatal(1,"[CONFIG] cfg admitted before output consumed");
      cycle();
    end
    force_stall=0; m_ready=1;
    while (!cfg_ready) cycle();
    cycle(); cfg_valid=0; #1;
    if (!configured || error || saturated) $fatal(1,"[CONFIG] reconfigure failed");
    // Reconfiguration must zero recursive state: feedback-only residual would be nonzero.
    force_stall=1; m_ready=0; sample(0,0,1);
    while (!m_valid) cycle();
    if (m_re!=0 || m_im!=0) $fatal(1,"[STATE_RESET] reconfigure did not clear state");
    force_stall=0; m_ready=1; drain();
    // Pending data stays held through a partial two-row configuration and its gap.
    reset_dut(); s_valid=1; s_re=77; s_im=-99; s_last=1;
    row(1<<COEF_FRAC,0,0,0,0,0);
    repeat(4) begin
      if (s_ready || configured || !cfg_ready) $fatal(1,"[CONFIG] partial config admitted data");
      cycle();
    end
    row(1<<COEF_FRAC,0,0,0,0,1);
    while (!s_ready) cycle();
    cycle(); s_valid=0; drain();
    // Reset at every microstep, as well as with an unread output and partial cfg.
    for (int delay_cycles=0; delay_cycles<12; delay_cycles=delay_cycles+1) begin
      reset_dut(); row(1<<COEF_FRAC,0,0,0,0,1);
      force_stall=1; m_ready=0; sample(123,-456,1);
      repeat(delay_cycles) cycle(); reset_dut();
      repeat(14) begin
        if (m_valid) $fatal(1,"[RESET] cancelled sample reappeared");
        cycle();
      end
      force_stall=0; m_ready=1;
    end
    reset_dut(); row(0,0,0,0,0,0); reset_dut();
    // Unit-circle poles, outside circle, all three Jury inequalities and signed32 corners.
    for (int kind=0; kind<7; kind=kind+1) begin
      reset_dut(); s_valid=1; s_last=1; s_re=0; s_im=0;
      case(kind)
        0: row(0,0,0,0,1<<COEF_FRAC,1);
        1: row(0,0,0,0,-(1<<COEF_FRAC),1);
        2: row(0,0,0,-(1<<COEF_FRAC),0,1);
        3: row(0,0,0,1<<COEF_FRAC,0,1);
        4: row(0,0,0,0,(1<<COEF_FRAC)+1,1);
        5: row(0,0,0,32'sh80000000,0,1);
        6: row(0,0,0,32'sh7fffffff,0,1);
      endcase
      expect_error(); reset_dut();
    end
    row(0,0,0,0,0,0); row(0,0,0,0,0,0); row(0,0,0,0,0,1); expect_error();
    reset_dut();
    repeat(4) row(0,0,0,0,0,0);
    row(0,0,0,0,0,1); expect_error(); reset_dut();
    // Stable configurations one integer LSB inside each stability boundary.
    row(0,0,0,-((1<<COEF_FRAC)-1),0,1);
    row(0,0,0,(1<<COEF_FRAC)-1,0,1);
    row(0,0,0,0,(1<<COEF_FRAC)-1,1);
    row(0,0,0,0,-((1<<COEF_FRAC)-1),1);
    if (!configured || error) $fatal(1,"[CONFIG] stable boundary rejected");
    // Protocol negative deliberately violates the actual input axis_check.
    if (inject_protocol) begin
      reset_dut(); s_valid=1; s_re=1; s_im=0; s_last=1; cycle();
      s_re=2; cycle();
      $fatal(1,"[NEGATIVE_MISSING] protocol checker did not fire");
    end
    reset_dut();
  endtask

  initial begin
    rst=RESET_ACTIVE; s_valid=0; cfg_valid=0; checking=0;
    cfg_last=0; cfg_b0=0; cfg_b1=0; cfg_b2=0; cfg_a1=0; cfg_a2=0;
    s_last=0; s_re=0; s_im=0; force_stall=0; stalled=0; lfsr=32'h8202;
    cycle_number=0; total=0; checks=0; input_stalls=0; output_stalls=0; cfg_blocked=0; collisions=0;
    for (int j=0; j<5; j=j+1) begin measured_latency[j]=0; measured_interval[j]=0; end
    seed=8202; dummy=$urandom(seed);
    inject_numeric=$test$plusargs("INJECT_MISMATCH");
    inject_protocol=$test$plusargs("INJECT_PROTOCOL");
    cycle(); protocols();
    if (!$value$plusargs("VECTORS=%s",vector_path)) $fatal(1,"[VECTOR] no path");
    fd=$fopen(vector_path,"r");
    if (fd==0 || $fscanf(fd,"%d",ncases)!=1) $fatal(1,"[VECTOR] header");
    for (int k=0; k<ncases; k=k+1) begin
      if ($fscanf(fd,"%d %d",ns,length)!=2 || length>MAX_SAMPLES || length<1)
        $fatal(1,"[VECTOR] length");
      for (int j=0; j<ns; j=j+1)
        if ($fscanf(fd,"%d %d %d %d %d",coeffs[j][0],coeffs[j][1],coeffs[j][2],coeffs[j][3],coeffs[j][4])!=5)
          $fatal(1,"[VECTOR] coefficients");
      for (int i=0; i<length; i=i+1) begin
        if ($fscanf(fd,"%d %d %d %d %d %d",input_re[i],input_im[i],lasts[i],expected_re[i],expected_im[i],clips[i])!=6)
          $fatal(1,"[VECTOR] sample");
        for (int c=0; c<2; c=c+1)
          for (int j=0; j<ns; j=j+1)
            for (int field=0; field<6; field=field+1) begin
              if ($fscanf(fd,"%s",integer_token)!=1) $fatal(1,"[VECTOR] trace");
              trace[i][c][j][field]=decimal_integer(integer_token);
            end
      end
      for (int j=0; j<ns; j=j+1) row(coeffs[j][0],coeffs[j][1],coeffs[j][2],coeffs[j][3],coeffs[j][4],j==ns-1);
      if (!configured || error) $fatal(1,"[CONFIG] model coefficients rejected");
      checking=1;
      stalled=$test$plusargs("STALL");
      for (int i=0; i<length; i=i+1) begin
        if (stalled) repeat($urandom_range(0,64)) cycle();
        sample(input_re[i],input_im[i],1'(lasts[i]));
      end
      while (emitted<length) cycle();
      if (accepted!=length) $fatal(1,"[NUMERIC] incomplete inputs");
      checking=0; stalled=0; cycle();
      if (m_valid) $fatal(1,"[NUMERIC] duplicate output");
    end
    if ($fscanf(fd,"%d",dummy)==1) $fatal(1,"[VECTOR] trailing data");
    $fclose(fd);
    if (input_stalls==0 || output_stalls==0 || cfg_blocked==0 || collisions==0 || checks==0)
      $fatal(1,"[COVERAGE] missing protocol or numeric coverage");
    $display("PASS SOS: samples=%0d raw_checks=%0d input_stalls=%0d output_stalls=%0d cfg_blocked=%0d collisions=%0d",total,checks,input_stalls,output_stalls,cfg_blocked,collisions);
    if (!$test$plusargs("STALL"))
      $display("PASS RATE: latency=%0d,%0d,%0d interval=%0d,%0d,%0d",measured_latency[1],measured_latency[2],measured_latency[4],measured_interval[1],measured_interval[2],measured_interval[4]);
    $finish;
  end
  initial begin #100000000; $fatal(1,"[TIMEOUT] SOS watchdog"); end
endmodule
