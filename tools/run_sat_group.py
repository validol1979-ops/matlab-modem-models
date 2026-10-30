#!/usr/bin/env python3
"""Verify 128-bit lane aggregation, per-lane gating and rejection controls."""
import re
import subprocess
from regression_evidence import ROOT, begin, finish, questa_paths, write_json
from run_rtl import execute


def main():
    if not __debug__:
        raise RuntimeError('Verification requires Python assertions enabled')
    output = ROOT/'build/rtl/sat_group'
    output.mkdir(parents=True, exist_ok=True)
    evidence = begin()
    target = output/'all_results.json'
    write_json(target, dict(status='RUNNING', **evidence))
    artifacts, records = [], {}
    bindir, _ = questa_paths()
    for width, style in ((34, 0), (44, 0), (17, 1), (23, 2)):
        for active in (1, 0):
            work = output/f'w{width}_style{style}_reset{active}'
            work.mkdir(parents=True, exist_ok=True)
            if not (work/'work').is_dir():
                execute([bindir/'vlib', 'work'], work, work/'vlib.log')
            expected = work/'expected.txt'
            expected.write_text('2\n4 2 0\n4 0 2\n')
            script = work/'negative.do'
            script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
            artifacts.extend([expected, script])
            execute([bindir/'vlog', '-64', '-sv', ROOT/'rtl/tb/sat_group_check.sv',
                     ROOT/'rtl/tb/sat_group_tb.sv'], work, work/'compile.log')
            artifacts.append(work/'compile.log')
            common = [bindir/'vsim', '-64', '-c', '-quiet', 'work.sat_group_tb',
                      f'-gRESET_ACTIVE={active}', f'-gOUT_WIDTH={width}', f'-gRANGE_STYLE={style}', f'+VECTORS={work}']
            text = execute([*common, '-do', 'onerror {quit -code 1}; run -all; quit -code 0'],
                           work, work/'positive.log')
            if ('PASS SATURATION group_unit: 8 evaluations, 4 events' not in text or
                    'PASS SAT GROUP UNIT' not in text or re.search(r'\*\* (?:Error|Fatal)', text)):
                raise RuntimeError('Grouped saturation checker positive control failed')
            artifacts.append(work/'positive.log')
            for name, flag in [('events', '+INJECT_SAT_MISMATCH'),
                               ('evaluations', '+INJECT_SAT_EVAL_MISMATCH'),
                               ('unknown', '+INJECT_SAT_X'), ('enable', '+INJECT_ENABLE_X')]:
                bad = subprocess.run([str(x) for x in [*common, flag, '-do', 'negative.do']],
                                     cwd=work, capture_output=True, text=True, timeout=60)
                text = bad.stdout+bad.stderr
                log = work/f'negative_{name}.log'
                log.write_text(text)
                artifacts.append(log)
                if (not bad.returncode or not re.search(r'\*\* Fatal:.*\[SATURATION\]', text)
                        or 'PASS SAT GROUP UNIT' in text):
                    raise RuntimeError(f'Grouped checker negative {name} not rejected')
            records[f'w{width}_style{style}_reset{active}'] = dict(status='PASS', evaluations=8,
                                                     events=4, negative_controls=4)
    write_json(target, dict(status='PASS', records=records, **finish(evidence, artifacts)))
    print('PASS SAT GROUP CHECKER: 8 positive runs, 32 rejected violations')


if __name__ == '__main__':
    main()
