function modem_test(cfg)
  % Независимая проверка всех меток созвездия и передачи кадра без шума.
  data = repmat(0:cfg.order-1,1,ceil(512/cfg.order));
  [ids, symbols] = modem_core('encode',cfg,data);
  assert(isequal(modem_core('decode',cfg,ids),data),'Differential codec mismatch');
  tx = modem_core('transmit',cfg,data);
  assert(all(isfinite(tx.waveform)),'Nonfinite transmit sample');
  if any(strcmp(cfg.family,{'msk','gmsk'}))
    assert(max(abs(abs(tx.waveform)-1)) < 1e-12,'CPM envelope mismatch');
  end
  rng(21,'twister');
  data = randi([0 cfg.order-1],1,768);
  tx = modem_core('transmit',cfg,data);
  rx = modem_core('receive',cfg,tx.waveform,data(1:192),numel(data));
  assert(isequal(rx.data(193:end),data(193:end)),'Noiseless loopback mismatch');
  fprintf('PASS %s Octave codec and waveform loopback\n',cfg.name);
end
