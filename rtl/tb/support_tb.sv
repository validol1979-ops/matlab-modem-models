`timescale 1ns/1ps
module rtl_support_top #(parameter ROM_FILE="rtl/common/mem/test_rom.mem");
  logic clk=0;
  always #5ns clk=~clk;
  logic signed [7:0] raw=0;
  wire signed [4:0] drop_one,drop_two;
  wire signed [5:0] same_fraction;
  wire signed [9:0] left_shift;
  wire [3:0] overflow;
  fxp_round_sat #(.IN_WIDTH(8),.IN_FRAC(4),.OUT_WIDTH(5),.OUT_FRAC(3)) r1(raw,drop_one,overflow[0]);
  fxp_round_sat #(.IN_WIDTH(8),.IN_FRAC(4),.OUT_WIDTH(5),.OUT_FRAC(2)) r2(raw,drop_two,overflow[1]);
  fxp_round_sat #(.IN_WIDTH(8),.IN_FRAC(4),.OUT_WIDTH(6),.OUT_FRAC(4)) r0(raw,same_fraction,overflow[2]);
  fxp_round_sat #(.IN_WIDTH(8),.IN_FRAC(2),.OUT_WIDTH(10),.OUT_FRAC(6)) rl(raw,left_shift,overflow[3]);
  logic wr_en=0,rd_en=0;
  logic [9:0] wr_addr=0,rd_addr=0;
  logic [17:0] wr_data=0;
  wire [17:0] rd_data;
  sync_ram ram(clk,wr_en,rd_en,wr_addr,rd_addr,wr_data,rd_data);
  logic rom_en=0;logic [7:0] rom_addr=0;wire [17:0] rom_data;
  sync_rom #(.INIT_FILE(ROM_FILE)) rom(clk,rom_en,rom_addr,rom_data);
  logic rst=1,async_bit=0,external_rst=1;
  wire sync_bit,sync_bit_low,sync_reset,sync_reset_low;
  bit_sync synchronizer(clk,rst,async_bit,sync_bit);
  bit_sync #(.RESET_ACTIVE(0)) synchronizer_low(clk,~rst,async_bit,sync_bit_low);
  reset_sync resetter(clk,external_rst,sync_reset);
  reset_sync #(.RESET_ACTIVE(0)) resetter_low(clk,~external_rst,sync_reset_low);
  task tick();@(posedge clk);#1ns;endtask
  initial begin
    string filename;int fd,count,input_raw,y1,y2,y0,yl,f1,f2,f0,fl;
    logic [17:0] golden_rom [0:255];logic [17:0] held;
    if(!$value$plusargs("VECTORS=%s",filename)) $fatal(1,"Missing support vectors");
    fd=$fopen(filename,"r");if(!fd || $fscanf(fd,"%d",count)!=1 || count!=256) $fatal(1,"Invalid support vectors");
    for(int i=0;i<count;i++) begin
      if($fscanf(fd,"%d %d %d %d %d %d %d %d %d",input_raw,y1,f1,y2,f2,y0,f0,yl,fl)!=9) $fatal(1,"Truncated support vector");
      if(i==0 && $test$plusargs("INJECT_MISMATCH")) y1++;
      raw=8'(input_raw);#1ns;
      if($signed(drop_one)!=y1 || overflow[0]!=f1 || $signed(drop_two)!=y2 || overflow[1]!=f2 ||
         $signed(same_fraction)!=y0 || overflow[2]!=f0 || $signed(left_shift)!=yl || overflow[3]!=fl)
        $fatal(1,"[NUMERIC] Rounding/saturation mismatch at %0d",input_raw);
    end
    $fclose(fd);
    for(int i=0;i<1024;i++) begin
      @(negedge clk);wr_en=1;wr_addr=10'(i);wr_data=18'(i*7919+17);tick();
    end
    @(negedge clk);wr_en=0;rd_en=1;
    for(int i=0;i<1024;i++) begin
      rd_addr=10'(i);tick();
      if(rd_data!==18'(i*7919+17)) $fatal(1,"[NUMERIC] RAM mismatch");
      @(negedge clk);
    end
    wr_en=1;wr_addr=0;wr_data=18'h3ffff;rd_addr=0;tick();
    if(rd_data!==18'd17) $fatal(1,"RAM read-during-write is not old data");
    @(negedge clk);wr_en=0;tick();if(rd_data!==18'h3ffff) $fatal(1,"RAM update missing");
    @(negedge clk);rd_en=0;held=rd_data;rd_addr=15;tick();if(rd_data!==held) $fatal(1,"RAM read enable ignored");
    $readmemb(ROM_FILE,golden_rom);
    @(negedge clk);rom_en=1;
    for(int i=0;i<256;i++) begin
      rom_addr=8'(i);tick();if(rom_data!==golden_rom[i]) $fatal(1,"[NUMERIC] ROM mismatch");@(negedge clk);
    end
    rom_en=0;held=rom_data;rom_addr=0;tick();if(rom_data!==held) $fatal(1,"ROM read enable ignored");
    repeat(3) tick();
    if(sync_bit!==0 || sync_bit_low!==0 || sync_reset!==1 || sync_reset_low!==0) $fatal(1,"Reset assertion failed");
    @(negedge clk);rst=0;external_rst=0;async_bit=1;tick();
    if(sync_bit!==0 || sync_bit_low!==0 || sync_reset!==1 || sync_reset_low!==0) $fatal(1,"Synchronizer released too early");
    tick();
    if(sync_bit!==1 || sync_bit_low!==1 || sync_reset!==0 || sync_reset_low!==1) $fatal(1,"Synchronizer latency mismatch");
    @(negedge clk);rst=1;tick();if(sync_bit!==0 || sync_bit_low!==0) $fatal(1,"Bit synchronizer reset failed");
    $display("PASS RTL support: 256 rounding cases, 1024 RAM words, 256 ROM words, synchronizers");$finish;
  end
  initial begin #1ms;$fatal(1,"Support simulation timeout");end
endmodule
