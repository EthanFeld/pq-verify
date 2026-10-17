# Fit the isolated Keccak core with Gowin EDA for a one-pin timing datapoint.
set repo [file normalize [file join [file dirname [info script]] ..]]
set out [file join $repo build gowin_keccak_rpc1]
if {[info exists ::env(PQ_VERIFY_BUILD_DIR)]} {
    set out [file normalize $::env(PQ_VERIFY_BUILD_DIR)]
}
file mkdir $out
create_project -name keccak_ooc -dir $out -pn GW2AR-LV18QN88C8/I7 -device_version C -force
set_device -name GW2AR-18C GW2AR-LV18QN88C8/I7
if {[info exists ::env(PQ_VERIFY_REUSE_NETLIST)]} {
    add_file -type netlist [file normalize $::env(PQ_VERIFY_REUSE_NETLIST)]
} else {
    add_file -type verilog [file join $out keccak_ooc.v]
}
add_file -type cst [file join $repo syn keccak_ooc.cst]
add_file -type sdc [file join $repo syn keccak_ooc.sdc]
set_option -top_module keccak_ooc_top
set_option -output_base_name keccak_ooc
set_option -synthesis_tool gowinsynthesis
set_option -verilog_std v2001
set_option -frequency 27.0
set_option -timing_driven 1
set_option -maxfan 64
set_option -replicate_resources 1
set place_option 0
if {[info exists ::env(PQ_VERIFY_PLACE_OPTION)]} {
    set place_option $::env(PQ_VERIFY_PLACE_OPTION)
}
set route_option 0
if {[info exists ::env(PQ_VERIFY_ROUTE_OPTION)]} {
    set route_option $::env(PQ_VERIFY_ROUTE_OPTION)
}
set_option -place_option $place_option
set_option -route_option $route_option
set_option -gen_text_timing_rpt 1
set_option -bit_compress 1
if {[info exists ::env(PQ_VERIFY_REUSE_NETLIST)]} {
    run pnr
} else {
    run all
}
