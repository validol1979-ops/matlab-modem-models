// Counts actual interface handshakes. No functional model or expected data is used.
`timescale 1ns/1ps
module stream_rate_tb;
  parameter bit FFT=0,RESET_ACTIVE=1;
  parameter int LOG2N=6,LOG2LANES=3,LOG2TMAX=6,TAPS=41,LENGTH=512,FRAMES=32,GAP=0;
  parameter bit BACKPRESSURE=0;
  parameter string TWIDDLE_FILE="rtl/common/mem/fft_twiddle_64.mem";
  localparam int INPUT_LENGTH=FFT?(1<<LOG2N):LENGTH;
  localparam int OUTPUT_LENGTH=FFT?INPUT_LENGTH:INPUT_LENGTH+TAPS-1;
  logic clk=0,rst=RESET_ACTIVE;
  always #5 clk=!clk;
  logic s_valid=0,s_last=0,s_ready;
  logic signed [17:0] s_re=0,s_im=0;
  logic m_valid,m_last,m_ready=1,error;
  logic signed [19:0] m_re,m_im;
  logic cfg_valid=0,cfg_last=0,cfg_ready,configured;
  logic signed [17:0] cfg_re=0,cfg_im=0;
  int fifo_observed,extra_observed,bank_observed,drain_observed,capacity_observed;
  if(FFT)begin : g_fft
    logic inverse;
    fft_r2sdf #(.LOG2N(LOG2N),.RESET_ACTIVE(RESET_ACTIVE),.TWIDDLE_FILE(TWIDDLE_FILE)) dut
      (.clk(clk),.rst(rst),.s_valid(s_valid),.s_last(s_last),.s_ready(s_ready),.s_inverse(1'b0),
       .s_re(s_re),.s_im(s_im),.m_valid(m_valid),.m_last(m_last),.m_ready(m_ready),
       .m_re(m_re),.m_im(m_im),.m_inverse(inverse),.error(error));
    assign configured=1;assign cfg_ready=1;
    always_comb begin
      capacity_observed=$size(dut.fifo);fifo_observed=int'(dut.fifo_count);extra_observed=int'(dut.pending);
      bank_observed=int'(dut.full[0])+int'(dut.full[1]);drain_observed=int'(dut.draining);
    end
  end else begin : g_fir
    logic signed [17:0] re,im;
    fir_runtime #(.LOG2LANES(LOG2LANES),.LOG2TMAX(LOG2TMAX),.RESET_ACTIVE(RESET_ACTIVE)) dut
      (.clk(clk),.rst(rst),.cfg_valid(cfg_valid),.cfg_last(cfg_last),.cfg_re(cfg_re),.cfg_im(cfg_im),
       .cfg_ready(cfg_ready),.configured(configured),.s_valid(s_valid),.s_last(s_last),.s_ready(s_ready),
       .s_re(s_re),.s_im(s_im),.m_valid(m_valid),.m_last(m_last),.m_ready(m_ready),
       .m_re(re),.m_im(im),.error(error));
    assign m_re=20'(re);assign m_im=20'(im);
    always_comb begin
      capacity_observed=$size(dut.fifo);fifo_observed=int'(dut.fifo_count);extra_observed=int'(dut.reserved);
      bank_observed=0;drain_observed=int'(dut.last_seen);
    end
  end
  axis_check #(.WIDTH(36),.RESET_ACTIVE(RESET_ACTIVE),.NAME("rates input")) check_input
    (.clk(clk),.rst(rst),.valid(s_valid),.ready(s_ready),.last(s_last),.data({s_re,s_im}));
  axis_check #(.WIDTH(40),.RESET_ACTIVE(RESET_ACTIVE),.NAME("rates output")) check_output
    (.clk(clk),.rst(rst),.valid(m_valid),.ready(m_ready),.last(m_last),.data({m_re,m_im}));
  longint cycle=0;
  int fd,accepted_in=0,accepted_out=0,input_frames=0,output_frames=0;
  bit armed=0;
  string trace;
  always @(posedge clk)begin
    cycle++;
    if(rst!=RESET_ACTIVE&&armed)begin
      $fdisplay(fd,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",cycle,s_valid,s_ready,(s_valid?s_last:1'b0),m_valid,m_ready,(m_valid?m_last:1'b0),
                fifo_observed,extra_observed,bank_observed,drain_observed,capacity_observed);
      if(error)$fatal(1,"[RATE] DUT error");
      if(s_valid&&s_ready)begin accepted_in++;if(s_last)input_frames++;end
      if(m_valid&&m_ready)begin accepted_out++;if(m_last)output_frames++;end
      if(fifo_observed<0||fifo_observed>capacity_observed)$fatal(1,"[RATE] FIFO capacity");
    end
  end
  always @(negedge clk)m_ready=!BACKPRESSURE||(cycle%8)<5;
  initial begin
    if(!$value$plusargs("TRACE=%s",trace))$fatal(1,"TRACE required");
    fd=$fopen(trace,"w");if(!fd)$fatal(1,"Cannot open trace");
    $fdisplay(fd,"cycle,s_valid,s_ready,s_last,m_valid,m_ready,m_last,fifo,extra,full_banks,draining,fifo_capacity");
    repeat(5)@(negedge clk);rst=!RESET_ACTIVE;
    if(!FFT)begin
      for(int k=0;k<TAPS;k++)begin
        @(negedge clk);cfg_valid=1;cfg_last=k==TAPS-1;cfg_re=k==0?18'sd65536:18'sd0;
        do @(posedge clk);while(!cfg_ready);
      end
      @(negedge clk);cfg_valid=0;cfg_last=0;
      if(!configured||error)$fatal(1,"[RATE] valid FIR configuration failed");
    end
    for(int frame=0;frame<FRAMES;frame++)begin
      if(frame>0&&GAP>0)begin @(negedge clk);s_valid=0;repeat(GAP-1)@(negedge clk);end
      for(int sample=0;sample<INPUT_LENGTH;sample++)begin
        @(negedge clk);armed=1;s_valid=1;s_last=sample==INPUT_LENGTH-1;
        s_re=18'(sample+frame);s_im=18'(-sample);
        for(int guard=0;guard<200000;guard++)begin
          @(posedge clk);if(s_ready)break;
          if(guard==199999)$fatal(1,"[RATE] input never accepted");
        end
      end
    end
    @(negedge clk);s_valid=0;s_last=0;
    for(int guard=0;guard<200000&&accepted_out<FRAMES*OUTPUT_LENGTH;guard++)@(negedge clk);
    repeat(20)@(negedge clk);
    if(accepted_in!=FRAMES*INPUT_LENGTH||accepted_out!=FRAMES*OUTPUT_LENGTH||input_frames!=FRAMES||output_frames!=FRAMES||error)
      $fatal(1,"[RATE] incomplete stream in%0d/out%0d frames%0d/%0d",accepted_in,accepted_out,input_frames,output_frames);
    armed=0;$fclose(fd);
    $display("PASS STREAM RATES: %0d inputs, %0d outputs, %0d frames",accepted_in,accepted_out,FRAMES);$finish;
  end
  initial begin #50000000;$fatal(1,"[RATE] measurement timeout");end
endmodule
