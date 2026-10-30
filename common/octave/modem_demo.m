function report = modem_demo(cfg)
  % Фиксированное начальное состояние обеспечивает повторяемость примера.
  rng(19,'twister');
  data = randi([0 cfg.order-1],1,768);
  tx = modem_core('transmit',cfg,data);
  n = 0:numel(tx.waveform)+7;
  wave = 0.65 * modem_core('cubic',tx.waveform,n-2.25).*exp(1i*(0.38+2*pi*0.00015*n));
  sigma = sqrt(mean(abs(wave).^2)/10^(28/10)/2);
  wave = wave + sigma*(randn(size(wave))+1i*randn(size(wave)));
  rx = modem_core('receive',cfg,wave,data(1:192),numel(data));
  errors = sum(rx.data(193:end) ~= data(193:end));
  report = struct('modem',cfg.name,'payload_symbols',576,'symbol_errors',errors, ...
                  'ser',errors/576,'estimated_delay',rx.delay,'estimated_frequency',rx.frequency);
  fprintf('%s\n',jsonencode(report));
end
