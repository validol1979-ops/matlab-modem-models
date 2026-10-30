#!/usr/bin/env python3
"""Continuous-rate Costas loop (rtl/common/costas_stream.sv): model vectors, strict lint, Questa
scoreboard, disturbance scenarios and the derived loop parameters.

What is claimed (functional only - synthesis is on the agreed pause, so no clock period or Fmax):
1. Throughput. With s_valid and m_ready held high the DUT accepts one sample per clock: the bench
   measures the longest run of consecutive accepts (RUN_LEN) and the largest gap between two accepts
   (GAP_MAX) instead of assuming them; every case must reach RUN_LEN == samples and GAP_MAX == 0.
2. Arithmetic. Every accepted output (re, im, the 32-bit phase that was used and the last flag) is
   compared bit exactly against sync_fixed.costas_pipelined, i.e. against the same integer rotator,
   discriminator, round and 32-bit wrap as costas_loop.sv, only with the loop delay counted in
   pipeline advances instead of restarting the loop for every transaction.
3. Loop delay. LOOP_DELAY = 10 advances (the rotator's 7-clock latency plus the error, product and
   update stages) = 1.25 symbols at sps=8. A backpressure stall freezes every stage, so it removes
   advances and leaves the outputs unchanged (the +STALL_OUTPUT runs must reproduce the dense
   vectors); an INPUT bubble is a missing advance that shortens the delay in samples, so the
   +STALL_INPUT runs are scored against the same model fed with the acceptance pattern the bench
   logs (sync_fixed.costas_pipelined(..., gaps)). Both behaviours are measured, not asserted.
4. Protocol. cfg_ready stays low while any sample is accepted-but-not-delivered (a configuration
   offered mid-stream is refused, +CFG_PROBE) and comes back once the pipeline drains; a reset
   returns the DUT to unconfigured and silent (+RESET_MID).
5. Stability, and where the delay bites. The RTL uses the already updated frequency in the phase
   update (costas_loop.sv:47-49), so the characteristic polynomial of the exact update order is
   z^D (z-1)^2 + a z (z-1) + b z^2 with a = Kd k1 / 2^15, b = Kd k2 / 2^15 and Kd the QPSK detector
   slope measured on the integer model (tools/loop_delay_study.py, reused). At D = 10 it has spectral
   radius < 1 for k=(.08,.001) and k=(.02,.0001) but > 1 for k=(.3,.01): the continuous-rate loop
   must use the smaller gain set, and the aggressive acquisition setting stays with costas_loop.sv.
   The claim is cross-checked on the integer model itself: the tracked phase residual against the
   generated carrier (modulo 90 degrees, a QPSK Costas loop locks with a four-fold ambiguity) and the
   largest delay at which the model still locks. Both a linear and a simulated number are recorded.
"""
import argparse
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

from regression_evidence import ROOT, begin, finish, write_json, questa_paths
from run_rtl import execute, SOURCES
from costas_stream_cases import CASES, CARRIERS, LOCKED, LOOP_DELAY, vectors
import sync_fixed
from loop_delay_study import detector_gain, poly_carrier, open_carrier, radius, max_delay

PILOT = ROOT / 'rtl/modems/bpsk_costas_2008_08_25'
DUT = ROOT / 'rtl/common/costas_stream.sv'
TABLES = PILOT / 'tables'
PASS = re.compile(r'PASS COSTAS_STREAM: (\d+) samples, (\d+) outputs, run_max (\d+), gap_max (\d+), '
                  r'out_gap_max (\d+), span (\d+), cycles (\d+)')
HOLD = re.compile(r'^(?:#\s*)?COSTAS_STREAM backpressure hold checks: (\d+)[ \t]*$', re.MULTILINE)
SCENARIOS = (('dense', []), ('stall_out', ['+STALL_OUTPUT']), ('cfg_probe', ['+CFG_PROBE']),
             ('reset_mid', ['+RESET_MID']))
STALLED = ['+STALL_INPUT', '+NO_SCORE']
RESETS = (1, 0)
GAIN_SETS = [(.08, .001), (.3, .01), (.02, .0001)]


def hold_coverage(text, required):
    """Require one unambiguous monitor count and actual coverage on stalled runs."""
    counts = HOLD.findall(text)
    if len(counts) != 1 or (required and int(counts[0]) < 1):
        raise RuntimeError('[COVERAGE] missing or invalid Costas output hold checks')
    return int(counts[0])


def check_negative(text, returncode, tag, detail=None):
    """Reject unrelated failures and false success markers in a negative control."""
    if (type(returncode) is not int or returncode != 13
            or not re.search(r'\*\* Fatal:[^\n]*\[' + re.escape(tag) + r'\]'
                             + (r'[^\n]*' + re.escape(detail) if detail else ''), text)
            or PASS.search(text)):
        raise RuntimeError(f'[{tag}] negative control not detected')
    return dict(status='PASS', vsim_exit_code=returncode)


def residual(values, phases, carrier):
    """Mean |tracked phase - carrier phase| modulo 90 degrees over the second half of the case."""
    quarter = math.pi / 2
    tail = range(len(phases) // 2, len(phases))
    return sum(abs((((phases[n] / 2**32 * 2 * math.pi - carrier(n)) % quarter) + quarter / 2)
                   % quarter - quarter / 2) for n in tail) / len(tail)


def lock_parameters():
    """Does the integer model lock, and up to which delay (functional, no timing claim)?"""
    records = {}
    for name, carrier in CARRIERS.items():
        data, _ = CASES[name][0]()
        gains = sync_fixed.costas_gains(*CASES[name][1])
        measured = {delay: residual(*sync_fixed.costas_pipelined(data, gains, delay), carrier)
                    for delay in (1, LOOP_DELAY)}
        largest = 0
        for delay in range(1, 66):        # a short case is conservative, so the cap is generous
            if residual(*sync_fixed.costas_pipelined(data, gains, delay), carrier) >= .05:
                break
            largest = delay
        if (measured[LOOP_DELAY] < .05) != LOCKED[name]:
            raise RuntimeError(f'[LOCK] {name}: measured residual {measured[LOOP_DELAY]:.4f} rad does '
                               f'not match the documented lock state {LOCKED[name]}')
        records[name] = dict(gains=CASES[name][1], residual_delay_1=measured[1],
                             residual_delay_10=measured[LOOP_DELAY],
                             locked_at_delay_10=measured[LOOP_DELAY] < .05,
                             max_locking_delay=largest)
    return records


def loop_parameters():
    """Spectral radius at LOOP_DELAY and the largest stable delay, per gain set (see module doc)."""
    kd = abs(detector_gain('qpsk', 'phase', .02))        # phase error per radian, measured
    records = {}
    for k1, k2 in GAIN_SETS:
        a, b = kd * k1 / 2**15, kd * k2 / 2**15          # rad per rad per sample
        # The RTL uses the already updated frequency in the phase update: z^D (z-1)^2 + a z (z-1) + b z^2.
        make = lambda D, g, a=a, b=b: poly_carrier(D, g * a, g * b, 'angle')
        delay, wc, pm0, verified = max_delay(make, open_carrier(a, b, 'angle'))
        records[f'{k1},{k2}'] = dict(k1=k1, k2=k2, kd_pe_per_rad=kd, a=a, b=b,
                                     delay=LOOP_DELAY, radius=radius(make(LOOP_DELAY, 1.)),
                                     stable=radius(make(LOOP_DELAY, 1.)) < 1,
                                     phase_margin_deg=57.29577951308232 * (pm0 - wc * LOOP_DELAY),
                                     max_stable_delay=delay, max_delay_root_verified=verified)
    low, high = .001, .6                                  # largest k1 with k2 = k1/80 at this delay
    for _ in range(60):
        mid = (low + high) / 2
        steady = radius(poly_carrier(LOOP_DELAY, kd * mid / 2**15, kd * mid / 80 / 2**15, 'angle')) < 1
        low, high = (mid, high) if steady else (low, mid)
    records['gain_limit_k2_over_k1_80'] = dict(k1=low, k2=low / 80,
                                               note='largest k1 with k2=k1/80 stable at '
                                                    f'delay {LOOP_DELAY}; '
                                                    f'margin over (.08,.001) is {low / .08:.2f}x')
    return records


def read_ints(path):
    """Every integer of a log file, one or more per line (the acceptance log has no header)."""
    return [int(value) for line in path.read_text().split('\n') if line.strip()
            for value in line.split()]


def check_stalled(folder, accepted_steps, observed):
    """Score a stalled run against the same model fed with the advances the bench logged."""
    def builder(name):
        return CASES[name][0]()
    name = folder.name
    data, last = builder(name)
    gains = sync_fixed.costas_gains(*CASES[name][1])
    steps = read_ints(accepted_steps)
    if len(steps) != len(data):
        raise RuntimeError(f'[COUNT] {name}: {len(steps)} of {len(data)} acceptances logged')
    gaps = [steps[0]] + [steps[n] - steps[n - 1] for n in range(1, len(steps))]
    values, phases = sync_fixed.costas_pipelined(data, gains, LOOP_DELAY, gaps)
    rows = [[int(v) for v in line.split()] for line in observed.read_text().split('\n') if line.strip()]
    if len(rows) != len(values):
        raise RuntimeError(f'[COUNT] {name}: {len(rows)} observed of {len(values)} outputs')
    for n, (re, im, phase, flag) in enumerate(rows):
        if (re, im, phase) != (values[n][0], values[n][1], phases[n]) or flag != int(last[n]):
            raise RuntimeError(f'[NUMERIC] {name} stalled output {n}: {re},{im},{phase},{flag} '
                               f'!= {values[n][0]},{values[n][1]},{phases[n]},{int(last[n])}')
    intervals = gaps[1:]
    return dict(samples=len(steps), outputs=len(rows),
                max_accept_interval_advances=max(intervals) if intervals else 0,
                max_input_bubble_advances=max(intervals) - 1 if intervals else 0,
                first_advance=steps[0], slowest_sample_delay=LOOP_DELAY - (max(intervals) - 1)
                if intervals else LOOP_DELAY)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', choices=['python', 'lint', 'hdl', 'all'], default='all')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/rtl/costas_stream',
                        help='directory for this run; use a separate directory to preserve prior evidence')
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError('Run verification without Python optimization (-O)')
    if args.suite in ('all', 'lint', 'hdl') and not DUT.is_file():
        raise RuntimeError(f'Missing DUT {DUT}')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    evidence = begin()
    target = output / f'{args.suite}_results.json'
    write_json(target, dict(evidence, status='RUNNING'))
    artifacts, records = [], {}
    if args.suite in ('all', 'python'):
        # The model must reduce to the per-transaction loop when the delay is one sample.
        import random
        rng = random.Random(7)
        probe = [(rng.randrange(-131072, 131072), rng.randrange(-131072, 131072)) for _ in range(300)]
        for k1, k2 in GAIN_SETS:
            gains = sync_fixed.costas_gains(k1, k2)
            if sync_fixed.costas(probe, gains) != sync_fixed.costas_pipelined(probe, gains, 1):
                raise RuntimeError(f'[MODEL] delay=1 differs from costas() for gains {k1},{k2}')
        loop = loop_parameters()
        lock = lock_parameters()
        unstable = sorted(key for key, value in loop.items() if key != 'gain_limit_k2_over_k1_80'
                          and value['radius'] >= 1)
        if unstable != ['0.3,0.01']:
            raise RuntimeError(f'[STABILITY] unexpected unstable gain sets at delay {LOOP_DELAY}: '
                               f'{unstable}')
        log = output / 'loop_parameters.json'
        write_json(log, dict(loop_delay=LOOP_DELAY, gains=loop, lock=lock))
        artifacts.append(log)
        records['python'] = dict(status='PASS', delay_one_equals_costas=True, loop=loop, lock=lock)
    if args.suite in ('all', 'lint'):
        log = output / 'lint.log'
        text = execute(['verilator', '--lint-only', '-Wall', '--top-module', 'costas_stream',
                        f'-I{PILOT}', *SOURCES], ROOT, log)
        if '%Warning' in text:
            raise RuntimeError('Lint warnings: costas_stream')
        artifacts.append(log)
        records['lint'] = 'PASS'
    if args.suite in ('all', 'hdl'):
        bindir, _ = questa_paths()
        base = output / 'vectors'
        if base.is_dir():
            shutil.rmtree(base)                    # never leave a stale case in the evidence
        table = vectors(base)
        artifacts.extend(base.rglob('*.txt'))
        scored = {}
        for active in RESETS:
            work = output / f'work_reset_{active}'
            work.mkdir(parents=True, exist_ok=True)
            if not (work / 'work').is_dir():
                execute([bindir / 'vlib', 'work'], work, work / 'vlib.log')
            execute([bindir / 'vlog', '-64', '-sv', f'+incdir+{PILOT}', *SOURCES,
                     ROOT / 'rtl/tb/costas_stream_tb.sv'], work, work / 'compile.log')
            artifacts.append(work / 'compile.log')
            common = [bindir / 'vsim', '-64', '-c', '-quiet', 'work.costas_stream_tb',
                      f'-gRESET_ACTIVE={active}', f'-gTABLE_DIR={TABLES}']
            run_all = ['-do', 'onerror {quit -code 1}; run -all; quit -code 0']
            for index, name in enumerate(CASES):
                folder = base / name
                samples, gains, _ = table[name]
                entry = {'gains': gains, 'samples': samples, 'reset_active': active}
                for scenario, options in SCENARIOS:
                    log = work / f'{name}_{scenario}.log'
                    text = execute([*common, f'+VECTORS={folder}', *options, *run_all], work, log)
                    match = PASS.search(text)
                    if not match or re.search(r'\*\* (?:Error|Fatal)', text):
                        raise RuntimeError(text[-6000:])
                    numbers = dict(zip(('samples', 'outputs', 'run_max', 'gap_max', 'out_gap_max',
                                        'span', 'cycles'), (int(v) for v in match.groups())))
                    if numbers['samples'] != samples or numbers['outputs'] != samples:
                        raise RuntimeError(f'[COUNT] {name} {scenario}: {numbers}')
                    numbers['hold_checks'] = hold_coverage(text, scenario == 'stall_out')
                    if scenario == 'dense':
                        if numbers['run_max'] != samples or numbers['gap_max'] != 0:
                            raise RuntimeError(f'[THROUGHPUT] {name}: {numbers}')
                        if numbers['span'] != samples - 1:
                            raise RuntimeError(f'[THROUGHPUT] {name}: span {numbers["span"]}')
                        numbers['ii_one'] = True
                    if scenario == 'cfg_probe' and 'CFG_PROBE: refused while busy, accepted when idle' not in text:
                        raise RuntimeError(f'[PROTOCOL] {name}: {text[-3000:]}')
                    entry[scenario] = numbers
                    artifacts.append(log)
                steps = work / f'{name}_stalled_acc.txt'
                observed = work / f'{name}_stalled_out.txt'
                log = work / f'{name}_stall_in.log'
                text = execute([*common, f'+VECTORS={folder}', *STALLED, f'+ACCEPT_LOG={steps}',
                                f'+OBSERVED={observed}', *run_all], work, log)
                if not PASS.search(text) or re.search(r'\*\* (?:Error|Fatal)', text):
                    raise RuntimeError(text[-6000:])
                entry['stall_in'] = check_stalled(folder, steps, observed)
                entry['stall_in']['hold_checks'] = hold_coverage(text, False)
                entry['stall_in']['model_gaps'] = 'sync_fixed.costas_pipelined(..., gaps)'
                artifacts.extend([log, steps, observed])
                if index == 0:
                    script = work / 'numeric_negative.do'
                    script.write_text('onfinish stop\nonerror {quit -code 13}\n'
                                      'onbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                    artifacts.append(script)
                    for key, tag, detail, options in (
                            ('negative', 'NUMERIC', 'costas_stream output', ['+INJECT_MISMATCH']),
                            ('hold_negative', 'PROTOCOL', 'costas_stream output changed under backpressure',
                             ['+STALL_OUTPUT', '+INJECT_HOLD_MISMATCH'])):
                        bad = subprocess.run([str(x) for x in [*common, f'+VECTORS={folder}',
                                                               *options, '-do', script.name]],
                                             cwd=work, capture_output=True, text=True, timeout=300)
                        negative = bad.stdout + bad.stderr
                        log = work / (key + '.log')
                        log.write_text(negative)
                        entry[key] = check_negative(negative, bad.returncode, tag, detail)
                        artifacts.append(log)
                scored[f'{name}_reset_{active}'] = entry
                print(f"PASS COSTAS_STREAM {name} reset={active} samples={samples} "
                      f"run_max={entry['dense']['run_max']} stalls_out={entry['stall_out']['run_max']} "
                      f"first_advance={entry['stall_in']['first_advance']}", flush=True)
        records['hdl'] = scored
    write_json(target, dict(status='PASS', records=records, claims=dict(
        continuous_rate='measured: every dense run reaches run_max == samples and gap_max == 0',
        loop_delay_advances=LOOP_DELAY, loop_delay_symbols_sps8=LOOP_DELAY / 8,
        arithmetic='bit exact against sync_fixed.costas_pipelined at the same delay',
        backpressure='output stalls freeze the pipeline, outputs unchanged',
        input_bubbles='scored against the model fed with the logged acceptance advances',
        stop_condition='none: continuous stream, s_last is copied and never restarts the loop',
        gain_limit='(.3,.01) is bit exact but does not lock at this delay: use costas_loop.sv',
        physical_timing='not verified: synthesis is on the agreed pause'),
        **finish(evidence, artifacts)))
    print(f'PASS COSTAS_STREAM {args.suite}')


if __name__ == '__main__':
    main()
