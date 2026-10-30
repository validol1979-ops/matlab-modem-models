# Deterministic package assignments for the benchmark harness, not a board.
load_package advanced_device
set part [lindex $quartus(args) 0]
set destination [lindex $quartus(args) 1]
load_device -part $part
set pins {}
set output_pins {}
set clock_pin ""
for {set i 0} {$i < [get_pad_data INT_PAD_COUNT]} {incr i} {
    if {![get_pad_data BOOL_IS_BONDED -pad $i]} {continue}
    if {[catch {get_pad_data STRING_TYPE_NAME -pad $i} type]} {continue}
    if {![string match "*I/O" $type]} {continue}
    set pin [get_pad_data STRING_USER_PIN_NAME -pad $i]
    set functions [get_pad_data STRING_AUXILIARY_FUNCTION_NAME -pad $i]
    if {$clock_pin eq "" && [regexp {(^|, )CLK[0-9]+p(,|$)} $functions]} {set clock_pin $pin}
    if {$type eq "Row I/O" && ![regexp {HPS|RZQ} $functions]} {lappend output_pins $pin}
    if {![regexp {HPS|CLK|DATA|PR_|RZQ} $functions]} {lappend pins $pin}
}
if {$clock_pin eq "" || [llength $pins]<22 || [llength $output_pins]<41} {error "Insufficient package pins"}
set input_ports {rst load enable m_ready}
for {set i 0} {$i<18} {incr i} {lappend input_ports "seed\[$i\]"}
set ports {}
for {set i 0} {$i<36} {incr i} {lappend ports "data\[$i\]"}
lappend ports {overflow[0]} {overflow[1]} valid ready last
set fd [open $destination w]
puts $fd "set_location_assignment PIN_$clock_pin -to clk"
foreach port $input_ports pin [lrange $pins 0 21] {
    puts $fd "set_location_assignment PIN_$pin -to {$port}"
}
foreach port $ports pin [lrange $output_pins 0 40] {
    puts $fd "set_location_assignment PIN_$pin -to {$port}"
}
close $fd
unload_device
