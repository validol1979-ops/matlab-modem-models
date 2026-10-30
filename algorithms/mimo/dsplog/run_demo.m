function run_demo()
%RUN_DEMO Исходный полный Monte Carlo: BPSK, Rayleigh MIMO 2x2 и ZF.
here = fileparts(mfilename('fullpath'));
original = fullfile(here, 'original');
if exist(original, 'dir') ~= 7
    error('modems:MissingOriginal', ...
        'исходные скрипты не входят в публичный репозиторий, см. THIRD_PARTY.md');
end
% Проверяем комплект до добавления путей и запуска вычислений.
sourceFiles = {
    'script_ber_mimo_zf_bpsk_rayleigh_channel.m';
};
for sourceIndex = 1:numel(sourceFiles)
    if exist(fullfile(original, sourceFiles{sourceIndex}), 'file') ~= 2
        error('modems:MissingSource', 'Missing original file: %s', sourceFiles{sourceIndex});
    end
end
oldPath = path;
oldDir = pwd;
oldRng = rng;
workDir = tempname;
mkdir(workDir);
cleanup = onCleanup(@() restore_state(oldPath, oldDir, oldRng, workDir)); %#ok<NASGU>
addpath(original);
cd(workDir);
rng(7, 'twister');
fprintf('Original MIMO ZF: 10^6 bits per point, Eb/N0 = 0:25 dB; this may take several minutes.\n');
run_original(fullfile(original, 'script_ber_mimo_zf_bpsk_rayleigh_channel.m'));
drawnow;
end

function run_original(source)
% clear из исходника действует только в этой области переменных.
eval(fileread(source));
end

function restore_state(oldPath, oldDir, oldRng, workDir)
cd(oldDir);
path(oldPath);
rng(oldRng);
rmdir(workDir, 's');
end
