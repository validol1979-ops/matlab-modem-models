# Evaluate every available device operating condition on the fitted netlist.
load_package project
load_package sta
set output [lindex $quartus(args) 0]
set top [lindex $quartus(args) 1]
project_open $output/$top
create_timing_netlist
read_sdc
update_timing_netlist
set fd [open $output/timing.tsv w]
foreach_in_collection condition [get_available_operating_conditions] {
    set_operating_conditions $condition
    update_timing_netlist
    set setup [get_timing_paths -setup -npaths 1]
    set hold [get_timing_paths -hold -npaths 1]
    if {[get_collection_size $setup] == 0 || [get_collection_size $hold] == 0} {error "Missing timing paths"}
    foreach_in_collection path $setup {set setup_slack [get_path_info -slack $path]}
    foreach_in_collection path $hold {set hold_slack [get_path_info -slack $path]}
    report_timing -setup -npaths 10 -file $output/setup_[get_operating_conditions_info -model $condition]_[get_operating_conditions_info -temperature $condition].rpt
    report_timing -hold -npaths 10 -file $output/hold_[get_operating_conditions_info -model $condition]_[get_operating_conditions_info -temperature $condition].rpt
    set label "[get_operating_conditions_info -model $condition] [get_operating_conditions_info -voltage $condition]mV [get_operating_conditions_info -temperature $condition]C"
    puts $fd "$label\t$setup_slack\t$hold_slack"
}
close $fd
report_timing -setup -npaths 10 -file $output/setup.rpt
report_timing -hold -npaths 10 -file $output/hold.rpt
report_ucp -file $output/unconstrained.rpt
report_clock_fmax_summary -file $output/fmax.rpt
delete_timing_netlist
project_close
