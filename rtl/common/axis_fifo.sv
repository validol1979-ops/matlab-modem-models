// Single-clock ready/valid FIFO. DEPTH is total usable capacity, including
// the registered RAM output; no asynchronous memory read or data reset.
// Minimum empty-input to output-handshake latency is two clocks. With queued
// backlog both ports sustain one transfer/clock, including full FIFO pop+push.
module axis_fifo #(
  parameter int WIDTH=36,DEPTH=16,
  parameter bit RESET_ACTIVE=1
)(
  input logic clk,rst,
  input logic s_valid,s_last,
  input logic [WIDTH-1:0] s_data,
  output logic s_ready,
  output logic m_valid,m_last,
  output logic [WIDTH-1:0] m_data,
  input logic m_ready,
  output logic [(DEPTH>1?$clog2(DEPTH+1):1)-1:0] level
);
  localparam int AW=DEPTH>1?$clog2(DEPTH):1;
  localparam int CW=DEPTH>1?$clog2(DEPTH+1):1;
  initial begin
    if(WIDTH<1||WIDTH>4096||DEPTH<2||DEPTH>65536)
      $fatal(1,"[PARAMETER] axis_fifo WIDTH1..4096 and DEPTH2..65536 required");
  end
  wire reset_now=rst==RESET_ACTIVE;
  logic [AW-1:0] wr_ptr,rd_ptr;
  logic output_valid;
  wire [WIDTH:0] ram_output;
  assign m_valid=output_valid&&!reset_now;
  assign {m_last,m_data}=ram_output;
  wire pop=m_valid&&m_ready;
  assign s_ready=!reset_now&&(level<CW'(DEPTH)||pop);
  wire push=s_valid&&s_ready;
  // All unread RAM words are included in level, but the current output is not
  // fetched twice. A new write cannot be read on its own write edge.
  wire read_word=!reset_now&&(level>CW'(output_valid))&&(!output_valid||m_ready);
  sync_ram #(.WIDTH(WIDTH+1),.ADDR_WIDTH(AW)) storage(
    .clk(clk),.wr_en(push),.rd_en(read_word),.wr_addr(wr_ptr),.rd_addr(rd_ptr),
    .wr_data((WIDTH+1)'({s_last,s_data})),.rd_data(ram_output));
  always_ff @(posedge clk) begin
    if(reset_now) begin
      level<='0;wr_ptr<='0;rd_ptr<='0;output_valid<=0;
    end else begin
      case({push,pop})
        2'b10:level<=level+1'b1;
        2'b01:level<=level-1'b1;
        default:begin end
      endcase
      if(push) wr_ptr<=wr_ptr==AW'(DEPTH-1)?'0:wr_ptr+1'b1;
      if(read_word) begin
        rd_ptr<=rd_ptr==AW'(DEPTH-1)?'0:rd_ptr+1'b1;
        output_valid<=1;
      end else if(pop) output_valid<=0;
    end
  end
endmodule
