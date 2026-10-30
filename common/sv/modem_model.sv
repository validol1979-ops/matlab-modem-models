module modem_model(modem_if bus);
  import modem_dsp_pkg::*;
  modem_dsp dsp;
  string config_path;
  labels_t preamble;
  samples_t combined;

  initial begin
    if (!$value$plusargs("CONFIG=%s",config_path)) $fatal(1,"Missing CONFIG argument");
    dsp=new(config_path);
  end

  // Один запрос передаёт кадр; тактовый интерфейс задаёт границу транзакции.
  // Вещественная обработка внутри такта является поведенческой, не RTL.
  always @(posedge bus.clk) begin
    if (!bus.rst_n) begin
      bus.done <= 0;
      bus.output_data.delete(); bus.output_wave.delete(); bus.output_symbols.delete();
      bus.estimated_delay=0; bus.estimated_frequency=0;
    end else begin
      bus.done <= 0;
      if (bus.valid) begin
        preamble=new[bus.training_count];
        foreach(preamble[k]) preamble[k]=bus.input_data[k];
        dsp.transmit(bus.input_data,bus.output_wave);
        if(bus.branches==2) dsp.combine(bus.input_wave,bus.input_wave_b,bus.gain_a,bus.gain_b,1,1,combined);
        else combined=bus.input_wave;
        dsp.receive(combined,preamble,bus.input_data.size(),bus.output_data,
                    bus.output_symbols,bus.estimated_delay,bus.estimated_frequency);
        bus.done <= 1;
      end
    end
  end
endmodule
