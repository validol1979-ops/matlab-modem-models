function results = matlab_check_research(steps, model_name)
% Проверяем новые схемы отдельно от двадцати уже перенесённых модемов.
if nargin < 1, steps = 16384; end
if nargin < 2, model_name = ''; end
assert(isscalar(steps) && isfinite(steps) && steps > 0 && steps == fix(steps), ...
    'Expected a positive integer number of simulation steps');
root = fileparts(fileparts(mfilename('fullpath')));
destination = fullfile(root, 'build', 'research_review');
if ~isempty(model_name), destination=fullfile(destination,'single',model_name); end
if ~isfolder(destination), mkdir(destination); end
files = dir(fullfile(root, 'research', 'electronix_20260930', 'models', '*.mdl'));
assert(numel(files) == 2, 'Expected the two reviewed research models');
if ~isempty(model_name), files=files(strcmp({files.name},[model_name '.mdl'])); end
assert(~isempty(files), 'No matching research model');
write_json(fullfile(destination,'matlab_results.json'),cell(0,1));
results = cell(numel(files), 1);
for index = 1:numel(files)
    filename = fullfile(files(index).folder, files(index).name);
    [~, model] = fileparts(filename);
    output_dir = fullfile(destination, model);
    if ~isfolder(output_dir), mkdir(output_dir); end
    result = struct('model', model, 'source', filename, 'matlab_version', version, ...
        'status', 'FAIL', 'load_status', 'NOT_RUN', 'compile_status', 'NOT_RUN', ...
        'simulation_status', 'NOT_RUN', 'repeat_status', 'NOT_RUN', ...
        'error_message', '', 'error_report', '', 'requested_steps', steps);
    started = tic;
    stage = 'load';
    try
        load_system(filename);
        result.load_status = 'PASS';
        result.original_stop_time = get_param(model, 'StopTime');
        result.solver = get_param(model, 'Solver');
        % Исходные модели бесконечные; ограничиваем время и отключаем окна в памяти.
        set_param(model, 'DisableAllScopes', 'on');
        stage = 'compile';
        set_param(model, 'SimulationCommand', 'update');
        result.compile_status = 'PASS';
        step = get_param(model, 'CompiledStepSize');
        if ischar(step), step = str2double(step); end
        assert(isscalar(step) && isfinite(step) && step > 0, 'Invalid compiled step size');
        result.step_size = step;
        result.stop_time = steps * step;
        blocks = find_system(model, 'SearchDepth', 1, 'Type', 'Block');
        port_count = 0;
        for k = 1:numel(blocks)
            handles = get_param(blocks{k}, 'PortHandles');
            for p = 1:numel(handles.Outport)
                port = handles.Outport(p);
                if get_param(port, 'Line') < 0, continue; end
                port_count = port_count + 1;
                set_param(port, 'DataLogging', 'on', 'DataLoggingNameMode', 'Custom', ...
                    'DataLoggingName', sprintf('trace_%03d', port_count), ...
                    'DataLoggingDecimateData', 'off', 'DataLoggingLimitDataPoints', 'off');
            end
        end
        set_param(model, 'SignalLogging', 'on', 'SignalLoggingName', 'research_signals', ...
            'SignalLoggingSaveFormat', 'Dataset', 'LimitDataPoints', 'off');
        stage = 'simulation';
        rng(5489, 'twister');
        simulation = sim(model, 'StopTime', sprintf('%.17g', result.stop_time), ...
            'ReturnWorkspaceOutputs', 'on', 'TimeOut', 180);
        [traces, summaries] = export_traces(simulation.get('research_signals'));
        assert(~isempty(traces), 'No signals captured');
        assert(all(cellfun(@(s) s.finite, summaries)), 'Nonfinite signal samples');
        times = simulation.get('tout');
        assert(abs(times(end) - result.stop_time) <= step / 2, 'Simulation stopped early');
        result.final_time = times(end);
        result.signals = summaries;
        result.signal_count = numel(traces);
        result.value_count = sum(cellfun(@(s) s.values, summaries));
        save(fullfile(output_dir, 'signals.mat'), 'traces', '-v7');
        result.simulation_status = 'PASS';
        stage = 'repeat';
        rng(5489, 'twister');
        simulation = sim(model, 'StopTime', sprintf('%.17g', result.stop_time), ...
            'ReturnWorkspaceOutputs', 'on', 'TimeOut', 180);
        [repeated, ~] = export_traces(simulation.get('research_signals'));
        assert(isequaln(traces, repeated), 'Repeated simulation changed captured samples');
        result.repeat_status = 'PASS';
        result.status = 'PASS';
    catch exception
        result.([stage '_status']) = 'FAIL';
        result.error_message = exception.message;
        result.error_report = getReport(exception, 'extended', 'hyperlinks', 'off');
        fprintf('%s\n', result.error_report);
    end
    if bdIsLoaded(model), close_system(model, 0); end
    result.elapsed_seconds = toc(started);
    results{index} = result;
    write_json(fullfile(output_dir, 'result.json'), result);
    fprintf('RESULT %s %s load=%s compile=%s simulation=%s repeat=%s\n', ...
        model, result.status, result.load_status, result.compile_status, ...
        result.simulation_status, result.repeat_status);
end
write_json(fullfile(destination, 'matlab_results.json'), results);
assert(all(cellfun(@(s) strcmp(s.status, 'PASS'), results)), 'Research model checks failed');
end

function [traces, summaries] = export_traces(dataset)
% Сохраняем обычные массивы для последующей проверки в Python и Octave.
traces = cell(dataset.numElements, 1);
summaries = cell(dataset.numElements, 1);
for k = 1:dataset.numElements
    element = dataset.getElement(k);
    data = double(element.Values.Data);
    traces{k} = struct('name', element.Name, 'block', element.BlockPath.getBlock(1), ...
        'port', element.PortIndex, 'time', element.Values.Time, 'data', data);
    summaries{k} = struct('name', element.Name, 'block', traces{k}.block, ...
        'port', element.PortIndex, 'samples', numel(element.Values.Time), ...
        'values', numel(data), 'finite', ~isempty(data) && all(isfinite(data(:))), ...
        'rms', sqrt(mean(abs(data(:)).^2)), 'last_real', real(data(end)), 'last_imag', imag(data(end)));
end
end

function write_json(filename, value)
file = fopen(filename, 'w');
assert(file >= 0, 'Cannot write report');
cleanup = onCleanup(@() fclose(file));
fprintf(file, '%s\n', jsonencode(value));
end
