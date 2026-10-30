function test_original()
% Отдельная проверка новых оригиналов без изменения архивных файлов.
root = fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
addpath(fullfile(root,'tools'));
matlab_check_research(16384,'oqpsk_2_sps_timing_recovery_2019_12_05');
end
