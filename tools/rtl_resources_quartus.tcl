# Read resources from a completed standalone map/fit run.
load_package project
load_package report
set output [lindex $quartus(args) 0]
set top [lindex $quartus(args) 1]
cd $output
project_open $output/$top
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
