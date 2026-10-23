function results = run_demo()
%RUN_DEMO Два исходных примера test_compare без сохранения файлов.
root = fileparts(mfilename('fullpath'));
oldPath = path;
cleanup = onCleanup(@() path(oldPath)); %#ok<NASGU>
addpath(root);
fprintf('Lowpass: Fc=10 kHz, Fstop=12 kHz, Fs=64 kHz, attenuation=40 dB\n');
results.lowpass = compare_filters(10e3, 12e3, 64e3, 40);
plotres(results.lowpass);
set(gcf, 'Name', 'Window comparison: 40 dB lowpass', 'NumberTitle', 'off');
format_response(64e3);
fprintf('\nAnti-aliasing: Fc=3.5 kHz, Fstop=7 kHz, Fs=256 kHz, attenuation=74 dB\n');
results.antialias = compare_filters(3.5e3, 7e3, 256e3, 74);
plotres(results.antialias);
set(gcf, 'Name', 'Window comparison: 74 dB anti-aliasing', 'NumberTitle', 'off');
format_response(256e3);
drawnow;
end

function format_response(fs)
set(gcf, 'Position', [100 100 900 550]);
legend('Location', 'eastoutside');
set(gca, 'FontSize', 11, 'Position', [0.12 0.14 0.62 0.78]);
xlim([0 fs/2]);
ylim([-140 5]);
end
