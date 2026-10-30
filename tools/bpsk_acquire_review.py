"""Shared direct-acquisition vectors and strict state-coverage acceptance gates."""
import re
import numpy as np
from bpsk_cases import p

ACQUIRE_SCENARIOS = ('baseline', 'reset_fit', 'reset_div', 'reset_score', 'reset_replay', 'busy_start')
DIVIDE_SCENARIOS = ('all', 'one', 'max')


def direct_vectors(folder, profile):
    rng=np.random.default_rng(194)
    preamble=rng.integers(0,profile.alphabet,192).tolist()
    ids=p.encode(profile,preamble)
    # Zero gives equal scores (strict first-candidate tie); constants and full-scale
    # alternating values cover low confidence, clamping and saturation at interpolation.
    waves=[[(0,0)]*1536,[(131071,131071)]*1536,[(-131072,-131072)]*1536,
           [(131071,-131072)]*1536,
           [(131071 if k&1 else -131072,-131072 if k&1 else 131071) for k in range(1536)]]
    waves += [[tuple(map(int,z)) for z in rng.integers(-131072,131072,(1536,2))] for _ in range(8)]
    lines=[str(len(waves))]
    for wave in waves:
        acq=p.acquire(profile,wave,preamble)
        energies=[sum(wave[n][0]**2+wave[n][1]**2 for n in range(64+i,320,8)) for i in range(8)]
        lines.append(' '.join(str(int(acq[k])) for k in ('delay','frequency','phase','gain','score','confidence')))
        lines.append(' '.join(map(str,energies)))
        lines.append(' '.join(map(str,ids[32:160])))
        lines += [f'{r} {i}' for r,i in wave]
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'acquire_direct.txt').write_text('\n'.join(lines)+'\n')
    return len(waves)



def checked_acquire(text, scenario, count, *, negative=False):
    if scenario not in ACQUIRE_SCENARIOS or count < 1:
        raise ValueError('Invalid acquisition scenario/count')
    targets = re.findall(r'ACQUIRE TARGET scenario=(\w+) case=(\d+) state=(\d+) div=(\d+) score=(\d+) replay=(\d+)', text)
    expected = 0 if scenario == 'baseline' else (1 if negative else count)
    if len(targets) != expected:
        raise RuntimeError('Missing/duplicate acquisition state markers')
    for index, (name, case, state, div, score, replay) in enumerate(targets):
        if name != scenario or int(case) != index or int(state) not in (7, 8):
            raise RuntimeError('Wrong acquisition state marker')
        if scenario in ('reset_div', 'busy_start') and int(div) != 1:
            raise RuntimeError('DIV state not reached')
        if scenario == 'reset_score' and int(score) != 1:
            raise RuntimeError('SCORE state not reached')
        if scenario == 'reset_replay' and int(replay) != 1:
            raise RuntimeError('Replay not active')
    if negative:
        if 'PASS ACQUIRE SCENARIO' in text or 'PASS BPSK direct acquisition:' in text:
            raise RuntimeError('Negative acquisition printed positive PASS')
        return
    if re.search(r'UVM_(?:FATAL|ERROR)|\*\* (?:Error|Fatal)|%Fatal:|%Error', text):
        raise RuntimeError('Acquisition scoreboard failed')
    rows = re.findall(r'PASS DIRECT ACQUISITION case=(\d+) repeat=(\d+) A=(\d+)', text)
    if [(int(j), int(k)) for j, k, _ in rows] != [(j, k) for j in range(count) for k in range(2)]:
        raise RuntimeError('Missing/reordered exact acquisition results')
    marker = re.findall(r'PASS ACQUIRE SCENARIO (\w+): reached=(\d+) exact=(\d+) divisor_checks=(\d+)', text)
    if len(marker) != 1 or marker[0][:3] != (scenario, str(expected), str(2*count)) or int(marker[0][3]) < 8*count:
        raise RuntimeError('Incomplete acquisition scenario/divisor assertion coverage')
    if f'PASS BPSK direct acquisition: {count} exact results' not in text:
        raise RuntimeError('Direct scoreboard incomplete')
    if scenario == 'busy_start':
        latencies = re.findall(r'ACQUIRE BUSY START case=(\d+) pulsed_latency=(\d+) clean_latency=(\d+)', text)
        if (len(latencies) != count or [int(j) for j, _, _ in latencies] != list(range(count))
                or any(a != b or int(a) <= 0 for _, a, b in latencies)):
            raise RuntimeError('Busy start changed acquisition latency or missing comparison')
    return dict(reached=expected, exact_results=2*count, divisor_checks=int(marker[0][3]))


def checked_divide(text, scenario, counts):
    if scenario not in DIVIDE_SCENARIOS:
        raise ValueError('Invalid divider scenario')
    if re.search(r'UVM_(?:FATAL|ERROR)|\*\* (?:Error|Fatal)|%Fatal:|%Error', text):
        raise RuntimeError('Divider scoreboard failed')
    rows = re.findall(r'PASS DIVIDE BOUNDARIES scenario=(\w+) one=(\d+) max=(\d+) modes=1,2', text)
    one = counts['one'] if scenario != 'max' else 0
    maximum = counts['max'] if scenario != 'one' else 0
    total = counts['all'] if scenario == 'all' else counts[scenario]
    if rows != [(scenario, str(one), str(maximum))] or total < 1:
        raise RuntimeError('Missing divider endpoint/mode coverage')
    if f'PASS BPSK divider modes: {total} exact results, latency=66/34' not in text:
        raise RuntimeError('Incomplete divider mode/latency coverage')
    return dict(exact_results=total, one=one, max=maximum, steps_per_cycle=[1, 2])


def divider_counts(path):
    rows = [tuple(map(int, row.split())) for row in path.read_text().splitlines()[1:]]
    return dict(all=len(rows), one=sum(d == 1 for _, d, _ in rows), max=sum(d == 2**32-1 for _, d, _ in rows))


def checked_divide_negative(text, scenario, mode):
    denominator = {'one': 1, 'max': 2**32-1}[scenario]
    if (f'DIVIDE TARGET scenario={scenario} denominator={denominator} modes=1,2' not in text
            or not re.search(rf'\[NUMERIC\][^\n]*scenario={scenario}[^\n]*d={denominator} mode={mode}\b', text)
            or 'PASS BPSK divider modes:' in text or 'PASS DIVIDE BOUNDARIES' in text):
        raise RuntimeError('Missing divider negative endpoint/mode coverage')
