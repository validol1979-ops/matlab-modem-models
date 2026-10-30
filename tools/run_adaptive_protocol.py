#!/usr/bin/env python3
"""Independent stable-valid cfg/data sources for LMS/RLS transaction boundaries."""
import argparse
import re
import subprocess
from regression_evidence import ROOT, begin, finish, write_json, questa_paths, require_unoptimized
from run_rtl import execute


def run_core(kind, output, artifacts, expect_failure=False):
    bindir, _ = questa_paths()
    work = output/kind; work.mkdir(parents=True, exist_ok=True)
    if not (work/'work').is_dir():
        execute([bindir/'vlib', 'work'], work, work/'vlib.log')
    sources = [ROOT/'rtl/common/mem/sync_rom.sv', ROOT/'rtl/common/fxp_divide_seq.sv',
               ROOT/'rtl/common/norm_reciprocal.sv', ROOT/'rtl/common/lms_filter.sv', ROOT/'rtl/common/rls_filter.sv',
               ROOT/'rtl/tb/axis_check.sv', ROOT/'rtl/tb/adaptive_protocol_tb.sv']
    execute([bindir/'vlog', '-64', '-sv', *sources], work, work/'compile.log'); artifacts.append(work/'compile.log')
    script = work/'probe.do'; negative_script = work/'negative_probe.do'
    script.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
    negative_script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
    artifacts.extend([script, negative_script]); results = []
    for active in (1, 0):
        for scenario in ('mid_frame', 'invalid_boundary', 'valid_boundary'):
            log = work/f'{scenario}_reset{active}.log'
            failed = expect_failure and scenario != 'valid_boundary'
            command = [bindir/'vsim', '-64', '-c', '-quiet', 'work.adaptive_protocol_tb', f'-gRLS={int(kind=="rls")}',
                       f'-gRESET_ACTIVE={active}', f'-gSCENARIO={scenario}',
                       f'-gRECIP_FILE={ROOT/"rtl/common/mem/lms_reciprocal.mem"}', '-do', negative_script.name if failed else script.name]
            result = subprocess.run([str(x) for x in command], cwd=work, capture_output=True, text=True, timeout=60)
            text = result.stdout+result.stderr; log.write_text(text); artifacts.append(log)
            if failed:
                valid = result.returncode != 0 and re.search(r'\*\* Fatal:.*\[PROTOCOL\]', text) and 'PASS ADAPTIVE PROTOCOL' not in text
            else:
                valid = result.returncode == 0 and 'PASS ADAPTIVE PROTOCOL' in text and not re.search(r'\*\* (?:Error|Fatal)', text)
            if not valid:
                raise RuntimeError(f'{kind}/{scenario}/reset{active}: unexpected rc={result.returncode}\n{text[-5000:]}')
            results.append(dict(kind=kind, scenario=scenario, reset_active=active, returncode=result.returncode,
                                expected_failure=failed, passed=not failed))
            print(f'PROTOCOL {kind}/{scenario}/reset{active}: rc={result.returncode}', flush=True)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--core', choices=('lms', 'rls', 'both'), default='both')
    parser.add_argument('--expect-failure', action='store_true', help='Audit known old-source failures; not successful regression evidence')
    parser.add_argument('--label', default='current')
    args = parser.parse_args(); require_unoptimized()
    output = ROOT/'build/rtl/adaptive_protocol'/args.label; output.mkdir(parents=True, exist_ok=True)
    evidence = begin(); artifacts = []; records = []
    write_json(output/'results.json', dict(evidence, status='RUNNING', records=[]))
    for kind in ('lms', 'rls') if args.core == 'both' else (args.core,):
        records.extend(run_core(kind, output, artifacts, args.expect_failure))
    status = 'KNOWN_FAILURES' if args.expect_failure else 'PASS'
    write_json(output/'results.json', dict(finish(evidence, artifacts), status=status, records=records))
    print(f'{status} ADAPTIVE PROTOCOL')


if __name__ == '__main__':
    main()
