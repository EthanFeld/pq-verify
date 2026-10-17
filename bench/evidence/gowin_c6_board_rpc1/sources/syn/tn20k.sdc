create_clock -name clk_27 -period 37.037 [get_ports {clk_27}]
create_generated_clock -name core_clk -source [get_ports {clk_27}] -multiply_by 10 -divide_by 7 [get_nets {core_clk}]
# PLL lock qualification asynchronously asserts the two-stage reset synchronizer.
# Its output releases reset synchronously in the core domain. Exclude only the
# synchronizer's asynchronous clear pins; core data/reset-release paths stay timed.
set_false_path -to [get_pins {reset_sync*/CLEAR}]
