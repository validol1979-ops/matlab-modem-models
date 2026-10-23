function results_c = compare_filters(fc,fstop,fs,Adb,varargin)
% Usage: results_c = compare_filters(fc,fstop,fs,Adb,varargin)
%
% A tool to design and compare windowed sinc FIR filters.
%
% COMPARE_FILTERS takes a user-supplied filter spec and designs
% a set of windowed sinc FIR filters using several common window
% types. It then compares the resulting filters in terms of
% complexity (number of coefficients), passband flatness, and
% and stopband rejection. This helps you make an informed choice
% in selecting an implementation best suited to your application.
%
% The tool designs lowpass, highpass, and bandpass filters with
% the following built-in windows: Hann, Hamming, Kaiser, Blackman,
% Parzen, Nuttall (4-term), and Albrecht (6-term).
%
% Optionally it can accept one or more user-supplied windows as a
% list (cell array) of function handles referencing functions that
% use the MATLAB or GNU Octave window function API. That is, the 
% tool accepts handles to functions that take a first argument
% containing the window length and an optional second argument to
% specify a window shaping parameter. Examples of such functions
% include bartlett(L) and chebwin(L,r). This feature makes it
% possible to create your own window function for evaluation.
%
% The tool runs an iterative search algorithm to determine the
% minimum number of filter coefficients needed to satisfy the
% design specifications. A table of results is then displayed,
% one row per window type, allowing you to compare different
% filter implementations.
%
% COMPARE_FILTERS is compatible with MATLAB and GNU Octave. It is
% implemented so as not to require any MATLAB toolboxes or GNU
% Octave packages. However it will likely run faster if the Signal
% Processing toolbox/package is installed.
%
% Inputs:
%
%   fc...........cutoff frequency spec in Hz, the frequency at
%                which the normalized magnitude response is -6 dB;
%                for lowpass and highpass filters specify a single 
%                frequency
%                for bandpass filters specify a vector of two 
%                frequencies corresponding to the lower and upper
%                passband edges
%   fstop........stopband frequency spec in Hz, the frequency at
%                which the normalized magnitude response is down
%                Adb db or more;
%                for lowpass and highpass filters specify a single
%                frequency
%                for bandpass filters specify a vector of two
%                frequencies corresponding to the lower and upper
%                stopband edges
%   fs...........sampling frequency Hz
%   Adb..........stopband attenuation spec in dB
%
% Optional inputs:
%
%   filter_type..optional char array, one of 'lowpass','highpass',or
%                'bandpass' (default 'lowpass')
%   user_win_c...optional cell array of function handles to window
%                function; for example {'@tukeywin','gausswin,3.5'}
%                adds comparisons for a Tukey window and a Gaussian
%                window with shaping factor of 3.5; as shown in the
%                example, if the window function uses a shaping
%                factor it is included in the cell after the window
%                name, separated by a comma
%
% Outputs:
%
%   results_c....output: cell array containing windowed sinc design
%                and performance measurements; Each cell contains
%                a struct with the following members
%                type...........filter type, one of 'lowpass', 'highpass',
%                               or 'bandpass'
%                window.........name of window
%                window_param...window shaping parameter
%                ntaps..........number of filter coefficients
%                fc.............6dB cutoff frequency design spec (Hz)
%                fstop..........stopband frequency design spec (Hz)
%                fs.............sampling frequency design spec (Hz)
%                Adb............stopband attenuation design spec (dB)
%                pt1db..........measured passband 0.1 dB frequency (Hz)
%                onedb..........measured passband 1 dB frequency (Hz)
%                threedb........measured passband 3 dB frequency (Hz)
%                Psbdb..........measured average stopband attenuation (dB)
%                cofs...........1-d array of filter coefficients
%                wcofs..........1-d array of window coefficients
%                Hdb............1-d array of magnitude reponses (dB)
%                f..............1-d array of frequencies (Hz)
%   Upon completion, a table containng a textual summary of results is 
%   displayed with the following columns
%               Window.........Name of window including shaping factor,
%                              if applicable
%               Ntaps..........Number of filter coefficients
%               Fc.............Cutoff frequency spec (Hz);
%                              In bandpass designs, two columns are
%                              displayed, Fc1 and Fc2, respectively
%                              the lower and upper cutoff frequencies
%               Fstop..........Stopband frequency spec (Hz);
%                              In bandpass designs, two columns are
%                              displayed, Fstop1 and Fstop2, the lower
%                              and upper stopband frequencies
%               Fs.............Sampling frequency spec (Hz)
%               Adb............Stopband attenuation spec (dB)
%               F.1db..........Frequency (Hz) at which the response is
%                              -0.1 dB (measure of passband flatness);
%                              In bandpass designs this column displays
%                              as BW.1db, the 0.1 dB bandwidth
%               F1db...........Frequency (Hz) at which the response is
%                              -1 dB (measure of passband flatness);
%                              In bandpass designs this column displays
%                              as BW1db, the 1 dB bandwidth
%               F3db...........Frequency (Hz) at which the response is
%                              -3 dB (measure of passband flatness);
%                              In bandpass designs this column displays
%                              as BW3db, the 3 dB bandwidth
%               Psbdb..........Average stopband attenuation (measure
%                              of spectral purity)
%
% Example 1: Compare performance of low pass filters given these specs
%              Cutoff frequency:   10 kHz
%            Stopband frequency:   12 kHz
%            Sampling frequency:   64 kHz
%          Stopband attenuation:   40 dB
%
%  >> res = compare_filters(10e3,12e3,64e3,40);
%  Window             Ntaps       Fc    Fstop        Fs    Adb    F.1db     F1db     F3db   Psbdb
%  hann                  51    10000    12000     64000     40     8085     8800     9446     -59
%  hamming               51    10000    12000     64000     40     8111     8878     9487     -64
%  kaiser(3.4)           39    10000    12000     64000     40     8148     8803     9440     -53
%  blackman              67    10000    12000     64000     40     8077     8891     9498     -64
%  parzen                77    10000    12000     64000     40     8088     8928     9518     -61
%  nuttall               81    10000    12000     64000     40     8061     8904     9507     -63
%  albrecht              99    10000    12000     64000     40     8049     8915     9514     -62
%  
%  The results show that a Kaiser window with beta=3.4 satisfies the spec
%  with the fewest coefficients. The Hamming and Blackman windows provide
%  the most stopband attenuation (at the expense of more coefficients) 
%  while the Parzen window has the flatest passband.
%
%  Plot results using the included plotres() utility.
%  >> plotres(res);
%  
% Example 2: Add user-supplied windows.
%  >> res = compare_filters(10e3,12e3,64e3,40,{'@chebwin','@gausswin,3.5'});
%  Window             Ntaps       Fc    Fstop        Fs    Adb    F.1db     F1db     F3db   Psbdb
%  @chebwin              77    10000    12000     64000     40     8058     8904     9507     -63
%  @gausswin(3.5)        85    10000    12000     64000     40     8068     8953     9535     -62
%  hann                  51    10000    12000     64000     40     8085     8800     9446     -59
%  hamming               51    10000    12000     64000     40     8111     8878     9487     -64
%  kaiser(3.4)           39    10000    12000     64000     40     8148     8803     9440     -53
%  blackman              67    10000    12000     64000     40     8077     8891     9498     -64
%  parzen                77    10000    12000     64000     40     8088     8928     9518     -61
%  nuttall               81    10000    12000     64000     40     8061     8904     9507     -63
%  albrecht              99    10000    12000     64000     40     8049     8915     9514     -62
%  
%  This example adds Chebychev and Gaussian (shape factor=3.5) windows.
%  The Gaussian design provides the flatest 3dB bandwidth while the
%  Chebychev window does not improve passband or stopband responses,
%  nor complexity compared to the built-in windows.
%  
% Example 3: You can bypass analysis of built-in windows by setting
% the last user window in the list to 'break'.
%  >> res = compare_filters(10e3,12e3,64e3,40,{'@flattopwin','break'});
%  Window             Ntaps       Fc    Fstop        Fs    Adb    F.1db     F1db     F3db   Psbdb
%  @flattopwin          105    10000    12000     64000     40     8033     8782     9403     -63
%
% Example 4: Design a highpass filter.
%  >> res = compare_filters_2(22e3,20e3,64e3,40,'highpass',{'@hann','break'});
%  Window             Ntaps       Fc    Fstop        Fs    Adb    F.1db     F1db     F3db   Psbdb
%  @hann                 51    22000    20000     64000     40    23915    23200    22554     -59
%
%  plotres(res);
%
% Example 5: Design a bandpass filter.
%  >> res = compare_filters_2([6e3 26e3],[4e3 28e3],64e3,40,'bandpass',{'@hamming','break'});
%  Window             Ntaps      Fc1      Fc2   Fstop1   Fstop2        Fs    Adb   BW.1db    BW1db    BW3db   Psbdb
%  @hamming              51     6000    26000     4000    28000     64000     40    16222    17756    18974     -64
%
%  plotres(res);
%
% References
% [1] F.J. Harris, "Multirate Signal Processing for Communications Systems,"
%     Prentice Hall, 2004.
% [2] Nuttall, Albert H., "Some windows with very good sidelobe behavior"
%     IEEE Transa on Acoustics, Speech, and Signal Processing Vol. ASSP-29,
%     February 1981, pp. 84-91.
% [3] Albrecht, Hans H., "A family of cosine-sum windows for high-
%     resolution measurements". 2001 IEEE International Conference on 
%     Acoustics, Speech, and Signal Processing, July 2001.
%

    windows = {};
    skip_builtins = false;
    filter_type = 'lowpass';

    for kk = 1:numel(varargin)
        thisarg = varargin{kk};
        if iscell(thisarg)
            % Check for user supplied window(s)
            for jj = 1:numel(thisarg)
                if strcmpi(thisarg{jj},'break')
                    skip_builtins = true;
                    break
                end
                windows{end+1} = thisarg{jj};
            end
        elseif ischar(thisarg)
            filter_type = lower(thisarg);
        end
    end

    % Add the list of wsinc builtin windows
    if ~skip_builtins
        [~,~,~,info] = wsinc();
        for kk = 1:numel(info.windows)
            windows{end+1} = info.windows{kk};
        end
    end

    % Input spec
    in_spec = struct();
    in_spec.type = filter_type;
    in_spec.fc = sort(fc);
    in_spec.fstop = sort(fstop);
    in_spec.fs = fs;
    in_spec.Adb = Adb;

    % LPF spec
    if strcmpi(filter_type,'lowpass')
        lpf_spec = in_spec;
    elseif strcmpi(filter_type,'highpass') || strcmpi(filter_type,'bandpass')
        lpf_spec = transform_to_lpf_spec(in_spec);
    else
        fprintf(2,"Filter type must be 'lowpass', 'highpass', or 'bandpass\n'");
        return
    end

    results_c = {};    
    for kk = 1:numel(windows)
        if Adb > 60 && strcmpi(windows{kk},'hamming')
            continue
        end
        win = windows{kk};
        [No,fstop,Hdb,f,b,w,search_info] = find_ntaps(lpf_spec.fc, ...
                                                      lpf_spec.fstop, ...
                                                      lpf_spec.fs, ...
                                                      lpf_spec.Adb, ...
                                                      win);
        rec = struct;
        rec.type = filter_type;
        rec.window = win;
        rec.window_param = search_info.winbeta;
        rec.ntaps = numel(b);
        rec.fc = lpf_spec.fc;
        rec.fstop = lpf_spec.fstop;
        rec.pt1db = search_info.pt1db;
        rec.onedb = search_info.onedb;
        rec.threedb = search_info.threedb;
        Hmagsq = 10.^(Hdb/10);
        % Average stopband atten dB:
        rec.Psbdb = round(10*log10(sum(Hmagsq(f>=fstop))/numel(Hmagsq(f>=fstop))));
        rec.fs = lpf_spec.fs;
        rec.Adb = lpf_spec.Adb;
        rec.cofs = b;
        rec.wcofs = w;
        rec.f = f(:);
        rec.Hdb = Hdb;
        rec2 = transform_from_lpf(rec,in_spec);
        results_c{end+1} = rec2;
    end

    % dump results to console
    if strcmpi(filter_type,'lowpass') || strcmpi(filter_type,'highpass')
        display_lpfhpf_results(results_c);
    elseif strcmpi(filter_type,'bandpass')
        display_bandpass_results(results_c);
    end

end % main function

function lpf_spec = transform_to_lpf_spec(spec)

    filter_type = spec.type;
    lpf_spec = spec;
    if strcmpi(filter_type,'highpass')
        lpf_spec.fc = spec.fs/2 - spec.fc;
        lpf_spec.fstop = spec.fs/2 - spec.fstop;
    elseif strcmpi(filter_type,'bandpass')
        lpf_spec.fc = (spec.fc(2) - spec.fc(1)) / 2;
        lpf_spec.fstop = lpf_spec.fc + (spec.fstop(2) - spec.fc(2));
    end

end % function

function reco = transform_from_lpf(reci,spec)

    filter_type = spec.type;
    reco = reci;
    if strcmpi(filter_type,'lowpass')
        return
    end

    if exist('freqz') == 2
        fresp = @freqz;
    else
        fresp = @pm_freqz;
    end

    switch filter_type
        case 'highpass'
            reco.fc = spec.fc;
            reco.fstop = spec.fstop;
            reco.pt1db = spec.fs/2 - reci.pt1db;
            reco.onedb = spec.fs/2 - reci.onedb;
            reco.threedb = spec.fs/2 - reci.threedb;
            reco.cofs = reci.cofs .* shiftdim((-1).^(0:reci.ntaps-1));
        case 'bandpass'
            fcenter = mean(spec.fc);
            fs = mean(spec.fs);
            reco.fc      = spec.fc;
            reco.fstop   = spec.fstop;
            reco.pt1db   = fcenter + [-reci.pt1db, reci.pt1db];
            reco.onedb   = fcenter + [-reci.onedb, reci.onedb];
            reco.threedb = fcenter + [-reci.threedb, reci.threedb];
            mix = 2 * cos(2*pi*(fcenter/fs)*(0:reci.ntaps-1));
            reco.cofs = reci.cofs(:) .* mix(:);
    end % switch

    H = fresp(reco.cofs,1,reco.f,reco.fs);
    reco.Hdb = 20*log10(abs(H));

end % function

function display_lpfhpf_results(results_c)

    if results_c{1}.fs > 10
        fprintf(1,'Window             Ntaps       Fc    Fstop        Fs    Adb    F.1db     F1db     F3db   Psbdb\n');
        for kk = 1:numel(results_c)
            res = results_c{kk};
            win_s = format_win_name(res.window,res.window_param);
            fprintf(1,'%s  % 6d   % 6d   % 6d  % 8d   % 4d   % 6d   % 6d   % 6d    % 4d\n' ...
              , win_s ...
              , res.ntaps ...
              , round(res.fc) ...
              , round(res.fstop) ...
              , round(res.fs) ...
              , res.Adb ...
              , round(res.pt1db) ...
              , round(res.onedb) ...
              , round(res.threedb) ...
              , res.Psbdb);
        end
    else
        fprintf(1,'Window             Ntaps          Fc       Fstop         Fs    Adb       F.1db        F1db        F3db   Psbdb\n');
        for kk = 1:numel(results_c)
            res = results_c{kk};
            win_s = format_win_name(res.window,res.window_param);
            fprintf(1,'%s  % 6d   % .2e   % .2e  % .2e   % 4d   % .2e   % .2e   % .2e    % 4d\n' ...
              , win_s ...
              , res.ntaps ...
              , res.fc ...
              , res.fstop ...
              , res.fs ...
              , res.Adb ...
              , res.pt1db ...
              , res.onedb ...
              , res.threedb ...
              , res.Psbdb);
        end
    end

end % function

function display_bandpass_results(results_c)

    fprintf(1,'Window             Ntaps      Fc1      Fc2   Fstop1   Fstop2        Fs    Adb   BW.1db    BW1db    BW3db   Psbdb\n');
    for kk = 1:numel(results_c)
        res = results_c{kk};
        bwpt1db = diff(res.pt1db);
        bwonedb = diff(res.onedb);
        bwthreedb = diff(res.threedb);
        win_s = format_win_name(res.window,res.window_param);
        fprintf(1,'%s  % 6d   % 6d   % 6d   % 6d   % 6d  % 8d   % 4d   % 6d   % 6d   % 6d    % 4d\n', ...
            win_s, res.ntaps, res.fc(1), res.fc(2), res.fstop(1), res.fstop(2), res.fs, res.Adb, bwpt1db, bwonedb, bwthreedb, res.Psbdb);
    end

end % function

function wstr = format_win_name(in_wstr,in_wparam)

    W = 16; % max window name chars
    toks = strsplit(in_wstr,',');
    win_name = toks{1};
    if numel(toks) == 2
        win_name = [win_name '(' toks{2} ')'];
    elseif ~isempty(in_wparam)
        win_name = sprintf('%s(%.1f)',win_name,in_wparam);
    end
    win_name = win_name(1:min(length(win_name),W));
    wstr = repmat(' ',1,W);
    wstr(1:numel(win_name)) = win_name;

end % function
