"""Finite, initially idle FIFO budgets; these do not remove a service-rate deficit."""


def finite_burst(length,interval,first_service=2):
    """One arrival at clocks0..length-1; departures at first_service+k*interval.

    A departure can free capacity on the same edge as an arrival. Count the
    maximum outstanding words after each edge, without rounding to RAM geometry.
    """
    if any(type(v) is not int for v in (length,interval,first_service)) or length<1 or interval<1 or first_service<1:
        raise ValueError('Positive integer burst, service interval and startup required')
    # With arrivals each clock and interval>=1, outstanding count cannot fall
    # during the arrival burst. No departure exists before the first service.
    departures=0 if length<=first_service else 1+(length-1-first_service)//interval
    capacity=length-departures
    return dict(length=length,service_interval=interval,first_service=first_service,
                required_capacity=capacity,ram_power_of_two=1<<(max(2,capacity)-1).bit_length(),
                infinite_one_per_cycle_supported=interval==1,
                scope='Finite burst, idle initially, no sink stalls, one arrival/clock; includes registered output')


def report():
    return dict(scope='Analytic finite-burst FIFO budgets, no measured or physical timing claim',
                rows=[finite_burst(b,8) for b in (16,64,128,512)],
                sustained_service=dict(arrivals_per_cycle=1,departures_per_8_cycles=1,backlog_growth_per_8_cycles=7,
                    finite_fifo_suffices=False,required_average_arrival_interval=8))


def _load_inputs(arrivals, ready_pattern, stall_windows, depth, trace):
    try:
        arrivals = tuple(arrivals)
        ready_pattern = tuple(ready_pattern)
        windows = tuple(tuple(window) for window in stall_windows)
    except TypeError as exc:
        raise ValueError('Arrival cycles, ready pattern and stall windows must be iterable') from exc
    if (not arrivals or any(type(c) is not int or c < 0 for c in arrivals)
            or any(a >= b for a, b in zip(arrivals, arrivals[1:]))):
        raise ValueError('Arrival release cycles must be nonempty, strictly increasing nonnegative integers')
    if (not ready_pattern or any(type(v) is not int or v not in (0, 1) for v in ready_pattern)
            or not any(ready_pattern)):
        raise ValueError('Periodic sink-ready pattern must contain binary integers and at least one ready cycle')
    if any(len(w) != 2 or any(type(c) is not int for c in w)
           or not 0 <= w[0] < w[1] for w in windows):
        raise ValueError('Sink stall windows must be nonnegative, nonempty half-open integer intervals')
    if depth is not None and (type(depth) is not int or not 2 <= depth <= 65536):
        raise ValueError('Physical axis_fifo depth must be an integer in 2..65536')
    if type(trace) is not bool:
        raise ValueError('trace must be boolean')
    return arrivals, ready_pattern, windows


def _costas_fifo_replay(arrivals, ready_pattern, windows, depth, trace):
    """Control simulation only; all values below are sampled before the edge."""
    count = len(arrivals)
    sent = consumed = completed = level = peak = blocked = 0
    fifo_valid = False
    # A take at t reaches ROTATE's result register after edge t+7, so the
    # registered output and UPDATE input-ready are visible before edge t+8.
    next_take = 0
    output_due = None
    accepted, service, outputs, samples = [], [], [], []
    last_stall = max((b for _, b in windows), default=0)
    # Each word can wait for at most one ready-pattern period after its eight
    # processing clocks; two FIFO refill clocks per word are conservative.
    limit = max(arrivals[-1], last_stall) + count * (10 + len(ready_pattern)) + 4
    for cycle in range(limit):
        sink_ready = ready_pattern[cycle % len(ready_pattern)]
        if any(a <= cycle < b for a, b in windows):
            sink_ready = 0
        output_valid = output_due is not None and cycle >= output_due
        fifo_ready = cycle >= next_take and (not output_valid or bool(sink_ready))
        pop = bool(fifo_valid and fifo_ready)
        source_valid = sent < count and arrivals[sent] <= cycle
        source_ready = depth is None or level < depth or pop
        push = bool(source_valid and source_ready)
        read_word = level > int(fifo_valid) and (not fifo_valid or fifo_ready)
        if trace:
            samples.append(dict(cycle=cycle, s_valid=int(source_valid), s_ready=int(source_ready),
                f_valid=int(fifo_valid), f_ready=int(fifo_ready), m_valid=int(output_valid),
                m_ready=int(sink_ready), level=level))
        if source_valid and not source_ready:
            blocked += 1
        if output_valid and sink_ready:
            outputs.append(cycle)
            completed += 1
            output_due = None
        if pop:
            service.append(cycle)
            consumed += 1
            next_take = cycle + 8
            output_due = cycle + 8
        if push:
            accepted.append(cycle)
            sent += 1
        level += int(push) - int(pop)
        peak = max(peak, level)
        if read_word:
            fifo_valid = True
        elif pop:
            fifo_valid = False
        if completed == count:
            if sent != count or consumed != count or level or fifo_valid or output_due is not None:
                raise RuntimeError('Inconsistent FIFO/Costas drain')
            result = dict(depth=depth, words=count, peak=peak, blocked_cycles=blocked,
                accepted_cycles=accepted, service_cycles=service, output_cycles=outputs,
                drained_cycle=cycle)
            if trace:
                result['trace'] = samples
            return result
    raise RuntimeError('FIFO/Costas schedule exceeded its conservative drain bound')


def costas_fifo_load(arrivals, *, ready_pattern=(1,), stall_windows=(), depth=None, trace=False):
    """Exact finite offered-load budget for configured axis_fifo + costas_loop.

    ``arrivals`` are absolute nominal release cycles, with at most one new word
    per clock. A finite-depth source retains each released word until accepted;
    any backlog is subsequently offered in order without extra idle clocks.
    ``ready_pattern`` repeats from cycle zero; half-open ``stall_windows`` force
    the sink not ready regardless of the pattern. Both blocks start empty and
    the consumer is already configured, with no reset or configuration requests
    during the load. TLAST does not change this consumer's service timing.

    The unbounded control replay computes required_capacity: total outstanding
    FIFO words, including its registered output. read_word and output_valid are
    tracked explicitly, including the singleton pop+push output bubble. A pop
    frees capacity on the same edge as a push. Costas accepts another word no
    earlier than eight clocks after its previous take, when its output register
    is available. Rotation proceeds during sink stalls: only a pending output
    can delay the next take. This is not a globally frozen cooldown model.

    Optional ``depth`` replays source backpressure for that physical FIFO depth;
    required_capacity always comes from the unconstrained nominal load, while
    peak/blocked_cycles/transfer cycles describe this requested replay. The
    physical module requires at least two entries even when the exact budget
    is one. minimum_depth is the mathematical requirement; an oversized budget
    has supported_by_single_fifo=False because the module allows at most 65536
    entries. Finite schedules and deterministic readiness prove no sustained
    rate or finite FIFO bound for other arrival/stall processes.
    """
    arrivals, ready_pattern, windows = _load_inputs(arrivals, ready_pattern, stall_windows, depth, trace)
    unlimited = _costas_fifo_replay(arrivals, ready_pattern, windows, None, trace and depth is None)
    need = unlimited['peak']
    result = unlimited if depth is None else _costas_fifo_replay(arrivals, ready_pattern, windows, depth, trace)
    result.update(required_capacity=need, minimum_depth=max(2, need),
        ram_power_of_two=1 << (max(2, need) - 1).bit_length(),
        supported_by_single_fifo=need <= 65536,
        scope='Exact finite nominal load; initially empty configured FIFO/Costas; total capacity includes registered output; no reset/configuration or physical timing claim')
    return result


def costas_rate_bound(words_per_period, period, *, ready_pattern=(1,)):
    """Necessary rate test only, never a sufficient finite-FIFO guarantee.

    Even an always-ready Costas consumer can service at most 1/8 word/clock.
    Sink readiness can lower that rate depending on its phase and pending
    output; its duty cycle must not be multiplied by 1/8. Passing this bound
    says nothing about maximum arrival burst or maximum sink-stall duration.
    """
    if (type(words_per_period) is not int or type(period) is not int
            or words_per_period < 1 or period < 1):
        raise ValueError('Positive integer word count and period required')
    try:
        ready_pattern = tuple(ready_pattern)
    except TypeError as exc:
        raise ValueError('Sink-ready pattern must be iterable') from exc
    if not ready_pattern or any(type(v) is not int or v not in (0, 1) for v in ready_pattern):
        raise ValueError('Sink-ready pattern must contain binary integers')
    impossible = not any(ready_pattern) or 8 * words_per_period > period
    return dict(words_per_period=words_per_period, period=period,
        maximum_service_rate_numerator=1, maximum_service_rate_denominator=8,
        unavoidable_rate_deficit=impossible,
        finite_fifo_suffices=False if impossible else None,
        scope='Necessary ideal-service upper bound only; no sufficiency claim or duty-cycle service approximation')


def _lms_framing(count, frame_lengths, input_last, taps, mode):
    if type(taps) is not int or taps < 1:
        raise ValueError('A positive integer tap count is required')
    if mode not in ('lms', 'nlms'):
        raise ValueError('Mode must be lms or nlms')
    if (frame_lengths is None) == (input_last is None):
        raise ValueError('Provide exactly one of frame_lengths or input_last')
    try:
        if frame_lengths is not None:
            lengths = tuple(frame_lengths)
            if (not lengths or any(type(n) is not int or n < 1 for n in lengths)
                    or sum(lengths) != count):
                raise ValueError('Positive frame lengths must sum to the arrival count')
            lasts = [0] * count
            index = 0
            for length in lengths:
                index += length
                lasts[index - 1] = 1
            return tuple(lasts), lengths
        lasts = tuple(input_last)
    except TypeError as exc:
        raise ValueError('Framing must be iterable') from exc
    if (len(lasts) != count or not lasts or lasts[-1] != 1
            or any(type(v) is not int or v not in (0, 1) for v in lasts)):
        raise ValueError('input_last must be binary, match arrivals and end with TLAST')
    ends = [j + 1 for j, last in enumerate(lasts) if last]
    lengths = tuple(end - start for start, end in zip([0] + ends[:-1], ends))
    return lasts, lengths


def _lms_fifo_replay(arrivals, lasts, taps, m_pattern, w_pattern, m_windows, w_windows, depth, trace):
    """Event/deadline model; no arithmetic or RTL-state enumeration is copied."""
    count = len(arrivals)
    expected_weights = sum(lasts) * taps
    sent = consumed = completed = weights = level = peak = blocked = 0
    fifo_valid = weight_valid = False
    output_due = dump_start = None
    output_last = False
    arithmetic_ready = dump_generated = 0
    accepted, service, outputs, weight_cycles, samples = [], [], [], [], []
    output_lasts, weight_lasts = [], []
    last_stall = max((b for _, b in (*m_windows, *w_windows)), default=0)
    # After all finite pauses, each sample takes at most 8 arithmetic clocks,
    # one data-ready period, two FIFO refill clocks, and (for singleton frames)
    # T weights each waiting at most one independent weight-ready period.
    per_word = 12 + len(m_pattern) + (taps + 1) * (len(w_pattern) + 1)
    limit = max(arrivals[-1], last_stall) + count * per_word + 8
    for cycle in range(limit):
        m_ready = m_pattern[cycle % len(m_pattern)]
        w_ready = w_pattern[cycle % len(w_pattern)]
        if any(a <= cycle < b for a, b in m_windows):
            m_ready = 0
        if any(a <= cycle < b for a, b in w_windows):
            w_ready = 0
        m_valid = output_due is not None and cycle >= output_due
        # Production LMS requires !m_valid, even if it drains on this edge.
        fifo_ready = cycle >= arithmetic_ready and dump_start is None and not m_valid
        pop = bool(fifo_valid and fifo_ready)
        source_valid = sent < count and arrivals[sent] <= cycle
        source_ready = depth is None or level < depth or pop
        push = bool(source_valid and source_ready)
        read_word = level > int(fifo_valid) and (not fifo_valid or fifo_ready)
        f_last = int(lasts[consumed]) if fifo_valid else 0
        w_last = int(dump_generated == taps) if weight_valid else 0
        if trace:
            samples.append(dict(cycle=cycle, s_valid=int(source_valid), s_ready=int(source_ready),
                s_last=int(lasts[sent]) if source_valid else 0,
                f_valid=int(fifo_valid), f_ready=int(fifo_ready), f_last=f_last,
                m_valid=int(m_valid), m_ready=int(m_ready), m_last=int(output_last) if m_valid else 0,
                w_valid=int(weight_valid), w_ready=int(w_ready), w_last=w_last, level=level))
        if source_valid and not source_ready:
            blocked += 1
        if m_valid and m_ready:
            outputs.append(cycle)
            completed += 1
            if output_last:
                output_lasts.append(cycle)
            output_due = None
        if weight_valid and w_ready:
            weight_cycles.append(cycle)
            weights += 1
            if w_last:
                weight_lasts.append(cycle)
        # DUMP can load the first register even when w_ready is low. On the
        # final weight handshake it clears history and returns to IDLE only
        # after the edge, so the following frame cannot be taken on this edge.
        if dump_start is not None and cycle >= dump_start and (not weight_valid or w_ready):
            if dump_generated == taps:
                weight_valid = False
                dump_start = None
                arithmetic_ready = max(arithmetic_ready, cycle + 1)
            else:
                dump_generated += 1
                weight_valid = True
        if pop:
            service.append(cycle)
            consumed += 1
            arithmetic_ready = cycle + 8
            output_due = cycle + 4
            output_last = bool(f_last)
            if f_last:
                dump_start = cycle + 8
                dump_generated = 0
        if push:
            accepted.append(cycle)
            sent += 1
        level += int(push) - int(pop)
        peak = max(peak, level)
        if read_word:
            fifo_valid = True
        elif pop:
            fifo_valid = False
        if completed == count and weights == expected_weights and dump_start is None:
            if (sent != count or consumed != count or level or fifo_valid or weight_valid
                    or output_due is not None):
                raise RuntimeError('Inconsistent FIFO/LMS drain')
            result = dict(depth=depth, words=count, peak=peak, blocked_cycles=blocked,
                accepted_cycles=accepted, service_cycles=service, output_cycles=outputs,
                weight_cycles=weight_cycles, output_last_cycles=output_lasts,
                weight_last_cycles=weight_lasts, drained_cycle=cycle)
            if trace:
                result['trace'] = samples
            return result
    raise RuntimeError('FIFO/LMS schedule exceeded its conservative drain bound')


def lms_fifo_load(arrivals, *, frame_lengths=None, input_last=None, taps=4, mode='lms',
                  m_ready_pattern=(1,), w_ready_pattern=(1,),
                  m_stall_windows=(), w_stall_windows=(), depth=None, trace=False):
    """Exact finite offered-load budget for axis_fifo(WIDTH=72) + lms_filter.

    Both blocks start empty, with legal LMS/NLMS configuration already accepted
    (LOG2N large enough for ``taps``), no reset or reconfiguration during the
    load, and the filter history/weights initially zero. Each absolute release
    cycle offers one (x_re,x_im,d_re,d_im) word. A finite-depth source holds each
    released word and its TLAST until accepted, then catches up in order.
    Specify exactly one framing form: positive ``frame_lengths`` summing to the
    word count, or one binary ``input_last`` per word with a final TLAST.

    Independent data and weight sinks use periodic binary patterns starting at
    cycle zero and optional half-open pause windows. Arithmetic runs regardless
    of data-output stalls: a take at t exposes m_valid at t+4 and finishes its
    arithmetic at t+8. The next take requires IDLE and an empty output register;
    consuming a pending output does not allow a simultaneous next input. After
    TLAST, DUMP loads the first weight at t+8 (visible at t+9), emits all T
    weights, and clears history only after the final weight handshake. Both
    that drain and any pending data output constrain the next frame. LMS and
    NLMS have identical control timing for legal configurations.

    As in costas_fifo_load, required_capacity comes from the unbounded nominal
    replay, includes the registered FIFO output, and permits full pop+push.
    Optional legal physical depth replays actual source backpressure. The
    minimum_depth is mathematical (at least two); supported_by_single_fifo
    flags requirements beyond the module's 65536-entry limit. This finite
    deterministic model proves no sustained throughput or other-load bound.
    """
    arrivals, m_pattern, m_windows = _load_inputs(arrivals, m_ready_pattern, m_stall_windows, depth, trace)
    _, w_pattern, w_windows = _load_inputs(arrivals, w_ready_pattern, w_stall_windows, depth, trace)
    lasts, lengths = _lms_framing(len(arrivals), frame_lengths, input_last, taps, mode)
    args = (arrivals, lasts, taps, m_pattern, w_pattern, m_windows, w_windows)
    unlimited = _lms_fifo_replay(*args, None, trace and depth is None)
    need = unlimited['peak']
    result = unlimited if depth is None else _lms_fifo_replay(*args, depth, trace)
    result.update(required_capacity=need, minimum_depth=max(2, need),
        ram_power_of_two=1 << (max(2, need) - 1).bit_length(),
        supported_by_single_fifo=need <= 65536, taps=taps, mode=mode,
        frames=len(lengths), frame_lengths=list(lengths),
        scope='Exact finite nominal load; initially empty configured FIFO/LMS; independent data and weight sinks; total FIFO capacity includes registered output; no reset/configuration or physical timing claim')
    return result


def lms_rate_bound(frame_lengths, taps, period, *, m_ready_pattern=(1,), w_ready_pattern=(1,)):
    """Necessary frame-aware service-rate bound for repeated LMS/NLMS loads.

    An always-ready filter needs 8*N+T+1 clocks from the first take of a frame
    to the first take of the next frame: final weights must drain before the
    next frame starts. Sum this cost over the repeated frame-length sequence.
    The two-clock initially empty FIFO startup is not part of this established
    service period. Extra sink stalls can only make service slower; passing
    the ideal bound therefore makes no finite-capacity or sufficiency claim.
    """
    try:
        lengths = tuple(frame_lengths)
        m_pattern, w_pattern = tuple(m_ready_pattern), tuple(w_ready_pattern)
    except TypeError as exc:
        raise ValueError('Frame lengths and ready patterns must be iterable') from exc
    if (not lengths or any(type(n) is not int or n < 1 for n in lengths)
            or type(taps) is not int or taps < 1 or type(period) is not int or period < 1):
        raise ValueError('Positive integer frame lengths, tap count and repeat period required')
    if any(not p or any(type(v) is not int or v not in (0, 1) for v in p)
           for p in (m_pattern, w_pattern)):
        raise ValueError('Ready patterns must contain binary integers')
    ideal = sum(8*n + taps + 1 for n in lengths)
    impossible = period < ideal or not any(m_pattern) or not any(w_pattern)
    return dict(frame_lengths=list(lengths), taps=taps, words_per_period=sum(lengths),
        period=period, minimum_processing_period=ideal,
        unavoidable_rate_deficit=impossible, finite_fifo_suffices=False if impossible else None,
        scope='Necessary ideal frame-aware service bound only; 8*N+T+1 clocks/frame with ready data and weight sinks; no finite-FIFO sufficiency or duty-cycle approximation')
