# Arguments: project root, output directory, top, part, XDC, source list.
set root [lindex $argv 0]
set output [lindex $argv 1]
set top [lindex $argv 2]
set part [lindex $argv 3]
set constraints [lindex $argv 4]
set sources [lindex $argv 5]
set kind [lindex $argv 6]
cd $output
set_param general.maxThreads 2
set_property include_dirs [list "$root/rtl/modems/bpsk_costas_2008_08_25"] [current_fileset]
set fd [open $sources r]
foreach filename [split [read $fd] "\n"] {if {$filename ne ""} {read_verilog -sv $filename}}
close $fd
synth_design -top rtl_synth_top -part $part -generic DUT_KIND=$kind
read_xdc $constraints
set_property IOSTANDARD LVCMOS18 [get_ports *]
set_property SLEW FAST [get_ports -filter {DIRECTION == OUT}]
set_property PACKAGE_PIN W5 [get_ports clk]
set available_pins [lsort [get_package_pins -filter {IS_GENERAL_PURPOSE == 1 && IS_CLK_CAPABLE == 0}]]
set index 0
foreach port [lsort [get_ports -filter {NAME != clk}]] {
  if {$index >= [llength $available_pins]} {error "Not enough harness IO pins"}
  set_property PACKAGE_PIN [lindex $available_pins $index] $port
  incr index
}
# Implementation-only hold guard band: hold fixing and routing see 0.05 ns more hold
# uncertainty, so fixed paths do not stop at exactly zero slack. The contract value from
# the XDC is restored before every signoff report and metric below.
set xdc_fd [open $constraints r]
set xdc_text [read $xdc_fd]
close $xdc_fd
if {![regexp {set_clock_uncertainty -from \[get_clocks core_clk\] -to \[get_clocks core_clk\] ([0-9.]+)} $xdc_text -> contract_uncertainty]} {error "Clock uncertainty not found"}
opt_design
place_design
set_clock_uncertainty -hold -from [get_clocks core_clk] -to [get_clocks core_clk] [expr {$contract_uncertainty + 0.05}]
phys_opt_design -hold_fix
route_design -directive Explore
set_clock_uncertainty -hold -from [get_clocks core_clk] -to [get_clocks core_clk] $contract_uncertainty
report_utilization -file $output/utilization.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file $output/timing.rpt
report_timing -delay_type max -max_paths 25 -nworst 1 -file $output/critical.rpt
report_drc -checks {LUTLP-1} -file $output/loops.rpt
if {[llength [get_drc_violations -quiet LUTLP*]] != 0} {error "Combinational loop detected"}
if {[llength [get_cells -quiet -hier -filter {REF_NAME =~ LD*}]] != 0} {error "Latch detected"}
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup] == 0 || [llength $hold] == 0} {error "Missing timing paths"}
set fd [open $output/metrics.tsv w]
puts $fd "setup_slack_ns\t[get_property SLACK [lindex $setup 0]]"
puts $fd "hold_slack_ns\t[get_property SLACK [lindex $hold 0]]"
foreach {label pattern} {lut LUT* registers FD* dsp DSP* bram RAMB*} {
    puts $fd "$label\t[llength [get_cells -quiet -hier -filter "REF_NAME =~ $pattern"]]"
}
close $fd
write_checkpoint -force $output/routed.dcp
