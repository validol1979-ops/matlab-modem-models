module tb_top;
  timeunit 1ns; timeprecision 1ps;
  import uvm_pkg::*;
  import modem_uvm_pkg::*;
  logic clk=0;
  always #5ns clk=~clk;
  modem_if bus(clk);
  modem_variant dut(bus);
  initial begin
    uvm_config_db#(virtual modem_if)::set(null,"*","vif",bus);
    run_test("modem_test");
  end
  initial begin
    #100us; $fatal(1,"Testbench watchdog expired");
  end
endmodule
