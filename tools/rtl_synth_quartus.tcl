# Arguments: project root, output directory, top, part, SDC, source list.
load_package project
load_package flow
set root [lindex $quartus(args) 0]
set output [lindex $quartus(args) 1]
set top [lindex $quartus(args) 2]
set part [lindex $quartus(args) 3]
set constraints [lindex $quartus(args) 4]
set sources [lindex $quartus(args) 5]
set kind [lindex $quartus(args) 6]
cd $output
puts "RTL_FLOW_STAGE project"
if {[catch {project_new $output/$top -overwrite} problem options]} {puts stderr "PROJECT ERROR: $problem";puts stderr [dict get $options -errorinfo];error $problem}
set_global_assignment -name FAMILY "Cyclone V"
set_global_assignment -name DEVICE $part
set_global_assignment -name TOP_LEVEL_ENTITY rtl_synth_top
set_parameter -name DUT_KIND $kind
set_global_assignment -name NUM_PARALLEL_PROCESSORS 2
set_global_assignment -name PROJECT_OUTPUT_DIRECTORY $output/output_files
set_global_assignment -name SDC_FILE $constraints
# A registered physical IO harness keeps pin counts within both packages.
set_instance_assignment -name IO_STANDARD "2.5 V" -to *
set output_ports {valid ready last}
for {set i 0} {$i<36} {incr i} {lappend output_ports "data\[$i\]"}
for {set i 0} {$i<2} {incr i} {lappend output_ports "overflow\[$i\]"}
foreach port $output_ports {
    set_instance_assignment -name CURRENT_STRENGTH_NEW "16MA" -to $port
    set_instance_assignment -name SLEW_RATE 1 -to $port
    set_instance_assignment -name FAST_OUTPUT_REGISTER ON -to $port
    set_instance_assignment -name BOARD_MODEL_FAR_C [expr {1e-12*[lindex $quartus(args) 8]}] -to $port
}

source [lindex $quartus(args) 7]
set_global_assignment -name SEARCH_PATH "$root/rtl/modems/bpsk_costas_2008_08_25"
set fd [open $sources r]
foreach filename [split [read $fd] "\n"] {if {$filename ne ""} {set_global_assignment -name SYSTEMVERILOG_FILE $filename}}
close $fd
export_assignments
set phase [lindex $quartus(args) 9]
if {$phase eq "map"} {
    execute_module -tool map
    project_close
    qexit -success
}
execute_flow -compile
load_package report
load_report
set fd [open $output/resources.tsv w]
foreach name [get_report_panel_names] {
    if {[string match "*Fitter Resource Usage Summary" $name]} {
        set id [get_report_panel_id $name]
        for {set row 0} {$row < [get_number_of_rows -id $id]} {incr row} {
            puts $fd [join [get_report_panel_row -id $id -row $row] "\t"]
        }
    }
}
close $fd
unload_report
project_close
