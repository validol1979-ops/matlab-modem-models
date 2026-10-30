module sync_ram #(
  parameter int WIDTH=18, ADDR_WIDTH=10
)(
  input logic clk,
  input logic wr_en, rd_en,
  input logic [ADDR_WIDTH-1:0] wr_addr, rd_addr,
  input logic [WIDTH-1:0] wr_data,
  output logic [WIDTH-1:0] rd_data
);
  // Simple dual port, registered read; same-address read/write returns old data.
  (* ram_style="block", ramstyle="M10K" *) logic [WIDTH-1:0] memory [0:(1<<ADDR_WIDTH)-1];
  always_ff @(posedge clk) begin
    if (wr_en) memory[wr_addr] <= wr_data;
    if (rd_en) rd_data <= memory[rd_addr];
  end
endmodule
