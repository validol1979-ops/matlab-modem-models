#!/usr/bin/env python3
"""Единая команда регрессии с ненулевым кодом возврата при любом отказе."""
from pathlib import Path
import argparse
import importlib.util
import json
import subprocess
import sys
import time
import unittest
from generate_vectors import generate, ROOT
from regression_evidence import begin, finish, write_json, require_pass


def verified_suite_artifacts(data, root=ROOT):
    """Preserve each child suite's verified artifacts in the parent result."""
    records=data if isinstance(data,list) else [data]
    if not records:raise RuntimeError('Missing completed child regression evidence')
    artifacts=[]
    for record in records:
        require_pass(record,root)
        artifacts.extend(Path(root)/name for name in record.get('artifact_hashes',{}))
    return list(dict.fromkeys(artifacts))


def verified_bpsk_uvm_artifacts(data, root=ROOT):
    """Require both complete RTL pilots before accepting their child artifacts."""
    if not isinstance(data,dict) or data.get('pilot')!='both':
        raise RuntimeError('Both BPSK RX and TX UVM pilots are required')
    if data.get('rx_profile_selection')!='all':
        raise RuntimeError('All registered RX UVM profiles are required')
    records=data.get('records')
    if not isinstance(records,dict):raise RuntimeError('Missing BPSK UVM records')
    for profile,prefix,scenarios in (
            ('bpsk','',('stream','stalled','midreset','cfgreset')),
            ('bpsk_tx','tx_',('stream','gaps','stalled','midreset','outreset')),
            ('qpsk_diff','qpsk_diff_',('stream','stalled','midreset','cfgreset')),
            ('psk8_fb','psk8_fb_',('stream','stalled','midreset','cfgreset'))):
        for scenario in scenarios:
            for active in (1,0):
                record=records.get(f'{prefix}{scenario}_reset_{active}')
                if (not isinstance(record,dict) or record.get('profile')!=profile
                        or record.get('scenario')!=scenario
                        or type(record.get('reset_active')) is not int
                        or record['reset_active']!=active):
                    raise RuntimeError('Incomplete BPSK UVM scenario coverage')
    for prefix,controls in (
            ('',{'numeric':'NUMERIC','ser':'SER','valid_x':'PROTOCOL','ready_x':'PROTOCOL'}),
            ('tx_',{'numeric':'NUMERIC','s_valid_x':'PROTOCOL','s_ready_x':'PROTOCOL',
                    'm_valid_x':'PROTOCOL','m_ready_x':'PROTOCOL','data_x':'NUMERIC','held_data':'STALL'}),
            ('qpsk_diff_',{'numeric':'NUMERIC','ser':'SER','label_high_bit':'NUMERIC','valid_x':'PROTOCOL',
                           'ready_x':'PROTOCOL','gain_ready_x':'PROTOCOL','warm_ser':'SER'}),
            ('psk8_fb_',{'numeric':'NUMERIC','ser':'SER','label_high_bit':'NUMERIC','valid_x':'PROTOCOL',
                        'ready_x':'PROTOCOL','warm_ser':'SER'})):
        for name,tag in controls.items():
            for active in (1,0):
                record=records.get(f'{prefix}negative_{name}_reset_{active}')
                if (not isinstance(record,dict) or record.get('detected_tag')!=tag
                        or type(record.get('returncode')) is not int or record['returncode']==0):
                    raise RuntimeError('Incomplete BPSK UVM negative controls')
    if not data.get('artifact_hashes'):raise RuntimeError('Missing BPSK UVM artifacts')
    return verified_suite_artifacts(data,root)


def python_tests(configs):
    suite=unittest.TestSuite()
    files=[ROOT/'tests'/'test_primitives.py', ROOT/'tests'/'test_regression_guards.py', ROOT/'tests'/'test_fixed_point.py', ROOT/'tests'/'test_rtl_tools.py', ROOT/'tests'/'test_bpsk_fixed.py', ROOT/'tests'/'test_psk_fixed.py', ROOT/'tests'/'test_mrc_fixed.py', ROOT/'tests'/'test_cpm_fixed.py', ROOT/'tests'/'test_oqpsk_fixed.py', ROOT/'tests'/'test_fft_fixed.py', ROOT/'tests'/'test_ofdm_fixed.py', ROOT/'tests'/'test_stft_fixed.py', ROOT/'tests'/'test_pfb_fixed.py', ROOT/'tests'/'test_fir_fixed.py', ROOT/'tests'/'test_oset_fixed.py', ROOT/'tests'/'test_fsk_fixed.py', ROOT/'tests'/'test_beam_fixed.py', ROOT/'tests'/'test_sync_fixed.py', ROOT/'tests'/'test_lms_fixed.py', ROOT/'tests'/'test_ldpc_fixed.py', ROOT/'tests'/'test_mmse_fixed.py', ROOT/'tests'/'test_rls_fixed.py', ROOT/'tests'/'test_omlsa_fixed.py']+[p.parent/'tests'/'test_modem.py' for p in configs]
    files.extend(ROOT/'tests'/name for name in ('test_questa_symlink.py',
                 'test_sync_slip_evidence.py', 'test_sync_precision.py',
                 'test_costas_acquisition.py', 'test_sync_disturbance.py',
                 'test_sync_grid_evidence.py', 'test_timing_precision.py',
                 'test_psk_precision.py', 'test_mmse3_fixed.py',
                 'test_cpm_precision.py','test_oqpsk_mrc_precision.py',
                 'test_fft_fir_precision.py','test_coverage_report.py','test_stream_rates.py',
                 'test_bpsk_ser_evidence.py','test_fft_width_sweep.py',
                 'test_adaptive_precision.py','test_suite_evidence.py',
                 'test_bpsk_uvm_evidence.py','test_linear_precision.py',
                 'test_sync_adaptive_rates.py','test_state_precision.py',
                 'test_ldpc_precision.py','test_spectral_precision.py','test_uvm_pilot_coverage.py',
                 'test_mmse3_rates.py'))
    for index,path in enumerate(files):
        spec=importlib.util.spec_from_file_location(f'modem_test_{index}',path)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful(): raise RuntimeError('Python regression failed')
    return result.testsRun


def octave_tests(configs,cross,output):
    script=[f"addpath('{str(ROOT/'common'/'octave').replace(chr(39),chr(39)*2)}');"]
    for config in configs:
        if cross: generate(config)
        config_text=str(config).replace("'","''")
        script.append(f"cfg=jsondecode(fileread('{config_text}')); modem_test(cfg);")
        if cross:
            directory=str(ROOT/'build'/'vectors'/config.parent.name).replace("'","''")
            script.append(f"modem_cross_test(cfg,'{directory}');")
    path=output/'octave_regression.m'; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(script)+'\n')
    result=subprocess.run(['octave-cli','--quiet',str(path)],capture_output=True,text=True)
    (output/'octave.log').write_text(result.stdout+result.stderr)
    print(result.stdout,end='')
    if result.returncode:
        print(result.stderr); raise RuntimeError('Octave regression failed')
    return len(configs)


def main():
    if not __debug__: raise RuntimeError("Run verification without Python optimization (-O)")
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite',choices=['python','octave','cross','hdl','all','rtl'],default='all')
    parser.add_argument('--modem')
    args=parser.parse_args()
    if args.suite=='rtl':
        if args.modem:parser.error('--modem is not supported by the RTL infrastructure suite')
        evidence=begin();target=ROOT/'build/rtl/rtl_results.json'
        write_json(target,dict(evidence,status='RUNNING'))
        subprocess.run([sys.executable,str(ROOT/'tools/run_rtl.py'),'--suite','all'],check=True)
        subprocess.run([sys.executable,str(ROOT/'tools/run_bpsk.py'),'--suite','all'],check=True)
        subprocess.run([sys.executable,str(ROOT/'tools/run_rtl_synth.py')],check=True)
        inputs=[ROOT/'build/rtl/all_results.json',ROOT/'build/rtl/bpsk/all_results.json',ROOT/'build/rtl/synth/results.json']
        write_json(target,dict(status='PASS',scope='Common primitives and BPSK pilot, including both vendor implementations',**finish(evidence,inputs)))
        return
    configs=[ROOT/'modems'/args.modem/'config.json'] if args.modem else sorted((ROOT/'modems').glob('*/config.json'))
    if args.modem and (Path(args.modem).name!=args.modem or not configs[0].is_file()): parser.error('Unknown modem name')
    output=ROOT/'build'/'single'/args.modem if args.modem else ROOT/'build'
    output.mkdir(parents=True,exist_ok=True)
    evidence=begin()
    targets=[args.suite]+(['python','cross','hdl'] if args.suite=='all' else [])
    for suite in targets: write_json(output/f'{suite}_results.json',{'status':'RUNNING',**evidence})
    summary=dict(suite=args.suite,modems=len(configs),model_names=[p.parent.name for p in configs]); start=time.monotonic()
    if args.suite in ('python','all'):
        summary['python_tests']=python_tests(configs)
        if not args.modem:
            summary['precision_results']={}
            for name in ('psk_precision','cpm_precision','oqpsk_mrc_precision','fft_fir_precision',
                         'adaptive_precision','linear_precision','state_precision',
                         'ldpc_precision','spectral_precision'):
                log=output/f'logs/{name}.log';log.parent.mkdir(parents=True,exist_ok=True)
                result=subprocess.run([sys.executable,str(ROOT/f'tools/{name}.py')],capture_output=True,text=True)
                log.write_text(result.stdout+result.stderr)
                if result.returncode:raise RuntimeError(f'{name} failed: {log}')
                report=ROOT/f'build/rtl/{name}/results.json'
                require_pass(json.loads(report.read_text()))
                summary['precision_results'][name]=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
    if args.suite in ('octave','cross','all'): summary['octave_modems']=octave_tests(configs,args.suite!='octave',output/'logs'/('cross' if args.suite=='all' else args.suite))
    if args.suite in ('octave','cross','all'):
        summary['octave_log']=str((output/'logs'/('cross' if args.suite=='all' else args.suite)/'octave.log').relative_to(ROOT))
    child_artifacts=[]
    if args.suite in ('hdl','all'):
        command=[str(ROOT/'tools'/'run_questa.sh')]
        command+=['--modem',args.modem] if args.modem else ['--all']
        subprocess.run(command,check=True)
        hdl_output=ROOT/'build/questa/single'/args.modem if args.modem else ROOT/'build/questa'
        summary['hdl']=json.loads((hdl_output/'results.json').read_text())
        child_artifacts.extend([hdl_output/'results.json',*verified_suite_artifacts(summary['hdl'])])
        if not args.modem:
            log=output/'logs/bpsk_uvm.log';log.parent.mkdir(parents=True,exist_ok=True)
            result=subprocess.run([sys.executable,str(ROOT/'tools/run_bpsk_uvm.py'),'--suite','all'],
                                  capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'BPSK RTL UVM pilot failed: {log}')
            report=ROOT/'build/rtl/bpsk_uvm/all_results.json'
            pilot=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_bpsk_uvm_artifacts(pilot)])
            summary['rtl_uvm_pilot']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
    if args.suite=='all' and not args.modem:
        # Полный запуск включает и отдельные алгоритмы из нового каталога типов.
        subprocess.run([sys.executable,str(ROOT/'tools/run_research.py'),'--suite','all'],check=True)
        summary['typed_algorithms']=json.loads((ROOT/'build/typed/all_results.json').read_text())
        child_artifacts.extend([ROOT/'build/typed/all_results.json',*verified_suite_artifacts(summary['typed_algorithms'])])
        subprocess.run([sys.executable,str(ROOT/'tools/check_contracts.py'),'--suite','all'],check=True)
        summary['input_contracts']=json.loads((ROOT/'build/contracts/all_results.json').read_text())
        child_artifacts.extend([ROOT/'build/contracts/all_results.json',*verified_suite_artifacts(summary['input_contracts'])])
    summary.update(status='PASS',elapsed_seconds=round(time.monotonic()-start,2))
    artifacts=child_artifacts+([ROOT/summary['octave_log']] if 'octave_log' in summary else [])
    for measurement in summary.get('precision_results',{}).values():
        artifacts.extend(ROOT/measurement[name] for name in ('result','log'))
    summary.update(finish(evidence,artifacts))
    for suite in targets: write_json(output/f'{suite}_results.json',dict(summary,suite=suite))
    print(json.dumps({k:v for k,v in summary.items() if k not in ('hdl','source_hashes','artifact_hashes','typed_algorithms','input_contracts')},indent=2))


if __name__=='__main__': main()
