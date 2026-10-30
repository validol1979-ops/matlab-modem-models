function result = test_original()
% Проверяем только исходную схему текущего каталога с указанными адаптациями.
here = fileparts(mfilename('fullpath'));
root = fileparts(fileparts(fileparts(here)));
addpath(fullfile(root, 'tools'));
[~, name] = fileparts(fileparts(here));
results = matlab_check_originals('compatible', name);
result = results{1};
assert(strcmp(result.status, 'PASS'), '%s', result.error_report);
end
