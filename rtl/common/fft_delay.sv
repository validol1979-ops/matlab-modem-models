// ce-gated delay of DEPTH samples for the SDF FFT datapath. On every clock with ce the
// input is shifted in; m_data is the value shifted in DEPTH ce-clocks earlier (plain
// shift-register semantics, valid during the ce clock that shifts the next value in).
// DEPTH <= 16: register shift. Larger: one sync_ram circular buffer with read-ahead
// (write address wa, read address wa+1 with rd_en=ce), so the registered read data equals
// the shift-register output; DEPTH >= 2 keeps the read off the address written that clock.
// Reset clears the write address of the RAM form and holds the register form.
module fft_delay #(
  parameter int WIDTH = 21, DEPTH = 8,
  parameter bit RESET_ACTIVE = 1
)(
  input logic clk, rst, ce,
  input logic [WIDTH-1:0] s_data,
  output logic [WIDTH-1:0] m_data
);
  localparam int AW = (DEPTH < 2) ? 1 : $clog2(DEPTH);
  generate
    if (DEPTH <= 16) begin : g_shift
      logic [WIDTH-1:0] pipe [0:DEPTH-1];
      always_ff @(posedge clk) begin
        // Reset only holds the shift (the contents need no reset).
        if (ce && rst != RESET_ACTIVE) begin
          pipe[0] <= s_data;
          for (int i = 1; i < DEPTH; i++) pipe[i] <= pipe[i-1];
        end
      end
      assign m_data = pipe[DEPTH-1];
    end else begin : g_ram
      logic [AW-1:0] wa;
      wire [AW-1:0] next = (wa == AW'(DEPTH-1)) ? '0 : wa + 1'b1;
      always_ff @(posedge clk) if (rst == RESET_ACTIVE) wa <= '0; else if (ce) wa <= next;
      sync_ram #(.WIDTH(WIDTH),.ADDR_WIDTH(AW)) ram (
        .clk(clk), .wr_en(ce), .rd_en(ce),
        .wr_addr(wa), .rd_addr(next),
        .wr_data(s_data), .rd_data(m_data));
    end
  endgenerate
endmodule
