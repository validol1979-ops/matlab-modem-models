function y = wola_chanex(indata, M, D, cofs)
% Usage: y = wola_chanex(indata, M, D, cofs)
%
% Weighted overlap-add channelizer
%
%   indata..............N-by-1 array of complex samples
%   M...................Scalar integer representing number of channels (M>1)
%   D...................Scalar integer representing decimation factor  (D<=M)
%   cofs................L-by-1 array of real lowpass filter coefficients
%

    % Initialize
    indata = shiftdim(indata);         % ensure input is a column vector
    get_shift(M,D,'reset');            % reset phase correction state machine
    Nout = numel(2:D:numel(indata));   % number of output samples to generate
    Nshift = numel(cofs);              % number of shift register stages
    z = zeros(Nshift,1);               % shift register
    v = zeros(Nout,M);                 % work buffer
    rptr = 0;                          % input data read pointer

    % Run first iteration outside of loop to preserve phase
    % 1. Fetch the first sample
    x = indata(1 + (rptr:rptr));
    rptr = rptr + 1;

    % 2. Update the shift register
    z(2:end) = z(1:end-1);
    z(1) = x(1);

    % 3. Apply filter weights
    w = cofs .* z;

    % 4. Stack and add
    u = sum(reshape(w,M,Nshift/M).');
    v(1,:) = [u(1) u(end:-1:2)];

    % 5. Apply phase correction via circular shift
    v(1,:) = phase_correct(v(1,:),M,D);
    % End of first iteration

    % Iterate for each output sample
    for kk = 2:Nout

        % 1. Fetch the next D samples
        x= indata(1 + (rptr:rptr+D-1));
        rptr = rptr + D;

        % 2. Update the shift register
        z(D+1:end) = z(1:end-D);
        z(1:D) = x(end:-1:1);

        % 3. Apply filter weights
        w = cofs .* z;

        % 4. Stack and add
        u = sum(reshape(w,M,Nshift/M).');
        v(kk,:) = [u(1) u(end:-1:2)];

        % 5. Apply phase correction via circular shift
        v(kk,:) = phase_correct(v(kk,:),M,D);

    end

    % 6. Final output via DFT
    y = fft(v(1:Nout,1:M),[],2);

end % main function

function v = phase_correct(v,M,D)

    shift = get_shift(M,D);
    v = circshift(v, shift);

end % function

function shift = get_shift(M,D,reset)
    persistent state
    persistent OL
    persistent K

    if nargin == 3
        state = 0;
        shift = 0;
        OL =  M-D; 
        K = lcm(M,D)/D; % number of states of phase corrector
        return
    end

    if isempty(state) || state == 0
        state = 1;
    end

    shift = M - mod(OL * (state - 1),M);
    state = mod(state + 1,K);
    if state == 0
        state = K;
    end

end % function
