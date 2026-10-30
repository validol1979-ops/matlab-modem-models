module sync_rom #(
  parameter int WIDTH=18, ADDR_WIDTH=8,
  parameter INIT_FILE="rtl/common/mem/test_rom.mem"
)(
  input logic clk, rd_en,
  input logic [ADDR_WIDTH-1:0] rd_addr,
  output logic [WIDTH-1:0] rd_data
);
  (* rom_style="block", romstyle="M10K" *) logic [WIDTH-1:0] memory [0:(1<<ADDR_WIDTH)-1];
  initial $readmemb(INIT_FILE,memory);
  always_ff @(posedge clk) if (rd_en) rd_data <= memory[rd_addr];
endmodule
