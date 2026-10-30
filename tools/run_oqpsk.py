#!/usr/bin/env python3
"""Integer OQPSK reference, strict lint, Questa numeric scoreboard (oqpsk_tx, oqpsk_rx)."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths
from run_rtl import execute,SOURCES
from oqpsk_cases import vectors,delay_vectors,save,o

PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
PASS=r'PASS OQPSK: (\d+) symbols, (\d+) acquisitions, (\d+) tx samples'
BOUNDS=r'PASS BOUNDS OQPSK: '+r' '.join([r'(\d+)']*12)
BOUND_FIELDS=('tx_actions','capture_actions','reader_requests','acquisition_accesses','costas_accesses',
              'sample_bank_accesses','tap_masks','tail_reads','zero_substituted_taps','reader_peak_inflight','symbol_peak_inflight','tx_simultaneous')
FEEDBACK=r'PASS FEEDBACK OQPSK: '+r' '.join([r'(\d+)']*5)
FEEDBACK_FIELDS=('delay_symbols','delayed_errors','cold_symbols','latency_min_ce','latency_max_ce')
BOUND_SCOPE='Selected active TX buffer transitions, RX capture/sample RAM ports, cubic present/zero masks, acquisition lag and training indices, reader/symbol reservations and Costas/error ring tags.'



def zero_energy_vectors(folder):
    # Retain a normal TX fixture; RX sees a distinct all-zero legal sample frame.
    # This is bypass/zero-vector arithmetic evidence, not a payload SER experiment.
    report=vectors(folder,frames=1,count=256,seed=23,loopback=True,tracking=False)
    preamble=[int(line) for line in (folder/'preamble.txt').read_text().splitlines()[1:]]
    wave=[(0,0)]*(256*8);result=o.receive(wave,preamble,256);acq=result['acquisition']
    save(folder/'rx_wave.txt',[(re,im,int(k==len(wave)-1))for k,(re,im)in enumerate(wave)])
    save(folder/'rx_out.txt',[(int(re),int(im),int(result['data'][k]),int(k==255))for k,(re,im)in enumerate(result['values'])])
    save(folder/'rx_acquire.txt',[(acq['delay'],acq['frequency'],acq['phase'])])
    report.update(samples=len(wave),payload_errors=None,scope='Directed zero-energy RX fraction bypass and zero-vector CORDIC phase0; no SER/EVM claim.')
    return report

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');parser.add_argument('--output',type=Path,help='new isolated output directory');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    output=args.output.resolve() if args.output else ROOT/'build/rtl/oqpsk';output.mkdir(parents=True,exist_ok=args.output is None)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        log=output/'test_oqpsk_fixed.log';execute([sys.executable,ROOT/'tests/test_oqpsk_fixed.py'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
    if args.suite in ('all','lint'):
        for top in ('oqpsk_tx','oqpsk_rx'):
            log=output/f'lint_{top}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module',top,f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top}')
            artifacts.append(log)
        records['lint']='PASS'
        for delay in (1,10,16):
            log=output/f'lint_oqpsk_rx_delay_{delay}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module','oqpsk_rx',f'-GLOOP_DELAY={delay}',f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: OQPSK delay {delay}')
            artifacts.append(log)
    if args.suite in ('all','hdl'):
        base=output/'vectors'
        reports={'stream':vectors(base),'loopback':vectors(base/'loopback',frames=3,loopback=True),
                 'minimum':vectors(base/'minimum',frames=1,count=192,seed=23),
                 'maximum':vectors(base/'maximum',frames=2,count=2048,seed=23),
                 'tailcut':vectors(base/'tailcut',frames=1,count=256,seed=23,tailcut=True)}
        for delay in (8,10):reports[f'delay_{delay}']=delay_vectors(base/f'delay_{delay}',delay)
        for delay in (1,16):reports[f'delay_{delay}']=delay_vectors(base/f'delay_{delay}',delay,frames=1)
        for name in ('preamble','tx_symbols','tx_out','rx_wave','rx_acquire'):
            if (base/'delay_8'/(name+'.txt')).read_bytes()!=(base/'delay_10'/(name+'.txt')).read_bytes():
                raise RuntimeError('Delay experiment changed input/truth/acquisition: '+name)
        paired={delay:{name:sum(values) for name,values in reports[f'delay_{delay}']['payload_errors'].items()} for delay in (8,10)}
        if paired[8]['phase_noise']>=paired[10]['phase_noise'] or paired[8]['threshold']>paired[10]['threshold']+6:
            raise RuntimeError(f'OQPSK shorter-delay quality regression: {paired}')
        records['delay_comparison']=dict(errors=paired,payload_symbols_per_scenario=reports['delay_8']['payload_symbols_per_scenario'],
                                        identical_inputs_and_truth=True,scope='Six paired frames per channel with a shared preamble; exact RTL outputs checked at delays 8 and 10.')
        artifacts.extend([*(output/'vectors').rglob('*.txt'), *(output/'vectors').rglob('tracking.json')])
        zero_folder=output/'vectors_zero_energy';zero_folder.mkdir(parents=True,exist_ok=True)
        reports['zero_energy']=zero_energy_vectors(zero_folder)
        artifacts.extend(zero_folder.glob('*.txt'))
        bindir,_=questa_paths()
        for active in (1,0):
            work=output/f'reset_{active}';work.mkdir(exist_ok=True)
            if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
            execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/bpsk_fir_bounds_check.sv',ROOT/'rtl/tb/bpsk_cordic_bounds_check.sv',ROOT/'rtl/tb/bpsk_divide_bounds_check.sv',ROOT/'rtl/tb/oqpsk_tb.sv'],work,work/'compile.log')
            artifacts.append(work/'compile.log')
            common=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.oqpsk_tb',f'-gRESET_ACTIVE={active}',f'-gTABLE_DIR={PILOT/"tables"}']
            bounds_records={};fir_history_records={};nested_records={};feedback_records={}
            for scenario,folder,options,count in [('stream',base,[],768),('stalled',base,['+STALL_INPUT'],768),
                                                  ('loopback',base/'loopback',['+STALL_INPUT'],768),
                                                  ('backpressure',base,['+STALL_INPUT','+STALL_OUTPUT'],768),
                                                  ('midreset',base,['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT'],768),
                                                  ('outreset',base,['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'],768),
                                                  ('cfgreset',base,['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'],768),
                                                  ('minimum',base/'minimum',[],192),('maximum',base/'maximum',[],2048),
                                                  ('tailcut',base/'tailcut',[],256),
                                                  ('zero_energy',zero_folder,[],256),
                                                  ('delay_8',base/'delay_8',[],768),
                                                  ('delay_8_stalled',base/'delay_8',['+STALL_INPUT','+STALL_OUTPUT'],768),
                                                  ('delay_10',base/'delay_10',['-gLOOP_DELAY=10'],768),
                                                  ('delay_10_stalled',base/'delay_10',['-gLOOP_DELAY=10','+STALL_INPUT','+STALL_OUTPUT'],768),
                                                  ('delay_1',base/'delay_1',['-gLOOP_DELAY=1','+STALL_INPUT','+STALL_OUTPUT'],768),
                                                  ('delay_16',base/'delay_16',['-gLOOP_DELAY=16','+STALL_INPUT','+STALL_OUTPUT'],768)]:
                report=reports['stream' if scenario in ('stalled','backpressure','midreset','outreset','cfgreset') else scenario.removesuffix('_stalled')];log=work/f'{scenario}.log'
                text=execute([*common,f'-gSYMBOLS={count}',f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                match=re.search(PASS,text)
                if not match or tuple(map(int,match.groups()))!=(report['symbols'],report['frames'],report['tx_samples']) or re.search(r'\*\* (?:Error|Fatal)',text):
                    raise RuntimeError(text[-6000:])
                bounds=re.search(BOUNDS,text)
                if not bounds or any(int(v)<1 for v in bounds.groups()[:7]):
                    raise RuntimeError('Missing/unexercised OQPSK active bounds evidence')
                bounds_records[scenario]=dict(zip(BOUND_FIELDS,map(int,bounds.groups())))
                feedback=re.search(FEEDBACK,text)
                delay=report.get('loop_delay',o.LOOP_DELAY)
                if (not feedback or tuple(map(int,feedback.groups()[:3]))!=(delay,report['frames']*(count-delay),report['frames']*delay)
                        or int(feedback[4])<1 or feedback[4]!=feedback[5]):
                    raise RuntimeError('Missing/incomplete OQPSK exact-age feedback evidence: '+scenario)
                feedback_records[scenario]=dict(zip(FEEDBACK_FIELDS,map(int,feedback.groups())))
                lifetime=re.search(PASS+r', (\d+) cycles',text)
                if not lifetime:raise RuntimeError('Missing measured OQPSK testbench lifetime')
                feedback_records[scenario]['testbench_cycles']=int(lifetime[4])
                fir_history_records[scenario]={}
                for name in ('OQTX','OQRX'):
                    observed=re.search(r'PASS FIR HISTORY '+name+r': (\d+) (\d+) (\d+) (\d+) (\d+)',text)
                    if not observed or any(int(observed[i])<1 for i in (1,2,3,5)):
                        raise RuntimeError(f'Unexercised FIR history observer: {name}/{scenario}')
                    fir_history_records[scenario][name]=dict(zip(('valid','history_words','firsts','pauses','active_last'),map(int,observed.groups())))
                if scenario=='backpressure' and fir_history_records[scenario]['OQTX']['pauses']<1:
                    raise RuntimeError('TX FIR enabled-clock pause not exercised')
                nested_records[scenario]={}
                for label in ('ACQ','LOOP'):
                    observed=re.search(r'PASS NESTED CORDIC '+label+r': (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+)',text)
                    if not observed or min(map(int,observed.groups()[:4]))<1 or observed[3]!=observed[4]:
                        raise RuntimeError('Incomplete nested CORDIC lifetime: '+label)
                    nested_records[scenario][label]=dict(zip(('valid_checks','active_stages','requests','responses','zero_vectors','pause_cycles','peak_live'),map(int,observed.groups())))
                observed=re.search(r'PASS NESTED DIVIDER: (\d+) (\d+) (\d+) (\d+) (\d+)',text)
                if not observed or int(observed[1])<1 or int(observed[1])!=int(observed[2]) or int(observed[3])!=32*int(observed[1]) or int(observed[4])!=2*int(observed[1]):
                    raise RuntimeError('Incomplete nested divider request/progress')
                nested_records[scenario]['divider']=dict(zip(('requests','responses','iterations','terminal_checks','ignored_starts'),map(int,observed.groups())))
                bypass=re.search(r'PASS NESTED FRACTION BYPASS: (\d+)',text)
                if not bypass:raise RuntimeError('Missing measured fraction bypass')
                nested_records[scenario]['nonpositive_fraction_bypasses']=int(bypass[1])
                if scenario=='zero_energy' and (int(bypass[1])<1 or any(nested_records[scenario][label]['zero_vectors']<1 for label in ('ACQ','LOOP'))):
                    raise RuntimeError('Directed zero-energy bypass/phase0 not exercised')
                if scenario=='tailcut' and bounds_records[scenario]['zero_substituted_taps']<1:
                    raise RuntimeError('Tailcut OQPSK failed to exercise real zero-substituted taps')
                artifacts.append(log)
            negative_do=work/'negative.do'
            negative_do.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
            artifacts.append(negative_do)
            for name,flag,tag in (('negative','+INJECT_MISMATCH','NUMERIC'),('negative_symbol','+INJECT_SYMBOL','NUMERIC'),
                                  ('negative_bounds','+INJECT_BOUND_MISMATCH','BOUNDS'),
                                  ('negative_feedback','+INJECT_FEEDBACK_VALUE','FEEDBACK'),
                                  ('negative_delay_0','-gLOOP_DELAY=0','PARAMETER'),
                                  ('negative_delay_17','-gLOOP_DELAY=17','PARAMETER'),
                                  ('negative_fir_index','+INJECT_FIR_INDEX','FIR_BOUNDS'),
                                  ('negative_fir_valid','+INJECT_FIR_VALID','FIR_BOUNDS'),
                                  ('negative_cordic_stage','+INJECT_CORDIC_STAGE','NESTED_BOUNDS'),
                                  ('negative_cordic_tag','+INJECT_CORDIC_TAG','NESTED_BOUNDS'),
                                  ('negative_cordic_hold','+INJECT_CORDIC_HOLD','NESTED_BOUNDS'),
                                  ('negative_divider_step','+INJECT_DIVIDER_STEP','NESTED_BOUNDS'),
                                  ('negative_divisor_zero','+INJECT_DIVISOR_ZERO','NESTED_BOUNDS')):
                options=['+STALL_OUTPUT'] if name in ('negative_fir_valid','negative_cordic_hold') else []
                bad=subprocess.run([str(x) for x in [*common,f'-gSYMBOLS=768',f'+VECTORS={base}',flag,*options,'-do',negative_do.name]],cwd=work,capture_output=True,text=True,timeout=90)
                negative=bad.stdout+bad.stderr;(work/f'{name}.log').write_text(negative)
                if bad.returncode==0 or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',negative) or re.search(PASS,negative) or (tag=='FIR_BOUNDS' and 'PASS FIR HISTORY' in negative):raise RuntimeError(f'{name} control not detected')
                artifacts.append(work/f'{name}.log')
            zero_bad=subprocess.run([str(x) for x in [*common,'-gSYMBOLS=256',f'+VECTORS={base/"tailcut"}',
                                                      '+INJECT_ZERO_DATA','-do',negative_do.name]],cwd=work,capture_output=True,text=True,timeout=90)
            negative=zero_bad.stdout+zero_bad.stderr;(work/'negative_zero.log').write_text(negative)
            if (zero_bad.returncode==0 or not re.search(r'\*\* Fatal:.*\[BOUNDS\].*out-of-frame tap',negative)
                    or re.search(PASS,negative)):
                raise RuntimeError('OQPSK wrong zero-substitution data control not detected')
            artifacts.append(work/'negative_zero.log')
            records[f'reset_{active}']=dict(reports=reports,negative_control='PASS',negative_bounds='PASS',
                                           negative_zero='PASS',negative_feedback='PASS',negative_delay='PASS',feedback=feedback_records,
                                           bounds_scope=BOUND_SCOPE,bounds=bounds_records,
                                           nested=nested_records,nested_scope='Static21CE-stage CORDIC validity/tag/zero lifetime and64iteration divider request/remainder/round/sign tracking; no dynamic RAM/ROM claims.',fir_history=fir_history_records,fir_history_scope='Static register histories and eight enabled-clock valid/last stages; CE/sample-derived live data comparisons. No dynamic RAM/ROM accesses in bpsk_fir.')
            print(f'PASS OQPSK reset={active}',flush=True)
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS OQPSK {args.suite}')

if __name__=='__main__':main()
