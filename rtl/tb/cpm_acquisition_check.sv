// Every pass1 owns precisely the increments0..1041 of its current frame.
`timescale 1ns/1ps
`include "uvm_macros.svh"
module cpm_acquisition_check #(parameter bit RESET_ACTIVE=1)(
 input logic clk,rst,pass1,inc_valid,
 input logic [10:0] inc_index,
 output int epochs=0,checks=0
);
 import uvm_pkg::*;
 bit previous_pass=0;
 int seen=0;
 always @(posedge clk) begin
  if(rst==RESET_ACTIVE) begin previous_pass=0;seen=0;epochs=0;checks=0;end
  else begin
   if(pass1&&!previous_pass) begin seen=0;epochs++;end
   if(pass1&&inc_valid) begin
    if(inc_index!==11'(seen)||seen>=1042)
      `uvm_fatal("ACQ_EPOCH",$sformatf("CPM acquisition epoch=%0d increment=%0d expected=%0d; stale/data token entered pass1",epochs,inc_index,seen))
    seen++;checks++;
   end
   if(!pass1&&previous_pass&&seen!=1042)
     `uvm_fatal("ACQ_EPOCH",$sformatf("Incomplete CPM acquisition increments: %0d",seen))
   previous_pass=pass1;
  end
 end
endmodule
