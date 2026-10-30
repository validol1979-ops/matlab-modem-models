int sy_bounds_checks;
`define SYNTH_DUT dut_synthesis
generate begin : synthesis_observer
  localparam string check_prefix="stft";
  wire check_done=ao_total>0&&ao_checked==ao_total&&so_checked==so_total;
  `include "istft_observer.svh"
end endgenerate
`undef SYNTH_DUT
`define ANALYSIS_DUT dut_analysis
`include "stft_analysis_bounds.svh"
`undef ANALYSIS_DUT
task automatic check_stft_bounds();
  if(an_bounds_checks<1 || sy_bounds_checks<1) $fatal(1,"[BOUNDS] STFT monitor not exercised");
  if(an_queued!=0) $fatal(1,"[BOUNDS] STFT flags did not drain");
  $display("PASS BOUNDS stft: %0d checks",an_bounds_checks+sy_bounds_checks);
endtask
