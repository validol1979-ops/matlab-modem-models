function y=run_model(operation,parameters,signal,auxiliary)
% Одна M-реализация выполняется в MATLAB и в Octave без toolbox.
if nargin<4, auxiliary=[]; end
here=fileparts(mfilename('fullpath'));root=here;
while ~isfolder(fullfile(root,'common','octave'))
  parent=fileparts(root);
  if strcmp(parent,root), error('Project root not found'); end
  root=parent;
end
addpath(fullfile(root,'common','octave'));
y=research_core(operation,parameters,signal,auxiliary);
end
