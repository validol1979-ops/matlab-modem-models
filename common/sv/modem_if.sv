interface modem_if(input logic clk);
  import modem_dsp_pkg::*;
  logic rst_n=0, valid=0, done;
  int case_id, training_count, branches=1;
  labels_t input_data, output_data;
  samples_t input_wave, output_wave, output_symbols;
  samples_t input_wave_b;
  complex_t gain_a,gain_b;
  real estimated_delay, estimated_frequency;
endinterface
