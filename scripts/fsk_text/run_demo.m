function results = run_demo()
%RUN_DEMO Передача текста исходными функциями FSK, без сохранения PNG.
here = fileparts(mfilename('fullpath'));
oldpath = path;
pathCleanup = onCleanup(@() path(oldpath)); %#ok<NASGU>
addpath(fullfile(here, 'Fourier Analysis & Frequency-Based Communication', 'code'));
state = rng;
rngCleanup = onCleanup(@() rng(state)); %#ok<NASGU>
rng(7, 'twister');
message = 'signal';
fs = 100;
rates = [1 5];
results = struct([]);
figure('Name', 'FSK: text, waveform and detected frequencies', 'NumberTitle', 'off', ...
    'Position', [80 80 1000 650]);
for k = 1:numel(rates)
    rate = rates(k);
    tx = freq_coding(message, rate);
    rx = tx + 0.01*randn(size(tx));
    decoded = freq_decoding(rx, rate);
    assert(strcmp(decoded, message), 'FSK text round trip failed.');
    fprintf('%d-FSK, %d bit/s: "%s" -> "%s" (noise variance 0.0001)\n', ...
        2^rate, rate, message, decoded);
    segments = reshape(rx, fs, []);
    spectrum = abs(fft(segments));
    [~, bins] = max(spectrum(2:50, :), [], 1);
    detected = bins; % Бины 2:50 соответствуют частотам 1:49 Гц.
    subplot(2,2,2*k-1);
    plot((0:numel(tx)-1)/fs, rx);
    grid on; xlabel('Time (s)'); ylabel('Amplitude');
    title(sprintf('%d-FSK, decoded: %s', 2^rate, decoded));
    subplot(2,2,2*k);
    stairs(0:numel(detected)-1, detected, 'o-');
    grid on; ylim([0 50]); xlabel('Symbol index'); ylabel('Detected frequency (Hz)');
    title(sprintf('%d bits / 1-second symbol', rate));
    results(k).bit_rate = rate;
    results(k).decoded = decoded;
    results(k).detected_hz = detected;
end
noisevars = [0 0.01 0.1 0.5 1 2 3 5];
errors = zeros(numel(rates), numel(noisevars));
for k = 1:numel(rates)
    tx = freq_coding(message, rates(k));
    for j = 1:numel(noisevars)
        decoded = freq_decoding(tx + sqrt(noisevars(j))*randn(size(tx)), rates(k));
        errors(k,j) = sum(decoded ~= message);
    end
    results(k).noise_variances = noisevars;
    results(k).character_errors = errors(k,:);
end
figure('Name', 'FSK: noise experiment', 'NumberTitle', 'off');
plot(noisevars, errors.', 'o-'); grid on;
xlabel('Noise variance'); ylabel('Wrong characters out of 6');
legend('2-FSK, 1 bit/s', '32-FSK, 5 bit/s', 'Location', 'best');
title('One noise realization per point; not a BER estimate');
drawnow;
end
