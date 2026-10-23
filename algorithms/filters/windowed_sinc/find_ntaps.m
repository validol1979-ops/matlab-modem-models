function [N,fstop,Hdb,f,b,w,info] = find_ntaps(fc,fstop,fs,Adb,win)
% Usage: [N,fstop,Hdb,f,b,w,info] = find_ntaps(fc,fstop,fs,Adb,win)
%
% Iteratively search for a windowed sinc FIR filter satisfying
% provided specifications with the fewest number of coefficients.
%
%   fc...........cutoff frequency spec in Hz, the frequency at
%                which the normalized magnitude response is -6 dB
%   fstop........stopband frequency in Hz, fstop is the frequency at
%                which the normalized magnitude response is down
%                Adb db or more
%   fs...........sampling frequency Hz
%   Adb..........stopband attenuation in dB
%   win..........char array containing built-in window name
%                built-in windows: 'hann', 'hamming','kaiser',
%                'blackman','parzen','nuttall','albrecht'
%                alternatively, a char array containing a function 
%                handle such as '@tukeywin'
%   N............output: number of coefficients
%   fstop........output: pass-through of fstop input
%   Hdb..........output: 1-d array magnitude response
%   f............output: 1-d array of frequencies for which the
%                magnitude reponse is evaluated
%   b............output: 1-d array of filter coefficients
%   w............output: 1-d array of window coefficients
%   info.........output: struct of useful info
%

    if nargin ~= 5
        fprintf(2,'Wrong number of input arguments.\n\n');
        help find_ntaps
        return
    end

    if fstop <= fc
        fprintf(2,'fstop must be greater than fc.\n');
        return
    end

    if 2*fstop >= fs
        fprintf(2,'fstop must be in the range (fc,fs/2)\n');
        return
    end

    if exist('freqz') == 2
        fresp = @freqz;
    else
        fresp = @pm_freqz;
    end

    fc0 = fc / fs;
    fstop0 = fstop / fs;
    tbw = fstop0 - fc0;

    N = ceil(1/tbw * (Adb - 8) / 14); % fharris eq. 3.11
    if rem(N,2) == 0
        N = N + 1;
    end
    N = max(N,11); % ensure min and odd

    nfreq = 1000;
    f0 = fstop0 + (-nfreq:nfreq)/nfreq * tbw;
    f0(nfreq + 1) = fstop0;
    f0 = f0(f0>0 & f0<0.5);

    iters = 0;
    tol = 1e-9;
    incr = N;
    if rem(incr,2) == 1
        incr = incr + 1;
    end
    best_err = inf;
    best_N   = N;
    best_ix = nan;
    early_term = 0;
    err = 1;
    sgn = 1;
    MAX_ITERS = 50;
    while 1
        iters = iters + 1;
        [b,w,N] = wsinc(fc0,1,Adb,win,N);

        if ~early_term

            Hdb = 20*log10(abs(fresp(b,1,f0,1)));
            ix = find(Hdb > -Adb, 1, 'last') + 1;
            if isempty(ix)
                N = 2 * N + iters;
                if rem(N,2) == 0
                    N = N + 1;
                end
            elseif ix >= numel(Hdb)
                N = ceil(1.1 * N);
                if rem(N,2) == 0
                    N = N + 1;
                end
            else
                err = f0(ix) - fstop0;
                if abs(err) < abs(best_err)
                    if isnan(best_ix)
                        sgn = sign(err);
                    end
                    best_err = err;
                    best_N = N;
                    best_ix = ix;
                end
                if inrange(err, -tol, 0)
                    MAX_ITERS = 150;
                    early_term = 1;
                elseif err > 0
                    if sgn == -1
                        incr = max(ceil(incr/2),2);
                    end
                    if rem(incr,2) == 1
                        incr = incr + 1;
                    end
                    N = N + incr;
                else % err < 0
                    if sgn == 1
                        incr = max(ceil(incr/2),2);
                    end
                    while incr >= N
                        incr = max(ceil(incr/2),2);
                    end
                    if rem(incr,2) == 1
                        incr = incr - 1;
                    end
                    incr = max(incr,2);
                    N = N - incr;
                    N = max(N,11);
                end
                if err > 0
                    sgn = 1;
                else
                    sgn = -1;
                end
            end
            if N > 100000
                % Too many coefficients. Design did not converge.
                break
            end

        end % if ~early_term

        if iters >= MAX_ITERS
            if best_err > 0
                N = best_N + 2;
            else
                N = best_N;
            end
            err = best_err;
            ix = best_ix;
            [b,w,nused,wsincinfo] = wsinc(fc0,1,Adb,win,N);
            break
        end

        nvec(iters) = N;
        errvec(iters) = err;

        % Terminate early if stuck in a limit cycle
        if iters > 4
            nhist = nvec(iters-3:end) - nvec(iters-3);
            if all(nhist == [0 2 0 2]) ...
            || all(nhist == [0 0 0 0]) ...
            || all(nhist == [0 -1 0 -1])
                MAX_ITERS = 150;
                early_term = 1;
            end
        end

        if sum(b) < 0.98 && early_term == 1
            N = N + 2;
        elseif early_term == 1
            break
        end

    end % while

    [b,w,N,wsincinfo] = wsinc(fc0,1,Adb,win,N);
    Hdb = 20*log10(abs(fresp(b,1,f0(nfreq:nfreq+2),1)));

    if Hdb(2) + Adb > 1
        fprintf(2,'Failed to converge (win=%s, err=%.4f, N=%d Hdb(fstop)=%.1f).\n', ...
            win,err,N,Hdb(2));
    end

    % Final frequency response
    f = (0:2^15)/2^15 * fs/2;
    Hdb = 20*log10(abs(fresp(b,1,f,fs)));

    % collect some useful info
    flong = (0:2^18)/2^18 * fs/2;
    Hdblong = interp1(f,Hdb,flong);
    info = struct();
    info.win = win;
    info.winbeta = wsincinfo.beta;
    info.nvec = nvec;
    info.errvec = errvec;
    info.pt1db = round(flong(find(Hdblong>-0.1,1,'last')));
    info.onedb = round(flong(find(Hdblong>-1,1,'last')));
    info.threedb = round(flong(find(Hdblong>-3,1,'last')));

end % function

function y = inrange(x,lwr,upr,range_type)
% Usage: y = inrange(x,lwr,upr,range_type)
%
% Determine which elements of an array are within the specified range.
%
%   x................numeric array to evaluate
%   lwr..............numeric scalar lower limit of range
%   upr..............numeric scalar upper limit of range
%   range_type.......char array specifying type of range interval
%      'closed'        include upper and lower limits (default)
%      'open'          exclude upper and lower limits
%      'openleft' or    
%      'closedright'   exclude lower and include upper limit
%      'closedleft' or  
%      'openright'     include lower and exclude upper limit
%   y................logical array of results where a "1" in position
%                    n means that the nth element of x falls within
%                    the specified range
%
% Example: Find all elements in x that fall within the closed range [3,5].
%   x = [1,2,3,4,5,6,7,8];
%   y = inrange(x,3,5,'closed')
%   y =
%     0   0   1   1   1   0   0   0
%
    if nargin < 4
        range_type = 'closed';
    end

    switch range_type
        case 'closed'
            y = and(ge(x,lwr), le(x,upr));
        case 'open'
            y = and(gt(x,lwr), lt(x,upr));
        case {'openleft', 'closedright'}
            y = and(gt(x,lwr), le(x,upr));
        case {'openright', 'closedleft'}
            y = and(ge(x,lwr), lt(x,upr));
        otherwise
            y = nan;
            fprintf(2,'Invalid range type.\n');
    end

end % function
