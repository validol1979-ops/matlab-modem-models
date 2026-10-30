function modem_cross_test(cfg, directory)
  % Входной шум читается из общего файла; генераторы случайных чисел не смешиваются.
  max_tx = 0; max_rx = 0;
  for c = 0:2
    fd = fopen(fullfile(directory,sprintf('case_%d.txt',c)),'r');
    assert(fd>=0,'Cannot open shared vectors');
    guard = onCleanup(@() fclose(fd));
    header = fscanf(fd,'%d',5);
    count=header(1); nrx=header(2); ntx=header(3); training=header(4); branches=header(5);
    data=fscanf(fd,'%d',count).';
    values=fscanf(fd,'%f',[2 nrx]); wave=values(1,:)+1i*values(2,:);
    if branches==2
      values=fscanf(fd,'%f',[2 nrx]); branch_b=values(1,:)+1i*values(2,:);
      values=fscanf(fd,'%f',[2 2]); gains=values(1,:)+1i*values(2,:);
      wave=modem_core('combine',[wave;branch_b],gains);
    end
    values=fscanf(fd,'%f',[2 ntx]); expected_tx=values(1,:)+1i*values(2,:);
    expected_data=fscanf(fd,'%d',count).';
    values=fscanf(fd,'%f',[2 count]); expected_symbols=values(1,:)+1i*values(2,:);
    estimates=fscanf(fd,'%f',2);
    clear guard;
    tx=modem_core('transmit',cfg,data);
    rx=modem_core('receive',cfg,wave,data(1:training),count);
    tx_error=max(abs(tx.waveform-expected_tx)); rx_error=max(abs(rx.symbols-expected_symbols));
    assert(tx_error<1e-7,'Python and Octave transmit mismatch');
    assert(rx_error<1e-7,'Python and Octave receive mismatch');
    assert(isequal(rx.data,expected_data),'Python and Octave decoded data mismatch');
    assert(isequal(rx.data(training+1:end),data(training+1:end)),'Payload mismatch');
    assert(abs(rx.delay-estimates(1))<1e-8,'Delay estimate mismatch');
    assert(abs(rx.frequency-estimates(2))<1e-10,'Frequency estimate mismatch');
    max_tx=max(max_tx,tx_error); max_rx=max(max_rx,rx_error);
  end
  fprintf('PASS %s cross-language TX %.12g RX %.12g\n',cfg.name,max_tx,max_rx);
end
