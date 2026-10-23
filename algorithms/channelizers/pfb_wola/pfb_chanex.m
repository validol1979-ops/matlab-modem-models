function y = pfb_chanex(indata, M, D, cofs)
% Usage: y = pfb_chanex(indata, M, D, cofs)
%
% Polyphase filter bank channelizer
%
%   indata..............N-by-1 array of complex samples
%   M...................Scalar integer representing number of channels (M>1)
%   D...................Scalar integer representing decimation factor  (D<=M)
%   cofs................M-by-L array of real filter coefficients representing
%                       a polyphase decomposition of the lowpass prototype
%                       filter, where M is the number of channels and L is
%                       the number of taps per channel
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

    % 3. Generate the first polyphase filter bank output
    v(1,:) = pfb(cofs,z);

    % 4. Apply phase correction via circular shift
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

        % 3. Generate next polyphase filter bank output
        v(kk,:) = pfb(cofs,z);

        % 4. Apply phase correction via circular shift
        v(kk,:) = phase_correct(v(kk,:),M,D);

    end

    % Final output via DFT
    y = fft(v(1:Nout,1:M),[],2);

end % main function

function v = phase_correct(v,M,D)

    shift = get_shift(M,D);
    v = circshift(v, shift);

end % function

function v = pfb(P,z)

    M = size(P,1);
    v = zeros(1,M);
    for kk = 1:M
        fftbin = get_fft_bin(kk,M);
        thisChanOut = P(kk,:) * z(kk:M:end);
        v(fftbin) = thisChanOut;
    end

end % function

function idx = get_fft_bin(m,M)
    
    if(m == 1)
        idx = m;
    else
        idx = M - m + 2;
    end

end % function

function shift = get_shift(M,D,reset)
    persistent state

    if nargin == 3
        state = 0;
        shift = 0;
        return
    end

    if isempty(state) || state == 0
        state = 1;
    end

    K = lcm(M,D)/D; % number of states of phase corrector
    OL =  M-D; 

    shift = M - mod(OL * (state - 1),M);
    state = mod(state + 1,K);
    if state == 0
        state = K;
    end

end % function
