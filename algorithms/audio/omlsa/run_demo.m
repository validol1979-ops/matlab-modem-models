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
    'omlsa.m';
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
workDir = tempname;
mkdir(workDir);
fileCleanup = onCleanup(@() rmdir(workDir, 's')); %#ok<NASGU>
fs = 16000;
t = (0:fs-1)'/fs;
clean = 0.15*sin(2*pi*440*t).*(t > 0.25);
x = clean + 0.03*randn(size(t));
fin = fullfile(workDir, 'noisy.wav');
fout = fullfile(workDir, 'enhanced');
% Исходник ожидает PCM16 с заголовком из 44 байт и дописывает .wav сам.
audiowrite(fin, x, fs, 'BitsPerSample', 16);
omlsa(fin, fout);
% У исходника выходной заголовок сохраняет длину входа; читаем PCM напрямую.
fid = fopen([fout '.wav'], 'rb');
assert(fid >= 0, 'OM-LSA output file was not created.');
readCleanup = onCleanup(@() fclose(fid)); %#ok<NASGU>
fseek(fid, 44, 'bof');
y = fread(fid, Inf, 'int16')/2^15;
clear readCleanup;
assert(~isempty(y) && all(isfinite(y)), 'OM-LSA returned invalid samples.');
figure('Name', 'Original OM-LSA/IMCRA: synthetic tone in noise', 'NumberTitle', 'off');
subplot(2,1,1); plot(t, x); grid on; xlabel('Time (s)'); ylabel('Input');
subplot(2,1,2); plot((0:numel(y)-1)/fs, y); grid on;
xlabel('Time (s)'); ylabel('Enhanced');
fprintf('Original OM-LSA: %d input, %d output samples\n', numel(x), numel(y));
results = struct('input', x, 'enhanced', y, 'sample_rate', fs);
drawnow;
end

function restore_state(oldPath, oldRng)
path(oldPath);
rng(oldRng);
end
