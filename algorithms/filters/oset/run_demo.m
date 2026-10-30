function results = run_demo()
%RUN_DEMO Короткий опыт с исходной реализацией из original/.
here = fileparts(mfilename('fullpath'));
original = fullfile(here, 'original');
if exist(original, 'dir') ~= 7
    error('modems:MissingOriginal', ...
        'исходные скрипты не входят в публичный репозиторий, см. THIRD_PARTY.md');
end
% Проверяем комплект до добавления путей и запуска вычислений.
sourceFiles = {
    'matlab/tools/generic/notch_filter_cls.m';
};
for sourceIndex = 1:numel(sourceFiles)
    if exist(fullfile(original, sourceFiles{sourceIndex}), 'file') ~= 2
        error('modems:MissingSource', 'Missing original file: %s', sourceFiles{sourceIndex});
    end
end
oldPath = path;
oldRng = rng;
cleanup = onCleanup(@() restore_state(oldPath, oldRng)); %#ok<NASGU>
addpath(original);
rng(7, 'twister');
addpath(fullfile(original, 'matlab', 'tools', 'generic'));
fs = 500;
t = (0:499)/fs;
clean = sin(2*pi*10*t);
x = clean + 0.7*sin(2*pi*50*t) + 0.05*randn(size(t));
% Короткий вход: исходник строит плотные матрицы и вычисляет SVD.
y = notch_filter_cls(x, 50/fs, 100);
assert(all(isfinite(y)), 'OSET returned non-finite samples.');
figure('Name', 'Original OSET: constrained least squares notch', 'NumberTitle', 'off');
subplot(2,1,1); plot(t, [clean; x; y].'); grid on;
xlabel('Time (s)'); ylabel('Amplitude'); legend('Clean', 'Input', 'Filtered');
subplot(2,1,2); f = (0:250)*fs/numel(x);
X = abs(fft(x)); Y = abs(fft(y));
plot(f, 20*log10([X(1:251); Y(1:251)].'+eps)); grid on;
xlabel('Frequency (Hz)'); ylabel('Magnitude (dB)'); legend('Input', 'Filtered');
results = struct('input', x, 'filtered', y, 'mse', mean((y-clean).^2));
fprintf('OSET notch: MSE relative to clean signal = %.6g\n', results.mse);
drawnow;
end

function restore_state(oldPath, oldRng)
path(oldPath);
rng(oldRng);
end
