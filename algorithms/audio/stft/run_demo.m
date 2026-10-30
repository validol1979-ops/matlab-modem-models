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
    'stft.m';
    'istft.m';
    'biorwin.m';
    'shiftcir.m';
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
fs = 8000;
t = (0:4095)'/fs;
x = sin(2*pi*(300*t + 1200*t.^2));
nfft = 256;
hop = 128;
% hanning должна быть доступна исходным stft/istft по имени.
assert(exist('hanning', 'file') == 2, 'hanning is required (Signal Processing Toolbox in MATLAB).');
Y = stft(x, nfft, hop, 1, 'hanning');
y = istft(Y, nfft, hop, 1, 'hanning');
interior = nfft+1:numel(y)-nfft;
err = max(abs(x(interior)-y(interior)));
assert(all(isfinite(y)) && err < 1e-10, 'STFT interior reconstruction failed.');
figure('Name', 'Original STFT/ISTFT: chirp and reconstruction', 'NumberTitle', 'off');
subplot(2,1,1);
imagesc((0:size(Y,2)-1)*hop/fs, (0:nfft/2)*fs/nfft, 20*log10(abs(Y)+eps));
axis xy; xlabel('Time (s)'); ylabel('Frequency (Hz)'); colorbar;
subplot(2,1,2); plot(t, x, t(1:numel(y)), y, '--'); grid on;
xlabel('Time (s)'); ylabel('Amplitude'); legend('Input', 'Reconstructed');
fprintf('Original STFT: max interior reconstruction error = %.3g\n', err);
results = struct('spectrum', Y, 'reconstructed', y, 'interior_error', err);
drawnow;
end

function restore_state(oldPath, oldRng)
path(oldPath);
rng(oldRng);
end
