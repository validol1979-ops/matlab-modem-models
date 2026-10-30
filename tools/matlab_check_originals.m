function results = matlab_check_originals(mode, modem_name, steps)
% Проверяем архивные схемы в памяти, не перезаписывая исходные MDL.
if nargin < 1, mode = 'audit'; end
if nargin < 2, modem_name = ''; end
if nargin < 3, steps = 16384; end
assert(any(strcmp(mode, {'audit', 'original', 'compatible'})), 'Unknown mode');
root = fileparts(fileparts(mfilename('fullpath')));
destination = fullfile(root, 'build', 'matlab_originals', mode);
if ~isempty(modem_name), destination = fullfile(destination, 'single', modem_name); end
assert(isscalar(steps) && isfinite(steps) && steps>0 && steps==fix(steps), 'Invalid simulation steps');
if ~isfolder(destination), mkdir(destination); end
workspaces = dir(fullfile(root, 'modems', '*', 'config.json'));
results = cell(0, 1);
write_json(fullfile(destination, 'results.json'), results);
for index = 1:numel(workspaces)
    workspace = workspaces(index).folder;
    [~, name] = fileparts(workspace);
    if ~isempty(modem_name) && ~strcmp(name, modem_name), continue; end
    configuration = jsondecode(fileread(fullfile(workspace, 'config.json')));
    % Новая подборка проверяется отдельным инструментом и не меняет старый отчёт.
    if isfield(configuration, 'research_addition') && configuration.research_addition
        if ~isempty(modem_name)
            error('Use matlab_check_research or matlab_research_references for research additions');
        end
        continue;
    end
    original = dir(fullfile(workspace, 'original', '*.mdl'));
    assert(numel(original) == 1, 'Expected one original model');
    filename = fullfile(original.folder, original.name);
    if strcmp(mode, 'compatible')
        filename = fullfile(workspace, 'matlab', original.name);
    end
    [~, model] = fileparts(filename);
    output_dir = fullfile(destination, name);
    if ~isfolder(output_dir), mkdir(output_dir); end
    log_file = fullfile(output_dir, 'matlab.log');
    file = fopen(log_file, 'w'); fclose(file);
    diary(log_file);
    fprintf('CHECK %s mode=%s\n', name, mode);
    result = struct('name', name, 'source', filename, 'matlab_version', version, ...
        'mode', mode, 'load_status', 'NOT_RUN', 'compile_status', 'NOT_RUN', ...
        'simulation_status', 'NOT_RUN', 'status', 'FAIL', 'error_identifier', '', ...
        'repeat_status', 'NOT_RUN', 'error_message', '', 'error_report', '', 'elapsed_seconds', 0);
    started = tic;
    stage = 'load';
    try
        load_system(filename);
        result.load_status = 'PASS';
        result.original_stop_time = get_param(model, 'StopTime');
        result.solver = get_param(model, 'Solver');
        result.top_blocks = inspect_blocks(model);
        result.runtime_changes = cell(0, 1);
        if strcmp(mode, 'compatible') && strcmp(name, 'simo_maximal_ratio_combining_2010_08_27')
            % Два антенных канала заданы Mux исходной схемы; задержка общая и скалярная.
            set_param([model '/cubic_farrow_interpolator/in'], 'PortDimensions', '2');
            set_param([model '/cubic_farrow_interpolator/mu'], 'PortDimensions', '1');
            result.runtime_changes{end + 1} = struct('block', [model '/cubic_farrow_interpolator/in'], ...
                'parameter', 'PortDimensions', 'value', '2');
            result.runtime_changes{end + 1} = struct('block', [model '/cubic_farrow_interpolator/mu'], ...
                'parameter', 'PortDimensions', 'value', '1');
        end
        % Графические окна не нужны пакетной проверке; алгоритм не меняется.
        set_param(model, 'DisableAllScopes', 'on');
        stage = 'compile';
        set_param(model, 'SimulationCommand', 'update');
        result.compile_status = 'PASS';
        if ~strcmp(mode, 'audit')
            stage = 'simulation';
            step_size = get_param(model, 'CompiledStepSize');
            if ischar(step_size), step_size = str2double(step_size); end
            if isempty(step_size) || ~isfinite(step_size) || step_size <= 0
                % У VariableStepDiscrete нет фиксированного шага; берём минимальный период.
                sample_times = Simulink.BlockDiagram.getSampleTimes(model);
                periods = [];
                for st = 1:numel(sample_times)
                    value = sample_times(st).Value;
                    if ~isempty(value), periods(end + 1) = value(1); end
                end
                step_size = min(periods(isfinite(periods) & periods > 0));
            end
            assert(isnumeric(step_size) && isscalar(step_size) && step_size > 0, ...
                'Expected a positive compiled fixed step size');
            result.step_size = step_size;
            model_steps = steps;
            if strcmp(name, 'qpsk_demod_with_phase_noise'), model_steps = max(steps, 262144); end
            result.stop_time = model_steps * step_size;
            result.requested_steps = model_steps;
            [result.logged_ports, result.mapper_ports] = enable_logging(model);
            set_param(model, 'SignalLogging', 'on', 'SignalLoggingName', 'modem_signals', ...
                'SignalLoggingSaveFormat', 'Dataset', 'LimitDataPoints', 'off');
            rng(5489, 'twister');
            simulation = sim(model, 'StopTime', sprintf('%.17g', result.stop_time), ...
                'ReturnWorkspaceOutputs', 'on', 'TimeOut', 180);
            [traces, summaries] = export_signals(simulation.get('modem_signals'));
            result.signals = summaries;
            result.signal_count = numel(traces);
            assert(~isempty(traces), 'No signals were captured');
            assert(all(cellfun(@(s) s.finite, summaries)), 'Nonfinite signal samples');
            times = simulation.get('tout');
            result.final_time = times(end);
            assert(abs(times(end) - result.stop_time) <= step_size / 2, 'Simulation stopped early');
            result.simulation_status = 'PASS';
            stage = 'repeat';
            % Повторный старт должен восстановить состояния фильтров, петель и генераторов.
            rng(5489, 'twister');
            repeated = sim(model, 'StopTime', sprintf('%.17g', result.stop_time), ...
                'ReturnWorkspaceOutputs', 'on', 'TimeOut', 180);
            [repeat_traces, ~] = export_signals(repeated.get('modem_signals'));
            assert(isequaln(traces, repeat_traces), 'Repeated simulation changed captured samples');
            result.repeat_status = 'PASS';
            save(fullfile(output_dir, 'signals.mat'), 'traces', '-v7');
        end
        result.status = 'PASS';
    catch exception
        result.([stage '_status']) = 'FAIL';
        result.error_identifier = exception.identifier;
        result.error_message = exception.message;
        result.error_report = getReport(exception, 'extended', 'hyperlinks', 'off');
        fprintf('%s\n', result.error_report);
    end
    if bdIsLoaded(model), close_system(model, 0); end
    result.elapsed_seconds = toc(started);
    results{end + 1, 1} = result;
    write_json(fullfile(output_dir, 'result.json'), result);
    write_json(fullfile(destination, 'results.json'), results);
    fprintf('RESULT %s %s load=%s compile=%s simulation=%s\n', name, ...
        result.status, result.load_status, result.compile_status, result.simulation_status);
    diary off;
end
assert(~isempty(results), 'No matching modem');
if strcmp(mode, 'audit')
    expected=jsondecode(fileread(fullfile(root,'docs','matlab_audit_expectations.json')));
    for k=1:numel(results)
        r=results{k}; e=expected.(r.name);
        assert(strcmp(r.load_status,'PASS') && strcmp(r.compile_status,e.compile_status) ...
            && strcmp(r.error_identifier,e.error_identifier), 'Unexpected original audit result: %s',r.name);
    end
else
    assert(all(cellfun(@(s) strcmp(s.status,'PASS'),results)), 'Original model checks failed; inspect results.json');
end
end

function [ports, mappers] = enable_logging(model)
% Пишем выходы верхних блоков: передатчик, канал, фильтры, приёмник и диагностику.
blocks = find_system(model, 'SearchDepth', 1, 'Type', 'Block');
ports = cell(0, 1);
for k = 1:numel(blocks)
    handles = get_param(blocks{k}, 'PortHandles');
    for p = 1:numel(handles.Outport)
        port = handles.Outport(p);
        if get_param(port, 'Line') < 0, continue; end
        [ports, ~] = add_logged_port(ports, port);
    end
end
% Дополнительно сравниваем вход и выход исходных мапперов с таблицами переноса.
mappers = cell(0, 1);
blocks = find_system(model, 'LookUnderMasks', 'all', 'FollowLinks', 'off', ...
    'RegExp', 'on', 'Name', '^(data_mapper|qpsk_data_mapper|Data Mapper RE|Data Mapper IM|M-PSK\s+Modulator\s+Baseband)$');
for k = 1:numel(blocks)
    handles = get_param(blocks{k}, 'PortHandles');
    if numel(handles.Inport) ~= 1 || numel(handles.Outport) ~= 1, continue; end
    line = get_param(handles.Inport(1), 'Line');
    if line < 0, continue; end
    source = get_param(line, 'SrcPortHandle');
    [ports, input_name] = add_logged_port(ports, source);
    [ports, output_name] = add_logged_port(ports, handles.Outport(1));
    mappers{end + 1, 1} = struct('block', blocks{k}, 'input', input_name, 'output', output_name);
end
end

function [ports, label] = add_logged_port(ports, port)
block = get_param(port, 'Parent');
number = get_param(port, 'PortNumber');
for k = 1:numel(ports)
    if strcmp(ports{k}.block, block) && ports{k}.port == number
        label = ports{k}.name;
        return;
    end
end
label = sprintf('trace_%03d', numel(ports) + 1);
set_param(port, 'DataLogging', 'on', 'DataLoggingNameMode', 'Custom', ...
    'DataLoggingName', label, 'DataLoggingDecimateData', 'off', ...
    'DataLoggingLimitDataPoints', 'off');
ports{end + 1, 1} = struct('name', label, 'block', block, 'port', number);
end

function [traces, summaries] = export_signals(dataset)
traces = cell(dataset.numElements, 1);
summaries = cell(dataset.numElements, 1);
for k = 1:dataset.numElements
    element = dataset.getElement(k);
    values = element.Values;
    data = double(values.Data);
    traces{k} = struct('name', element.Name, 'block', element.BlockPath.getBlock(1), ...
        'port', element.PortIndex, 'time', values.Time, 'data', data);
    summaries{k} = struct('name', element.Name, 'block', traces{k}.block, ...
        'port', element.PortIndex, 'samples', numel(values.Time), 'values', numel(data), ...
        'finite', all(isfinite(data(:))), 'rms', sqrt(mean(abs(data(:)).^2)), ...
        'peak', max(abs(data(:))), 'last_real', real(data(end)), 'last_imag', imag(data(end)));
end
end

function inventory = inspect_blocks(model)
% Сохраняем реальные пути и типы для выбора точек регистрации сигналов.
blocks = find_system(model, 'SearchDepth', 1, 'Type', 'Block');
inventory = cell(numel(blocks), 1);
for k = 1:numel(blocks)
    inventory{k} = struct('path', blocks{k}, 'type', get_param(blocks{k}, 'BlockType'), ...
        'mask_type', get_param(blocks{k}, 'MaskType'), 'reference', get_param(blocks{k}, 'ReferenceBlock'));
end
end

function write_json(filename, value)
file = fopen(filename, 'w');
assert(file >= 0, 'Cannot write report');
cleanup = onCleanup(@() fclose(file));
fprintf(file, '%s\n', jsonencode(value));
end
