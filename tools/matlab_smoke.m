% Проверяем установленную среду отдельно от эквивалентности архивных моделей.
fprintf('MATLAB version: %s\n', version);
products = ver;
for product_index = 1:numel(products)
    fprintf('%s: %s\n', products(product_index).Name, products(product_index).Version);
end
assert(abs(sum([1, 2, 3]) - 6) < eps, 'MATLAB arithmetic check failed');

symbols = qammod((0:15).', 16);
assert(numel(unique(symbols)) == 16, 'Communications Toolbox check failed');
pulse = rcosdesign(1, 4, 8, 'sqrt');
assert(abs(sum(pulse.^2) - 1) < 1e-12, 'Pulse design check failed');

filter_object = dsp.FIRFilter('Numerator', [1, 2, 1]);
response = filter_object([1; 0; 0]);
assert(isequal(response, [1; 2; 1]), 'DSP System Toolbox check failed');
release(filter_object);
fixed_value = fi(0.5, 1, 16, 14);
assert(double(fixed_value) == 0.5, 'Fixed-Point Designer check failed');

% Временная схема не сохраняется и не меняет исходники модемов.
model_name = 'modem_installation_smoke';
new_system(model_name);
model_cleanup = onCleanup(@() close_system(model_name, 0));
add_block('simulink/Sources/Constant', [model_name '/Constant'], 'Value', '3');
add_block('simulink/Math Operations/Gain', [model_name '/Gain'], 'Gain', '2');
add_block('simulink/Sinks/To Workspace', [model_name '/Output'], ...
          'VariableName', 'smoke_output', 'SaveFormat', 'Array');
add_line(model_name, 'Constant/1', 'Gain/1');
add_line(model_name, 'Gain/1', 'Output/1');
set_param(model_name, 'Solver', 'FixedStepDiscrete', 'FixedStep', '1', 'StopTime', '2');
simulation = sim(model_name, 'ReturnWorkspaceOutputs', 'on');
output = simulation.get('smoke_output');
assert(all(output(:) == 6), 'Simulink simulation check failed');
% Закрываем несохранённую схему до завершения MATLAB, пока обработчик ещё активен.
clear model_cleanup;
fprintf('PASS MATLAB installation smoke test\n');
