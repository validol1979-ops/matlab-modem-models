function [b,w,Nused,info] = wsinc(fc,fs,Adb,win,N)
% Usage: [b,w,Nused,info] = wsinc(fc,fs,Adb,win,N)
%
% Windowed sinc filter design
%
%   fc...........cutoff frequency spec in Hz, the frequency at
%                which the normalized magnitude response is -6 dB
%   fs...........sampling frequency in Hz
%   Adb..........stopband attenuation spec in dB
%   win..........char array containing built-in window name
%                built-in windows: 'hann', 'hamming','kaiser',
%                'blackman','parzen','nuttall','albrecht'
%                alternatively, a char array containing a function 
%                handle such as '@tukeywin'
%   N............integral number of filter coefficients
%   b............output: 1-d array of filter coefficients
%   w............output: 1-d array of window coefficients
%   Nused........output: number of filter coefficients used (always odd)
%   info.........output: struct of useful info
%

    b = [];
    w = [];
    Nused = [];
    info = struct;
    info.windows = get_supported_windows();

    if nargin ~= 5
        if nargin ~= 0
            help wsinc
        end
        return
    end

    if rem(N,2) == 0
        N = N + 1; % ensure odd length
    end
    Nused = N;
    Nb2 = (N-1) / 2;

    % sinc
    fnyq = fs/2;
    n = -Nb2:Nb2;
    fp = fc/fnyq; % Fpass normalized 0<fp<1
    b = sin(pi*n*fp)./(pi*n);
    b(n==0) = fp;

    % window
    if win(1) == '@'
        [w,beta] = fetch_user_win(win,N);
    else
        [w,beta] = fetch_win(win,Nb2,Adb);
    end
    info.beta = beta;

    % windowed-sinc
    b = b(:) .* w(:);

end % function

function [w,beta] = fetch_win(win,Nb2,Adb)

    N = 2*Nb2 + 1;
    x = (0:Nb2)'/(N-1);
    beta = [];

    switch lower(win(1:3))
        case 'han' %hann
            % 1.67*fsin/tbw taps
            w = 0.5 - 0.5*cos(2*pi*x);
            w = [w; w(end-1:-1:1)];
            w([1 numel(w)]) = 0;
        case 'ham' %hamming
            w = 0.54 - 0.46*cos(2*pi*x);
            w = [w; w(end-1:-1:1)];
        case 'kai' %kaiser
            if Adb > 50
                beta = 0.1102*(Adb - 8.7);
            elseif Adb >= 21
                beta = 0.5842*(Adb-21)^0.4 + 0.07886*(Adb-21);
            else
                beta = 0;
            end
            % kaiser calculation valid only for odd N
            num = besseli(0,beta*sqrt(1-(2*x(:)).^2));
            den = besseli(0,beta);
            w = num / den;
            w = [w(end:-1:1); w(2:end)];
        case {'bla', 'blk'} %blackman
            w = 0.42 - 0.5*cos(2*pi*x) + 0.08*cos(4*pi*x);
            w = [w; w(end-1:-1:1)];
            w([1 numel(w)]) = 0;
        case 'par' %parzen
            n0 = -Nb2:Nb2;
            n1 = n0(find(abs(n0) <= Nb2/2));
            n2 = n0(find(n0 > Nb2/2));
            n3 = n0(find(n0 < -Nb2/2));
            w1 = 1 -6*(abs(n1)./(N/2)).^2 + 6*(abs(n1)./(N/2)).^3;
            w2 = 2*(1-abs(n2)./(N/2)).^3;
            w3 = 2*(1-abs(n3)./(N/2)).^3;
            w = [w3 w1 w2]';
            w([1 numel(w)]) = 0;
        case 'nut' %nuttall (4-term)
            % Ref: Nuttall, Albert H., "Some windows with very good sidelobe behavior"
            % IEEE Transa on Acoustics, Speech, and Signal Processing Vol. ASSP-29,
            % February 1981, pp. 84-91.
            %a0 = 0.355768;  % -93 dB peak sidelobe
            %a1 = 0.487396;
            %a2 = 0.144232;
            %a3 = 0.012604;
            %a0 = 0.3635819;  % -98 dB peak sidelobe
            %a1 = 0.4891775;
            %a2 = 0.1365995;
            %a3 = 0.0106411;
            a0 = 0.353478834;  % -114 dB peak sidelobe
            a1 = 0.486608654;
            a2 = 0.146521166;
            a3 = 0.013391346;
            w = a0 + a1*cos(2*pi*x) + a2*cos(4*pi*x) + a3*cos(6*pi*x);
            w = [w(end:-1:1); w(2:end)];
        case 'alb' %nuttall-albrecht (6-term)
            % Ref: Hans H. Albrecht, "A family of cosine-sum windows for high-
            % resolution measurements". 2001 IEEE International Conference on 
            % Acoustics, Speech, and Signal Processing.
            a0 = 0.2931693616;  % -166 dB peak sidelobe
            a1 = 0.4516703713;
            a2 = 0.2017352499;
            a3 = 0.0481846021;
            a4 = 0.0050953886;
            a5 = 0.0001450266;
            w = a0 + a1*cos(2*pi*x) + a2*cos(4*pi*x) + a3*cos(6*pi*x) + ...
                a4*cos(8*pi*x) + a5*cos(10*pi*x);
            w = [w(end:-1:1); w(2:end)];
            w([1 numel(w)]) = 0;
        case 'box' %boxcar
            w = ones(2*Nb2+1,1);
        otherwise
            error('Invalid Window')
    end %switch

end % function

function [w,beta] = fetch_user_win(win,N)
    toks = strsplit(win,',');
    fw = eval(toks{1});
    if numel(toks) == 2
        beta = eval(toks{2});
        w = fw(N,beta);
    else
        beta = [];
        w = fw(N);
    end
end % function

function wins_c = get_supported_windows()
    wins_c = {'hann','hamming','kaiser','blackman','parzen','nuttall','albrecht'};
end % function
