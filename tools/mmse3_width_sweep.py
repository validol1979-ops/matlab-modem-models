#!/usr/bin/env python3
"""MMSE3 Gram/output width proof, raw observations and frozen-RTL equivalence."""
import argparse
import hashlib
from itertools import product
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from regression_evidence import ROOT, begin, finish, write_json, require_unoptimized, questa_paths
from mmse3_cases import vectors, CASES as NATIVE_CASES
from spectral_evidence import check_observers
sys.path.insert(0, str(ROOT/'common/python'))
import mmse3_widths as widths

CASES = (*NATIVE_CASES, 'gram_peak')
LAYOUTS = (('selected',38,84), ('old_all',40,85), ('old_gram',40,84), ('old_sum',38,85))
INVALID = (('gram_low',37,84), ('gram_high',41,84), ('sum_low',38,83), ('sum_high',38,86))
SCENARIOS = {'stream':[], 'stalled':['+STALL_INPUT','+STALL_OUTPUT'],
             'midreset':['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT'],
             'outreset':['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'],
             'cfgreset':['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT']}
TAGS = ('GRAM','SUM','ROUND')
DIRECTED_COUNTS = dict(gram_checks=32770, sum_checks=24576, round_checks=24599)
BASELINE_REV = '1d22c17'
SOURCES = [ROOT/'rtl/common/fxp_divide_seq.sv', ROOT/'rtl/common/norm_reciprocal.sv', ROOT/'rtl/common/mmse3.sv']


def rows(path):
    return [tuple(map(int,line.split())) for line in path.read_text().splitlines() if line.strip()]


def bank(values):
    return dict(count=len(values), min=min(values), max=max(values))


def fixture(index, case, folder):
    data = vectors(folder, case, seed=53+index)
    cfg = rows(folder/'cfg.txt'); h = cfg[:9]; lam = cfg[9][0]
    w = rows(folder/'weights.txt'); observations = [v[:2] for v in rows(folder/'in.txt')]
    gram = widths.gram(h, lam)
    raw = [widths.sums(w, observations[k:k+3]) for k in range(0,len(observations),3)]
    clipped = [(widths.rounded(t[2*i],clip=True), widths.rounded(t[2*i+1],clip=True)) for t in raw for i in range(3)]
    if clipped != [v[:2] for v in rows(folder/'out.txt')]:
        raise RuntimeError('Independent raw trace disagrees with fixed MMSE3 model')
    banks = [bank(gram[0::2]),bank(gram[1::2])]
    banks += [bank([t[k] for t in raw]) for k in range(6)]
    banks += [bank([widths.rounded(t[k]) for t in raw]) for k in range(6)]
    return dict(case=case, outputs=data['outputs'], triples=len(raw), banks=banks,
                vector_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()})


def report():
    with tempfile.TemporaryDirectory() as tmp:
        records = [fixture(i,case,Path(tmp)/case) for i,case in enumerate(CASES)]
    return dict(scope='MMSE3 Gram expressions and full signed64-weight output sums; synthesis paused',
                bounds=widths.layout(), records=records, baseline_revision=BASELINE_REV,
                rtl_verified=False, rtl_equivalence=[], rtl_frozen=[], rtl_parameters=[],
                rtl_directed=[], rtl_negative=[], rtl_lint=[])


def require(ok, reason):
    if not ok: raise RuntimeError(reason)


def coverage(records, keys, expected):
    for r in records:
        if 'active' in keys:
            require(type(r.get('active')) is int, 'Invalid reset polarity type')
    require(len(records)==len(expected) and {tuple(r[k] for k in keys) for r in records}==expected,
            'Incomplete or duplicate MMSE3 coverage: '+','.join(keys))


def check_acceptance(result):
    model = report()
    require(all(result[k]==model[k] for k in ('bounds','records','baseline_revision')), 'Changed MMSE3 model evidence')
    sections = ('rtl_equivalence','rtl_frozen','rtl_parameters','rtl_directed','rtl_negative','rtl_lint')
    require(type(result['rtl_verified']) is bool, 'Invalid verification flag')
    if not result['rtl_verified']:
        require(not any(result[k] for k in sections), 'Unverified MMSE3 observations')
        return
    expected = set(product(CASES, [v[0] for v in LAYOUTS], (1,0), SCENARIOS))
    coverage(result['rtl_equivalence'], ('case','layout','active','scenario'), expected)
    for r in result['rtl_equivalence']:
        source = next(s for s in model['records'] if s['case']==r['case'])
        layout = next(v for v in LAYOUTS if v[0]==r['layout'])
        require(r['widths']==list(layout[1:]) and r['outputs']==source['outputs'] and
                all(type(v) is int for v in r['widths']) and type(r['outputs']) is int and
                type(r['cycles']) is int and r['cycles']>0 and r['observers_verified'] is True, 'Missing MMSE3 numeric evidence')
        require(len(r['banks'])==14, 'Missing MMSE3 raw banks')
        for i,(observed,reference) in enumerate(zip(r['banks'],source['banks'])):
            # Warm-up observations before MID/OUT reset are discarded by both monitors.
            require(observed==reference and all(type(observed[k]) is int for k in ('count','min','max')),
                    'Changed MMSE3 raw bank '+str(i))
        counts = [b['count'] for b in r['banks']]
        require(r['gram_checks']==sum(counts[:2]) and r['sum_checks']==sum(counts[2:8]) and
                r['round_checks']==sum(counts[8:]) and all(type(r[k]) is int for k in ('gram_checks','sum_checks','round_checks')),
                'MMSE3 observation count mismatch')
    for case,a,s in product(CASES,(1,0),SCENARIOS):
        group = [r for r in result['rtl_equivalence'] if (r['case'],r['active'],r['scenario'])==(case,a,s)]
        require(len({r['cycles'] for r in group})==1, 'MMSE3 layouts changed timing')
    coverage(result['rtl_frozen'], ('case','active','scenario'), set(product(CASES,(1,0),SCENARIOS)))
    for r in result['rtl_frozen']:
        source = next(s for s in model['records'] if s['case']==r['case'])
        require(type(r['old_cycles']) is int and r['old_cycles']>0 and r['old_cycles']==r['new_cycles'] and
                r['old_outputs']==r['new_outputs']==source['outputs'] and
                all(type(r[k]) is int for k in ('new_cycles','old_outputs','new_outputs')), 'Frozen MMSE3 mismatch')
    coverage(result['rtl_directed'], ('layout','active'), set(product([v[0] for v in LAYOUTS],(1,0))))
    for r in result['rtl_directed']:
        layout = next(v for v in LAYOUTS if v[0]==r['layout'])
        require(r.get('passed') is True and r.get('widths')==list(layout[1:]) and
                all(type(v) is int for v in r['widths']) and
                all(type(r.get(k)) is int and r[k]==v for k,v in DIRECTED_COUNTS.items()), 'Missing directed evidence')
    coverage(result['rtl_parameters'],('layout','active'),set(product([v[0] for v in INVALID],(1,0))))
    coverage(result['rtl_negative'],('bench','tag','active'),set(product(('stream','directed'),TAGS,(1,0))))
    for section in ('rtl_parameters','rtl_negative'):
        require(all(type(r.get('returncode')) is int and r['returncode']==13 for r in result[section]), 'Missing rejection exit code')
    coverage(result['rtl_lint'],('layout',),{(v[0],) for v in LAYOUTS})
    require(all(type(r.get('warnings')) is int and r['warnings']==0 for r in result['rtl_lint']), 'MMSE3 lint warnings')


def parse_raw(text):
    pattern=r'PASS MMSE3 WIDTHS GRAM_WIDTH=(\d+) SUM_WIDTH=(\d+) gram=(\d+) sum=(\d+) round=(\d+)'
    require(len(re.findall(pattern,text))==1, 'Missing or duplicate MMSE3 raw summary')
    m = re.search(pattern, text)
    found = re.findall(r'MMSE3 WIDTHS BANK bank=(\d+) count=(\d+) min=(-?\d+) max=(-?\d+)',text)
    require(len(found)==14 and [int(v[0]) for v in found]==list(range(14)), 'Incomplete MMSE3 banks')
    return dict(widths=list(map(int,m.groups()[:2])),gram_checks=int(m[3]),sum_checks=int(m[4]),round_checks=int(m[5]),
                banks=[dict(count=int(c),min=int(lo),max=int(hi)) for _,c,lo,hi in found])


def verify_rtl(result, base):
    base.mkdir(parents=True,exist_ok=True); artifacts=[]
    bindir,_ = questa_paths()
    for i,case in enumerate(CASES):
        folder=base/'vectors'/case
        require(fixture(i,case,folder)==result['records'][i], 'MMSE3 vectors changed')
        artifacts.extend(p for p in folder.iterdir() if p.is_file())
    def command(args,work,name,tag=None,allow_warnings=('(vopt-13314)','(vopt-2244)')):
        log=work/(name+'.log')
        if tag:
            args=[('negative.do' if str(v)=='run.do' else v) for v in args]
        proc=subprocess.run(list(map(str,args)),cwd=work,capture_output=True,text=True,timeout=180)
        output=proc.stdout+proc.stderr;log.write_text(output);artifacts.append(log)
        if tag:
            require(proc.returncode==13 and re.search(r'\*\* Fatal:.*\['+tag+r'\]',output) and
                    'PASS MMSE3:' not in output and 'PASS MMSE3 WIDTH DIRECTED' not in output,
                    'MMSE3 negative control missed: '+name)
        else:
            warning_lines=re.findall(r'^.*\*\* Warning:.*$',output,re.MULTILINE)
            require(proc.returncode==0 and not re.search(r'\*\* (?:Error|Fatal)|%Warning',output) and
                    all(any(code in line for code in allow_warnings) for line in warning_lines),
                    'MMSE3 command failed: '+str(log)+'\n'+output[-4000:])
        return output,proc.returncode
    def compile_work(name,dut,tb,directed=False):
        work=base/name;work.mkdir(exist_ok=True)
        if not (work/'work').is_dir():
            command([bindir/'vlib','work'],work,'vlib')
        elif (work/'vlib.log').is_file():
            artifacts.append(work/'vlib.log')
        command([bindir/'vlog','-64','-sv',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES[:2],dut,
                 ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_event_check.sv',tb,
                 *([ROOT/'rtl/tb/mmse3_width_tb.sv'] if directed else [])],work,'compile',
                allow_warnings=('(vlog-13314)','(vlog-2244)'))
        for filename,onbreak in (('run.do',''),('negative.do','onbreak {quit -code 13}\n')):
            script=work/filename
            script.write_text('onfinish stop\nonerror {quit -code 13}\n'+onbreak+'run -all\nquit -code 0\n')
            artifacts.append(script)
        return work
    work=compile_work('current',SOURCES[2],ROOT/'rtl/tb/mmse3_tb.sv',True)
    for label,g,y in LAYOUTS:
        command(['verilator','--lint-only','-Wall','--top-module','mmse3',f'-GGRAM_WIDTH={g}',f'-GSUM_WIDTH={y}',*SOURCES],work,'lint_'+label)
        result['rtl_lint'].append(dict(layout=label,warnings=0))
    for active in (1,0):
        for label,g,y in LAYOUTS:
            options=[f'-gRESET_ACTIVE={active}',f'-gGRAM_WIDTH={g}',f'-gSUM_WIDTH={y}']
            for case in CASES:
                for scenario,flags in SCENARIOS.items():
                    output,_=command([bindir/'vsim','-64','-c','-quiet','work.mmse3_tb',*options,f'+VECTORS={base/"vectors"/case}',
                                      '+CHECK_MMSE3_WIDTHS',*flags,'-do','run.do'],work,f'{case}_{label}_{active}_{scenario}')
                    require(len(re.findall(r'PASS MMSE3: (\d+) outputs, (\d+) cycles',output))==1, 'Missing or duplicate numeric summary')
                    m=re.search(r'PASS MMSE3: (\d+) outputs, (\d+) cycles',output)
                    require(m is not None and re.search(r'PASS BOUNDS mmse3: [1-9]\d* checks',output), 'Missing MMSE3 scoreboard/bounds')
                    check_observers(output,base/'vectors'/case,'mmse3')
                    result['rtl_equivalence'].append(dict(case=case,layout=label,active=active,scenario=scenario,
                        outputs=int(m[1]),cycles=int(m[2]),observers_verified=True,**parse_raw(output)))
            output,_=command([bindir/'vsim','-64','-c','-quiet','work.mmse3_width_tb',*options,'-do','run.do'],work,f'directed_{label}_{active}')
            direct=re.findall(r'PASS MMSE3 WIDTH DIRECTED GRAM_WIDTH=(\d+) SUM_WIDTH=(\d+) gram=(\d+) sum=(\d+) round=(\d+)',output)
            require(len(direct)==1,'Missing directed MMSE3 evidence')
            dg,dy,gc,sc,rc=map(int,direct[0])
            require((dg,dy)==(g,y) and (gc,sc,rc)==tuple(DIRECTED_COUNTS.values()), 'Incomplete directed MMSE3 checks')
            result['rtl_directed'].append(dict(layout=label,active=active,passed=True,widths=[dg,dy],
                                              gram_checks=gc,sum_checks=sc,round_checks=rc))
            print('PASS MMSE3 widths',label,'reset',active,flush=True)
        for label,g,y in INVALID:
            _,rc=command([bindir/'vsim','-64','-c','-quiet','work.mmse3_width_tb',f'-gRESET_ACTIVE={active}',
                          f'-gGRAM_WIDTH={g}',f'-gSUM_WIDTH={y}','-do','run.do'],work,f'parameter_{label}_{active}','PARAMETER')
            result['rtl_parameters'].append(dict(layout=label,active=active,returncode=rc))
        for tag in TAGS:
            _,rc=command([bindir/'vsim','-64','-c','-quiet','work.mmse3_tb',f'-gRESET_ACTIVE={active}',
                          f'+VECTORS={base/"vectors"/CASES[0]}','+CHECK_MMSE3_WIDTHS','+INJECT_MMSE3='+tag,
                          '-do','run.do'],work,f'negative_{tag}_{active}',tag)
            result['rtl_negative'].append(dict(bench='stream',tag=tag,active=active,returncode=rc))
            _,rc=command([bindir/'vsim','-64','-c','-quiet','work.mmse3_width_tb',f'-gRESET_ACTIVE={active}',
                          '+INJECT_MMSE3='+tag,'-do','run.do'],work,f'negative_directed_{tag}_{active}',tag)
            result['rtl_negative'].append(dict(bench='directed',tag=tag,active=active,returncode=rc))
    frozen=base/'frozen';frozen.mkdir(exist_ok=True)
    for relative in ('rtl/common/mmse3.sv','rtl/tb/mmse3_tb.sv'):
        target=frozen/Path(relative).name
        target.write_bytes(subprocess.run(['git','show',BASELINE_REV+':'+relative],cwd=ROOT,check=True,capture_output=True).stdout)
        artifacts.append(target)
    old_work=compile_work('frozen_old',frozen/'mmse3.sv',frozen/'mmse3_tb.sv')
    new_work=compile_work('frozen_new',SOURCES[2],frozen/'mmse3_tb.sv')
    for case,active,scenario in product(CASES,(1,0),SCENARIOS):
        matches=[]
        for name,run_work in (('old',old_work),('new',new_work)):
            output,_=command([bindir/'vsim','-64','-c','-quiet','work.mmse3_tb',f'-gRESET_ACTIVE={active}',
                              f'+VECTORS={base/"vectors"/case}',*SCENARIOS[scenario],'-do','run.do'],run_work,f'{case}_{active}_{scenario}')
            require(len(re.findall(r'PASS MMSE3: (\d+) outputs, (\d+) cycles',output))==1, 'Missing or duplicate frozen summary')
            m=re.search(r'PASS MMSE3: (\d+) outputs, (\d+) cycles',output)
            require(m is not None,'Missing frozen scoreboard')
            matches.append(tuple(map(int,m.groups())))
        result['rtl_frozen'].append(dict(case=case,active=active,scenario=scenario,old_outputs=matches[0][0],new_outputs=matches[1][0],
                                        old_cycles=matches[0][1],new_cycles=matches[1][1]))
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/mmse3_width_sweep/results.json')
    args=parser.parse_args();args.output=args.output.resolve()
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report();check_acceptance(result)
        artifacts=verify_rtl(result,args.output.parent/'equivalence') if args.verify_rtl else []
        check_acceptance(result)
        write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),**result));raise
    print('PASS MMSE3 width study',flush=True)


if __name__=='__main__':main()
