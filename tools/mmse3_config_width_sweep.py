#!/usr/bin/env python3
"""MMSE3 configuration-expression proof, native observations and frozen equivalence."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from itertools import product
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from regression_evidence import ROOT, begin, finish, write_json, require_unoptimized, questa_paths
from mmse3_cases import vectors, CASES as NATIVE_CASES
from spectral_evidence import check_observers
sys.path.insert(0, str(ROOT/'common/python'))
import mmse3_config_widths as widths

CASES = (*NATIVE_CASES, 'gram_peak')
LAYOUTS = (('selected',81,126,104), ('old_all',84,128,106),
           ('old_adj',84,126,104), ('old_det',81,128,104), ('old_m',81,126,106))
INVALID = (('adj_low',80,126,104), ('adj_high',85,126,104),
           ('det_low',81,125,104), ('det_high',81,129,104),
           ('m_low',81,126,103), ('m_high',81,126,107))
SCENARIOS = {'stream':[], 'stalled':['+STALL_INPUT','+STALL_OUTPUT'],
             'midreset':['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT'],
             'outreset':['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'],
             'cfgreset':['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT']}
TAGS = ('ADJ','DET','M')
BANK_NAMES = ('adj_re','adj_im','det_re','det_im','m_re','m_im')
DIRECTED_COUNTS = dict(adj_checks=4608, det_checks=8192, m_checks=73728)
DIRECTED_BANK_COUNTS = (2304,2304,4096,4096,36864,36864)
BASELINE_REV = 'configuration-start-20261026'
BASELINE = ROOT/'build/acceptance_20261026_mmse_configuration/baseline'
BASELINE_HASHES = {
    'rtl/common/mmse3.sv':'dca3dbb92078b711e8e09c402d5680d85938821a64cc04ddcdfbac1e0cdfecc1',
    'rtl/tb/mmse3_tb.sv':'ddf2defd3279277cbf068253f4e6ae731b17f08096010c40d2d357cbba4f35ef',
}
SOURCES = [ROOT/'rtl/common/fxp_divide_seq.sv', ROOT/'rtl/common/norm_reciprocal.sv', ROOT/'rtl/common/mmse3.sv']
SECTIONS = ('rtl_equivalence','rtl_frozen','rtl_parameters','rtl_directed','rtl_negative','rtl_lint')
PASS = r'PASS MMSE3: (\d+) outputs, (\d+) cycles'
MAX_JOBS = 8


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def exact(a, b):
    """Numeric evidence must preserve integers: Python's True == 1 is too weak."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(exact(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(exact(x,y) for x,y in zip(a,b))
    return a == b


def rows(path):
    return [tuple(map(int,line.split())) for line in path.read_text().splitlines() if line.strip()]


def fixture(index, case, folder):
    data = vectors(folder, case, seed=53+index)
    cfg = rows(folder/'cfg.txt')
    trace = widths.trace(cfg[:9], cfg[9][0])
    # Compare the complete coefficient derivation against the established model,
    # retaining independent raw G/A/D/M arithmetic in mmse3_config_widths.
    import mmse3_fixed as fixed
    from beam_fixed import reciprocal
    r, z = reciprocal(trace['det'][0])
    derived = [tuple(fixed._round_shift(v*r,z-39) for v in pair) for pair in trace['m']]
    require(derived == rows(folder/'weights.txt'), 'Independent MMSE3 configuration disagrees with fixed model')
    return dict(case=case, outputs=data['outputs'], banks=widths.banks(trace),
                vector_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(folder.iterdir()) if p.is_file()})


def report():
    with tempfile.TemporaryDirectory() as tmp:
        records = [fixture(i,case,Path(tmp)/case) for i,case in enumerate(CASES)]
    return dict(scope='MMSE3 adjugate/determinant/M expression widths over full independent stored G40/A84/H18 codes; storage and wround unchanged; synthesis paused',
                bounds=widths.layout(), records=records, baseline_revision=BASELINE_REV,
                baseline_hashes=BASELINE_HASHES.copy(), rtl_verified=False,
                **{section:[] for section in SECTIONS})


def coverage(records, keys, expected):
    require(type(records) is list, 'Invalid MMSE3 configuration coverage collection')
    for r in records:
        require(type(r) is dict and all(type(r[k]) is (int if k=='active' else str) for k in keys),
                'Invalid MMSE3 configuration coverage types')
    require(len(records)==len(expected) and {tuple(r[k] for k in keys) for r in records}==expected,
            'Incomplete or duplicate MMSE3 configuration coverage: '+','.join(keys))


def configurations(scenario):
    return 2 if scenario in ('midreset','outreset') else 1


def epochs(scenario):
    return 2 if scenario in ('midreset','outreset','cfgreset') else 1


def scaled_banks(source, factor):
    return [dict(b, count=b['count']*factor) for b in source['banks']]


def directed_banks():
    bounds = widths.layout()
    return [dict(name=name, count=count,
                 min=bounds[name.split('_')[0]][axis]['minimum'],
                 max=bounds[name.split('_')[0]][axis]['maximum'])
            for name,count,axis in zip(BANK_NAMES,DIRECTED_BANK_COUNTS,('real','imag')*3)]


def check_counts(r):
    counts = [b['count'] for b in r['banks']]
    expected = dict(adj_checks=sum(counts[:2]), det_checks=sum(counts[2:4]),
                    m_checks=sum(counts[4:]), total_checks=sum(counts))
    require(all(type(r.get(k)) is int and r[k]==v for k,v in expected.items()),
            'MMSE3 configuration observation count mismatch')


def check_acceptance(result):
    model = report()
    require(all(exact(result[k],model[k]) for k in ('scope','bounds','records','baseline_revision','baseline_hashes')),
            'Changed MMSE3 configuration model evidence')
    require(type(result['rtl_verified']) is bool, 'Invalid MMSE3 configuration verification flag')
    if not result['rtl_verified']:
        require(all(exact(result[k],[]) for k in SECTIONS), 'Unverified MMSE3 configuration observations')
        return
    names = [v[0] for v in LAYOUTS]
    coverage(result['rtl_equivalence'], ('case','layout','active','scenario'),
             set(product(CASES,names,(1,0),SCENARIOS)))
    source_by_case = {r['case']:r for r in model['records']}
    for r in result['rtl_equivalence']:
        source = source_by_case[r['case']]
        target = next(v for v in LAYOUTS if v[0]==r['layout'])
        require(exact(r['widths'],list(target[1:])) and type(r['outputs']) is int and
                r['outputs']==source['outputs'] and type(r['cycles']) is int and r['cycles']>0 and
                r['observers_verified'] is True, 'Missing MMSE3 configuration numeric evidence')
        require(type(r['epochs']) is int and r['epochs']==epochs(r['scenario']) and
                type(r['configs']) is int and r['configs']==configurations(r['scenario']),
                'Missing cumulative MMSE3 reset/configuration evidence')
        require(exact(r['banks'],scaled_banks(source,r['configs'])), 'Changed MMSE3 configuration raw banks')
        check_counts(r)
    timings = {}
    for r in result['rtl_equivalence']:
        key = r['case'],r['active'],r['scenario']
        require(key not in timings or timings[key]==r['cycles'], 'MMSE3 configuration layouts changed timing')
        timings[key] = r['cycles']
    coverage(result['rtl_frozen'], ('case','active','scenario'), set(product(CASES,(1,0),SCENARIOS)))
    for r in result['rtl_frozen']:
        require(all(type(r[k]) is int for k in ('old_cycles','new_cycles','old_outputs','new_outputs')) and
                r['old_cycles']>0 and r['old_cycles']==r['new_cycles'] and
                r['old_outputs']==r['new_outputs']==source_by_case[r['case']]['outputs'], 'Frozen MMSE3 configuration mismatch')
    coverage(result['rtl_directed'], ('layout','active'), set(product(names,(1,0))))
    for r in result['rtl_directed']:
        target = next(v for v in LAYOUTS if v[0]==r['layout'])
        require(r['passed'] is True and exact(r['widths'],list(target[1:])) and
                exact(r['banks'],directed_banks()) and type(r['epochs']) is int and r['epochs']==1 and
                type(r['configs']) is int and r['configs']==1 and
                all(type(r[k]) is int and r[k]==v for k,v in DIRECTED_COUNTS.items()),
                'Missing MMSE3 full-domain directed evidence')
        check_counts(r)
    coverage(result['rtl_parameters'], ('layout','active'), set(product([v[0] for v in INVALID],(1,0))))
    coverage(result['rtl_negative'], ('bench','tag','active'), set(product(('stream','directed'),TAGS,(1,0))))
    for key in ('rtl_parameters','rtl_negative'):
        require(all(type(r['returncode']) is int and r['returncode']==13 for r in result[key]), 'Missing MMSE3 configuration rejection exit code')
    coverage(result['rtl_lint'], ('layout',), {(v[0],) for v in LAYOUTS})
    require(all(type(r['warnings']) is int and r['warnings']==0 for r in result['rtl_lint']), 'MMSE3 configuration lint warnings')


def parse_banks(text, directed=False):
    marker = 'MMSE3 CONFIG '+('DIRECTED ' if directed else '')+'BANK'
    found = re.findall(marker+r' bank=(\d+) count=(\d+) min=(-?\d+) max=(-?\d+)',text)
    require(len(found)==6 and [int(v[0]) for v in found]==list(range(6)), 'Missing or duplicate MMSE3 configuration raw banks')
    return [dict(name=BANK_NAMES[int(i)], count=int(c), min=int(lo), max=int(hi)) for i,c,lo,hi in found]


def parse_raw(text):
    pattern = (r'PASS MMSE3 CONFIG ADJ_WIDTH=(\d+) DET_WIDTH=(\d+) M_WIDTH=(\d+) epochs=(\d+) '
               r'adj_re=(\d+) adj_im=(\d+) det_re=(\d+) det_im=(\d+) m_re=(\d+) m_im=(\d+) total=(\d+)')
    found = re.findall(pattern,text)
    require(len(found)==1, 'Missing or duplicate MMSE3 configuration raw summary')
    adj,det,m,epoch,*counts = map(int,found[0])
    banks = parse_banks(text)
    require(counts[:6]==[b['count'] for b in banks] and counts[6]==sum(counts[:6]), 'MMSE3 configuration summary/bank mismatch')
    return dict(widths=[adj,det,m], epochs=epoch, banks=banks,
                adj_checks=sum(counts[:2]), det_checks=sum(counts[2:4]),
                m_checks=sum(counts[4:6]), total_checks=counts[6])


def parse_directed(text):
    pattern = r'PASS MMSE3 CONFIG DIRECTED ADJ_WIDTH=(\d+) DET_WIDTH=(\d+) M_WIDTH=(\d+) adj=(\d+) det=(\d+) m=(\d+)'
    found = re.findall(pattern,text)
    require(len(found)==1, 'Missing or duplicate MMSE3 configuration directed summary')
    adj,det,m,ac,dc,mc = map(int,found[0])
    result = parse_raw(text)
    require(result['widths']==[adj,det,m] and [result[k] for k in DIRECTED_COUNTS]==[ac,dc,mc] and
            exact(result['banks'],parse_banks(text,True)), 'MMSE3 configuration directed observer mismatch')
    return dict(result, passed=True, configs=1)


def numeric(text):
    matches = re.findall(PASS,text)
    require(len(matches)==1, 'Missing or duplicate MMSE3 numeric summary')
    return tuple(map(int,matches[0]))


def verify_rtl(result, base, jobs=MAX_JOBS):
    require(type(jobs) is int and 1<=jobs<=MAX_JOBS, 'MMSE3 configuration --jobs must be 1..8')
    base = base.resolve()
    base.mkdir(parents=True,exist_ok=True)
    artifacts=[]
    bindir,_ = questa_paths()

    def command(args, work, name, tag=None, compiler=False):
        log = work/(name+'.log')
        proc = subprocess.run(list(map(str,args)),cwd=work,capture_output=True,text=True,timeout=300)
        output = proc.stdout+proc.stderr
        log.write_text(output)
        if tag:
            require(proc.returncode==13 and re.search(r'\*\* Fatal:.*\['+re.escape(tag)+r'\]',output) and
                    not re.search(PASS,output) and 'PASS MMSE3 CONFIG DIRECTED' not in output,
                    'MMSE3 configuration negative control missed: '+str(log)+'\n'+output[-2000:])
        else:
            warnings = re.findall(r'^.*\*\* Warning:.*$',output,re.MULTILINE)
            allowed = ('(vlog-13314)','(vlog-2244)','(vopt-13314)','(vopt-2244)') if compiler else ()
            require(proc.returncode==0 and not re.search(r'\*\* (?:Error|Fatal)|%Warning|Errors:\s*[1-9]',output) and
                    all(any(code in line for code in allowed) for line in warnings),
                    'MMSE3 configuration command failed: '+str(log)+'\n'+output[-4000:])
        return output,proc.returncode,log

    # Pin pre-edit DUT/TB identities; archived includes keep the frozen bench
    # independent of changes to current observer implementations.
    frozen = base/'baseline'
    for relative,expected in BASELINE_HASHES.items():
        source = BASELINE/relative
        require(source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest()==expected,
                'Missing or changed pinned MMSE3 baseline: '+str(source))
    baseline_files = [BASELINE/'rtl/common/mmse3.sv', *sorted((BASELINE/'rtl/tb').glob('mmse3*'))]
    manifest = {}
    for source in baseline_files:
        relative = source.relative_to(BASELINE)
        target = frozen/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        manifest[str(relative)] = hashlib.sha256(target.read_bytes()).hexdigest()
        artifacts.append(target)
    manifest_path = frozen/'manifest.json'
    write_json(manifest_path,manifest)
    artifacts.append(manifest_path)
    for i,case in enumerate(CASES):
        folder=base/'vectors'/case
        require(exact(fixture(i,case,folder),result['records'][i]), 'MMSE3 configuration vectors changed')
        artifacts.extend(p for p in folder.iterdir() if p.is_file())

    scripts = {}
    for name,extra in (('run',''),('negative','onbreak {quit -code 13}\n')):
        p = base/(name+'.do')
        p.write_text('onfinish stop\nonerror {quit -code 13}\n'+extra+'run -all\nquit -code 0\n')
        scripts[name] = p
        artifacts.append(p)

    def compile_library(name, dut, tb, includes, directed=False):
        work = base/name
        work.mkdir(exist_ok=True)
        if not (work/'work').is_dir():
            _,_,log = command([bindir/'vlib','work'],work,'vlib')
            artifacts.append(log)
        _,_,log = command([bindir/'vlog','-64','-sv',f'+incdir+{includes}',*SOURCES[:2],dut,
                           *[ROOT/'rtl/tb'/p for p in ('axis_check.sv','stream_cover.sv','sat_event_check.sv')],tb,
                           *([ROOT/'rtl/tb/mmse3_config_width_tb.sv'] if directed else [])],
                          work,'compile',compiler=True)
        artifacts.append(log)
        return work

    def optimise(work, bench, name, active, values=None):
        args = [bindir/'vopt','-64','work.'+bench,f'-gRESET_ACTIVE={active}']
        if values is not None:
            args += [f'-g{p}_WIDTH={v}' for p,v in zip(TAGS,values)]
        _,_,log = command([*args,'-o',name],work,'vopt_'+name,compiler=True)
        artifacts.append(log)

    current = compile_library('current',SOURCES[2],ROOT/'rtl/tb/mmse3_tb.sv',ROOT/'rtl/tb',True)
    for label,adj,det,m in LAYOUTS:
        _,_,log = command(['verilator','--lint-only','-Wall','--top-module','mmse3',
                           f'-GADJ_WIDTH={adj}',f'-GDET_WIDTH={det}',f'-GM_WIDTH={m}',*SOURCES],base,'lint_'+label)
        artifacts.append(log)
        result['rtl_lint'].append(dict(layout=label,warnings=0))
        for active,bench in product((1,0),('mmse3_tb','mmse3_config_width_tb')):
            optimise(current,bench,f'{bench}_{label}_{active}',active,(adj,det,m))
    # Guards execute at time zero; optimise each illegal layout separately so
    # even rejection jobs only read shared libraries during parallel simulation.
    for values,active in product(INVALID,(1,0)):
        label,*numbers = values
        optimise(current,'mmse3_config_width_tb',f'mmse3_config_width_tb_invalid_{label}_{active}',active,numbers)
    old = compile_library('frozen_old',frozen/'rtl/common/mmse3.sv',frozen/'rtl/tb/mmse3_tb.sv',frozen/'rtl/tb')
    new = compile_library('frozen_new',SOURCES[2],frozen/'rtl/tb/mmse3_tb.sv',frozen/'rtl/tb')
    for work in (old,new):
        for active in (1,0):
            optimise(work,'mmse3_tb',f'mmse3_tb_reset{active}',active)

    def simulate(library, top, name, flags=(), tag=None, generics=()):
        work = base/'runs'/name
        work.mkdir(parents=True,exist_ok=True)
        script = work/'simulation.do'
        shutil.copyfile(scripts['negative' if tag else 'run'],script)
        return command([bindir/'vsim','-64','-c','-quiet','-lib',library/'work',top,
                        *generics,*flags,'-do',script.name],work,'simulation',tag)

    def stream(job):
        case,label,active,scenario = job
        text,_,log = simulate(current,f'mmse3_tb_{label}_{active}',f'stream_{case}_{label}_{active}_{scenario}',
                              [f'+VECTORS={base/"vectors"/case}','+CHECK_MMSE3_CONFIG',*SCENARIOS[scenario]])
        outputs,cycles = numeric(text)
        check_observers(text,base/'vectors'/case,'mmse3')
        return dict(case=case,layout=label,active=active,scenario=scenario,outputs=outputs,cycles=cycles,
                    configs=configurations(scenario),observers_verified=True,**parse_raw(text)),[log]

    def directed(job):
        label,active = job
        text,_,log = simulate(current,f'mmse3_config_width_tb_{label}_{active}',f'directed_{label}_{active}',
                              ['+CHECK_MMSE3_CONFIG'])
        return dict(layout=label,active=active,**parse_directed(text)),[log]

    def invalid(job):
        values,active = job
        label = values[0]
        _,rc,log = simulate(current,f'mmse3_config_width_tb_invalid_{label}_{active}',
                            f'parameter_{label}_{active}',tag='PARAMETER')
        return dict(layout=label,active=active,returncode=rc),[log]

    def negative(job):
        bench,tag,active = job
        top = 'mmse3_tb' if bench=='stream' else 'mmse3_config_width_tb'
        flags = ['+CHECK_MMSE3_CONFIG','+INJECT_MMSE3_CONFIG='+tag]
        if bench=='stream':
            flags.append(f'+VECTORS={base/"vectors"/CASES[0]}')
        _,rc,log = simulate(current,f'{top}_selected_{active}',f'negative_{bench}_{tag}_{active}',flags,'MMSE3_CONFIG_'+tag)
        return dict(bench=bench,tag=tag,active=active,returncode=rc),[log]

    def frozen_pair(job):
        case,active,scenario = job
        matches=[]
        logs=[]
        for label,library in (('old',old),('new',new)):
            text,_,log = simulate(library,f'mmse3_tb_reset{active}',f'frozen_{label}_{case}_{active}_{scenario}',
                                  [f'+VECTORS={base/"vectors"/case}',*SCENARIOS[scenario]])
            matches.append(numeric(text))
            check_observers(text,base/'vectors'/case,'mmse3')
            logs.append(log)
        return dict(case=case,active=active,scenario=scenario,old_outputs=matches[0][0],new_outputs=matches[1][0],
                    old_cycles=matches[0][1],new_cycles=matches[1][1]),logs

    tasks = [('rtl_equivalence',stream,j) for j in product(CASES,[v[0] for v in LAYOUTS],(1,0),SCENARIOS)]
    tasks += [('rtl_directed',directed,j) for j in product([v[0] for v in LAYOUTS],(1,0))]
    tasks += [('rtl_parameters',invalid,j) for j in product(INVALID,(1,0))]
    tasks += [('rtl_negative',negative,j) for j in product(('stream','directed'),TAGS,(1,0))]
    tasks += [('rtl_frozen',frozen_pair,j) for j in product(CASES,(1,0),SCENARIOS)]

    def run_task(task):
        section,worker,job = task
        record,logs = worker(job)
        return section,record,[p for log in logs for p in (log,log.parent/'simulation.do')]

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for index,(section,record,logs) in enumerate(pool.map(run_task,tasks),1):
            result[section].append(record)
            artifacts.extend(logs)
            if index%50==0 or index==len(tasks):
                print(f'PASS MMSE3 configuration jobs {index}/{len(tasks)}',flush=True)
    result['rtl_verified'] = True
    return artifacts


def main():
    require_unoptimized()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true')
    parser.add_argument('--jobs',type=int,default=MAX_JOBS)
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/mmse3_config_width_sweep/results.json')
    args = parser.parse_args()
    require(1<=args.jobs<=MAX_JOBS, 'MMSE3 configuration --jobs must be 1..8')
    args.output = args.output.resolve()
    evidence = begin()
    write_json(args.output,dict(evidence,status='RUNNING'))
    result = {}
    try:
        result = report()
        check_acceptance(result)
        artifacts = verify_rtl(result,args.output.parent/'equivalence',args.jobs) if args.verify_rtl else []
        check_acceptance(result)
        write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),**result))
        raise
    print('PASS MMSE3 configuration width study',flush=True)


if __name__=='__main__':
    main()
