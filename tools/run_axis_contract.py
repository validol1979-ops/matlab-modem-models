#!/usr/bin/env python3
"""Verify held transfers, reset cancellation and seven protocol negative controls."""
import re
import subprocess
import sys

from regression_evidence import ROOT, begin, finish, questa_paths, write_json
from run_rtl import execute


FAULTS = {1: 'valid dropped', 2: 'data changed', 3: 'last changed',
          4: 'unknown valid', 5: 'unknown ready', 6: 'unknown last',
          7: 'unknown data'}


def main():
    if not __debug__:
        raise RuntimeError('Verification requires Python assertions enabled')
    output = ROOT / 'build/rtl/axis_contract'
    output.mkdir(parents=True, exist_ok=True)
    evidence = begin()
    target = output / 'all_results.json'
    write_json(target, dict(status='RUNNING', **evidence))
    artifacts, records = [], {}
    bindir, _ = questa_paths()
    try:
        for active in (1, 0):
            work = output / f'reset_{active}'
            work.mkdir(parents=True, exist_ok=True)
            if not (work / 'work').is_dir():
                execute([bindir / 'vlib', 'work'], work, work / 'vlib.log')
            compile_log = work / 'compile.log'
            execute([bindir / 'vlog', '-64', '-sv', ROOT / 'rtl/tb/axis_check.sv',
                     ROOT / 'rtl/tb/axis_contract_tb.sv'], work, compile_log)
            artifacts.append(compile_log)
            common = [bindir / 'vsim', '-64', '-c', '-quiet', 'work.axis_contract_tb',
                      f'-gRESET_ACTIVE={active}']
            script = work / 'run.do'
            script.write_text('onbreak {quit -code 13}\nonerror {quit -code 14}\nonfinish stop\nrun -all\nquit -code 0\n')
            artifacts.append(script)
            log = work / 'positive.log'
            text = execute([*common, '+FAULT=0', '-do',
                            'onerror {quit -code 14}; run -all; quit -code 0'], work, log)
            if f'PASS AXIS CONTRACT reset={active}' not in text or re.search(r'\*\* (?:Error|Fatal)', text):
                raise RuntimeError('Legal transfer or reset cancellation failed')
            artifacts.append(log)
            for fault, name in FAULTS.items():
                result = subprocess.run([str(x) for x in [*common, f'+FAULT={fault}', '-do', script.name]],
                                        cwd=work, capture_output=True, text=True, timeout=60)
                text = result.stdout + result.stderr
                log = work / f'fault_{fault}.log'
                log.write_text(text)
                artifacts.append(log)
                if (result.returncode == 0 or not re.search(r'\*\* Fatal:.*\[PROTOCOL\]', text)
                        or '[MISSED_FAULT]' in text or 'PASS AXIS CONTRACT' in text):
                    raise RuntimeError(f'Protocol checker did not reject {name}: {text[-2000:]}')
            records[f'reset_{active}'] = dict(positive='PASS', rejected=list(FAULTS.values()))
        write_json(target, dict(status='PASS', records=records, **finish(evidence, artifacts)))
    except Exception as exc:
        write_json(target, dict(status='FAIL', error=str(exc), records=records,
                                **finish(evidence, artifacts)))
        raise
    print('PASS AXIS CONTRACT: 2 legal/reset runs, 14 rejected protocol violations')
    return 0


if __name__ == '__main__':
    sys.exit(main())
