#!/usr/bin/env python3
"""Единая команда регрессии с ненулевым кодом возврата при любом отказе."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import subprocess
import sys
import time
import unittest
from generate_vectors import generate, ROOT
from regression_evidence import begin, finish, write_json, require_pass

ACTIVE_REPORTS=[]


def mark_failed_reports(reports,error):
    """Close this invocation's RUNNING records without retagging completed/newer runs."""
    for path,started in reports:
        try:
            if not Path(path).is_file():continue
            data=json.loads(Path(path).read_text())
            if data.get('status')!='RUNNING' or data.get('started_at_utc')!=started:continue
            data.update(status='FAIL',error=f'{type(error).__name__}: {error}',
                        failed_at_utc=datetime.now(timezone.utc).isoformat())
            write_json(path,data)
        except (OSError,ValueError) as secondary:
            print(f'Could not record regression failure in {path}: {secondary}',file=sys.stderr)


def verified_suite_artifacts(data, root=ROOT):
    """Preserve each child suite's verified artifacts in the parent result."""
    records=data if isinstance(data,list) else [data]
    if not records:raise RuntimeError('Missing completed child regression evidence')
    artifacts=[]
    for record in records:
        require_pass(record,root)
        artifacts.extend(Path(root)/name for name in record.get('artifact_hashes',{}))
    return list(dict.fromkeys(artifacts))


# Every non-BPSK profile of the shared bpsk_rx core has its own full UVM series.
UVM_RX_PROFILES=('qpsk','qpsk_half_diff','qpsk_axis_diff_ff','qpsk_axis','qpsk_diff','psk8_ff','psk8_fb',
                 'psk8_rotated_fb','pi4','qam16','qam16_eq','qam16_dfe','qam64')


def verified_bpsk_uvm_artifacts(data, root=ROOT):
    """Require both complete RTL pilots before accepting their child artifacts."""
    if not isinstance(data,dict) or data.get('pilot')!='both':
        raise RuntimeError('Both BPSK RX and TX UVM pilots are required')
    if data.get('rx_profile_selection')!='all':
        raise RuntimeError('All registered RX UVM profiles are required')
    records=data.get('records')
    if not isinstance(records,dict):raise RuntimeError('Missing BPSK UVM records')
    rx=['bpsk',*UVM_RX_PROFILES]
    for profile,prefix,scenarios in [('bpsk_tx','tx_',('stream','gaps','stalled','midreset','outreset'))]+[
            (name,'' if name=='bpsk' else name+'_',('stream','stalled','midreset','cfgreset')) for name in rx]:
        for scenario in scenarios:
            for active in (1,0):
                record=records.get(f'{prefix}{scenario}_reset_{active}')
                if (not isinstance(record,dict) or record.get('profile')!=profile
                        or record.get('scenario')!=scenario
                        or type(record.get('reset_active')) is not int
                        or record['reset_active']!=active):
                    raise RuntimeError('Incomplete BPSK UVM scenario coverage')
                if profile!='bpsk_tx':
                    rows=record.get('float_per_frame')
                    if (not isinstance(rows,list) or len(rows)!=4
                            or any(not isinstance(r,dict) or r.get('delta')!=r.get('rtl_errors',0)-r.get('float_errors',0) for r in rows)):
                        raise RuntimeError('Incomplete BPSK UVM float SER comparison')
        if profile!='bpsk_tx':
            for kind in ('decision','errorcount','denominator'):
                record=records.get(f'{prefix}validator_rejects_float_{kind}')
                if not isinstance(record,dict) or not record.get('rejected'):
                    raise RuntimeError('Incomplete independent float validator negatives')
    floats={f'float_{k}':'FLOAT_SER' for k in ('decision','errorcount','denominator')}
    controls=[('',{'numeric':'NUMERIC','ser':'SER','valid_x':'PROTOCOL','ready_x':'PROTOCOL',**floats}),
              ('tx_',{'numeric':'NUMERIC','s_valid_x':'PROTOCOL','s_ready_x':'PROTOCOL',
                      'm_valid_x':'PROTOCOL','m_ready_x':'PROTOCOL','data_x':'NUMERIC','held_data':'STALL'})]
    for name in UVM_RX_PROFILES:
        controls.append((name+'_',{'numeric':'NUMERIC','ser':'SER','label_high_bit':'NUMERIC','valid_x':'PROTOCOL','ready_x':'PROTOCOL',
                                   'warm_ser':'SER',**floats,**({'gain_ready_x':'PROTOCOL'} if name=='qpsk_diff' else {})}))
    for prefix,names in controls:
        for name,tag in names.items():
            for active in (1,0):
                record=records.get(f'{prefix}negative_{name}_reset_{active}')
                if (not isinstance(record,dict) or record.get('detected_tag')!=tag
                        or type(record.get('returncode')) is not int or record['returncode']==0):
                    raise RuntimeError('Incomplete BPSK UVM negative controls')
    if not data.get('artifact_hashes'):raise RuntimeError('Missing BPSK UVM artifacts')
    return verified_suite_artifacts(data,root)


def verified_oqpsk_uvm_artifacts(data, root=ROOT):
    """Require the complete OQPSK TX UVM matrix and every negative control."""
    from run_bpsk_uvm import TX_SCENARIOS
    from run_oqpsk_uvm import CONTROLS
    if not isinstance(data,dict) or data.get('pilot')!='tx' or not isinstance(data.get('records'),dict):
        raise RuntimeError('Complete OQPSK TX UVM records required')
    records=data['records']
    for active in (1,0):
        for scenario in TX_SCENARIOS:
            row=records.get(f'tx_{scenario}_reset_{active}')
            if (not isinstance(row,dict) or row.get('profile')!='oqpsk_tx' or row.get('scenario')!=scenario
                    or type(row.get('reset_active')) is not int or row['reset_active']!=active
                    or row.get('label_bits')!=2 or row.get('labels_seen_mask')!=15):
                raise RuntimeError('Incomplete OQPSK TX UVM scenario/label coverage')
        for name,(tag,_,_) in CONTROLS.items():
            row=records.get(f'tx_negative_{name}_reset_{active}')
            if (not isinstance(row,dict) or row.get('detected_tag')!=tag
                    or type(row.get('returncode')) is not int or row['returncode']==0):
                raise RuntimeError('Incomplete OQPSK TX UVM negative controls')
    if not data.get('artifact_hashes'):raise RuntimeError('Missing OQPSK UVM artifacts')
    return verified_suite_artifacts(data,root)


def verified_packet_rx_uvm_artifacts(data, root=ROOT):
    """Require all OQPSK/MSK/GMSK RX scenarios and independent reference negatives."""
    from run_packet_rx_uvm import PROFILES, SCENARIOS, CONTROLS, VECTOR_CONTROLS, CPM_CONTROLS
    if not isinstance(data,dict) or data.get('profiles')!='all' or not isinstance(data.get('records'),dict):
        raise RuntimeError('All packet RX UVM profiles required')
    records=data['records']
    for name,(_,alphabet) in PROFILES.items():
        for active in (1,0):
            for scenario in SCENARIOS:
                row=records.get(f'{name}_{scenario}_reset_{active}')
                if (not isinstance(row,dict) or row.get('profile')!=name or row.get('scenario')!=scenario
                        or type(row.get('reset_active')) is not int or row['reset_active']!=active
                        or row.get('label_bits')!=(alphabet-1).bit_length()
                        or row.get('soft_bits')!=(18 if name=='oqpsk' else 36)
                        or row.get('terminal_last_discarded')!=int(scenario=='outreset')):
                    raise RuntimeError('Incomplete packet RX UVM scenario/width/reset coverage')
                floats=row.get('float_per_frame')
                if (not isinstance(floats,list) or len(floats)!=4
                        or any(not isinstance(f,dict) or f.get('payload_symbols')!=576
                               or f.get('delta')!=f.get('rtl_errors',0)-f.get('float_errors',0) for f in floats)):
                    raise RuntimeError('Incomplete packet RX floating SER')
            controls={**{k:v[0] for k,v in CONTROLS.items()},**VECTOR_CONTROLS}
            if name!='oqpsk':controls.update({k:v[0] for k,v in CPM_CONTROLS.items()})
            for key,tag in controls.items():
                row=records.get(f'{name}_negative_{key}_reset_{active}')
                if (not isinstance(row,dict) or row.get('detected_tag')!=tag
                        or type(row.get('returncode')) is not int or row['returncode']==0):
                    raise RuntimeError('Incomplete packet RX UVM negative controls')
        for key in ('decision','errorcount','denominator'):
            row=records.get(f'{name}_validator_rejects_float_{key}')
            if not isinstance(row,dict) or not row.get('rejected'):
                raise RuntimeError('Incomplete packet float validator controls')
    if not data.get('artifact_hashes'):raise RuntimeError('Missing packet RX UVM artifacts')
    return verified_suite_artifacts(data,root)


def verified_cpm_uvm_artifacts(data, root=ROOT):
    from run_cpm_uvm import PROFILES, CONTROLS, TX_SCENARIOS
    if not isinstance(data,dict) or data.get('profiles')!='all' or not isinstance(data.get('records'),dict):
        raise RuntimeError('Both CPM TX UVM profiles required')
    records=data['records']
    for profile in PROFILES:
        for active in (1,0):
            for scenario in TX_SCENARIOS:
                row=records.get(f'{profile}_{scenario}_reset_{active}')
                if (not isinstance(row,dict) or row.get('profile')!=profile+'_tx' or row.get('scenario')!=scenario
                        or type(row.get('reset_active')) is not int or row['reset_active']!=active
                        or row.get('label_bits')!=1 or row.get('labels_seen_mask')!=3):
                    raise RuntimeError('Incomplete CPM TX UVM scenario/width coverage')
            for key,(tag,_,_) in CONTROLS.items():
                row=records.get(f'{profile}_negative_{key}_reset_{active}')
                if (not isinstance(row,dict) or row.get('detected_tag')!=tag
                        or type(row.get('returncode')) is not int or row['returncode']==0):
                    raise RuntimeError('Incomplete CPM TX UVM negative controls')
    if not data.get('artifact_hashes'):raise RuntimeError('Missing CPM TX UVM artifacts')
    return verified_suite_artifacts(data,root)


def verified_fft_uvm_artifacts(data, root=ROOT):
    from run_fft_uvm import CASES, SCENARIOS, CONTROLS
    if not isinstance(data,dict) or data.get('case_selection')!='all' or not isinstance(data.get('records'),dict):
        raise RuntimeError('All FFT UVM geometries required')
    records=data['records']
    for name,(log2n,frames,in_width,width) in CASES.items():
        for active in (1,0):
            for scenario in SCENARIOS:
                row=records.get(f'{name}_{scenario}_reset_{active}')
                if (not isinstance(row,dict) or row.get('case')!=name or row.get('scenario')!=scenario
                        or type(row.get('reset_active')) is not int or row['reset_active']!=active
                        or (row.get('log2n'),row.get('in_width'),row.get('width'))!=(log2n,in_width,width)
                        or not isinstance(row.get('per_frame'),list) or len(row['per_frame'])!=frames
                        or row.get('terminal_resets')!=int(scenario=='outreset')
                        or row.get('bad_completed')!=int(scenario=='badlast')):
                    raise RuntimeError('Incomplete FFT UVM scenario/width/error/reset coverage')
            for key,(tag,_,_) in CONTROLS.items():
                row=records.get(f'{name}_negative_{key}_reset_{active}')
                if (not isinstance(row,dict) or row.get('detected_tag')!=tag
                        or type(row.get('returncode')) is not int or row['returncode']==0):
                    raise RuntimeError('Incomplete FFT UVM negative controls')
    if not data.get('artifact_hashes'):raise RuntimeError('Missing FFT UVM artifacts')
    return verified_suite_artifacts(data,root)


def verified_dsp_uvm_artifacts(data, root=ROOT):
    from dsp_uvm_plans import CASES,contract
    from run_dsp_uvm import scenarios,controls
    if not isinstance(data,dict) or data.get('case_selection')!='all' or not isinstance(data.get('records'),dict):
        raise RuntimeError('All DSP UVM cases required')
    records=data['records']
    for name,case in CASES.items():
        schema=contract(case);configured=bool(schema['config_fields'])
        model=dict(config_rows=int(configured),**schema)
        input_bits=sum(bits for _,bits,_ in schema['input_fields'])
        output_bits=sum(bits for _,bits,_ in schema['output_fields'])
        for active in (1,0):
            for scenario in scenarios(model):
                row=records.get(f'{name}_{scenario}_reset_{active}')
                if (not isinstance(row,dict) or row.get('case')!=name or row.get('kind')!=case['kind'] or row.get('scenario')!=scenario
                        or type(row.get('reset_active')) is not int or row['reset_active']!=active
                        or row.get('configured') is not configured
                        or row.get('cfgreset_supported') is not schema['cfgreset_supported']
                        or row.get('error_port') is not schema['error_port'] or row.get('sideband_port') is not schema['sideband_port']
                        or row.get('packed_input_bits')!=input_bits or row.get('packed_output_bits')!=output_bits
                        or not isinstance(row.get('per_frame'),list) or len(row['per_frame'])!=schema['expected_frames']
                        or row.get('terminal_resets')!=int(scenario=='outreset')
                        or row.get('weight_port') is not schema['weight_port']
                        or row.get('packed_weight_bits')!=(36 if schema['weight_port'] else 0)
                        or row.get('weight_terminal_resets')!=int(scenario=='woutreset')
                        or row.get('per_weight_frame')!=([dict(frame=f,outputs=case['taps']) for f in range(schema['expected_frames'])] if schema['weight_port'] else [])):
                    raise RuntimeError('Incomplete DSP UVM case/width/frame/reset/physical-port coverage')
            for key,(tag,_,_) in controls(model).items():
                row=records.get(f'{name}_negative_{key}_reset_{active}')
                if (not isinstance(row,dict) or row.get('detected_tag')!=tag
                        or type(row.get('returncode')) is not int or row['returncode']==0):
                    raise RuntimeError('Incomplete DSP UVM negative controls')
    if not data.get('artifact_hashes'):raise RuntimeError('Missing DSP UVM artifacts')
    return verified_suite_artifacts(data,root)


def verified_psk_tx_uvm_artifacts(data,root=ROOT):
    from run_psk_tx_uvm import PROFILES,TX_SCENARIOS,CONTROLS,parameters
    if not isinstance(data,dict) or data.get('profiles')!='all' or not isinstance(data.get('records'),dict):
        raise RuntimeError('All PSK/QAM TX UVM profiles required')
    records=data['records']
    for name,profile in PROFILES.items():
        bits=(profile.alphabet-1).bit_length();mask=(1<<profile.alphabet)-1
        for active in (1,0):
            for scenario in TX_SCENARIOS:
                row=records.get(f'{name}_{scenario}_reset_{active}')
                if (not isinstance(row,dict) or row.get('profile')!=name+'_tx' or row.get('scenario')!=scenario
                        or type(row.get('reset_active')) is not int or row['reset_active']!=active
                        or row.get('label_bits')!=bits or row.get('labels_seen_mask')!=mask or row.get('tx_parameters')!=parameters(name)
                        or row.get('per_frame')!=[dict(frame=f,input_symbols=n,output_samples=8*n+32) for f,n in enumerate((1,2,33,192,768))]
                        or row.get('held_last_resets')!=int(scenario=='outreset')):
                    raise RuntimeError('Incomplete PSK/QAM TX UVM profile/mapper/label/frame/reset coverage')
            for key,(tag,_,_) in CONTROLS.items():
                row=records.get(f'{name}_negative_{key}_reset_{active}')
                if (not isinstance(row,dict) or row.get('detected_tag')!=tag
                        or type(row.get('returncode')) is not int or row['returncode']==0):
                    raise RuntimeError('Incomplete PSK/QAM TX UVM negative controls')
    if not data.get('artifact_hashes'):raise RuntimeError('Missing PSK/QAM TX UVM artifacts')
    return verified_suite_artifacts(data,root)


def verified_dsp_rates_artifacts(data,root=ROOT):
    from dsp_stream_rates import verified_artifacts
    return verified_artifacts(data,root)


def verified_modem_rates_artifacts(data,root=ROOT):
    from modem_stream_rates import verified_artifacts
    return verified_artifacts(data,root)


def python_tests(configs):
    suite=unittest.TestSuite()
    files=[ROOT/'tests'/'test_primitives.py', ROOT/'tests'/'test_regression_guards.py', ROOT/'tests'/'test_fixed_point.py', ROOT/'tests'/'test_rtl_tools.py', ROOT/'tests'/'test_bpsk_fixed.py', ROOT/'tests'/'test_psk_fixed.py', ROOT/'tests'/'test_mrc_fixed.py', ROOT/'tests'/'test_cpm_fixed.py', ROOT/'tests'/'test_oqpsk_fixed.py', ROOT/'tests'/'test_fft_fixed.py', ROOT/'tests'/'test_ofdm_fixed.py', ROOT/'tests'/'test_stft_fixed.py', ROOT/'tests'/'test_pfb_fixed.py', ROOT/'tests'/'test_fir_fixed.py', ROOT/'tests'/'test_oset_fixed.py', ROOT/'tests'/'test_fsk_fixed.py', ROOT/'tests'/'test_beam_fixed.py', ROOT/'tests'/'test_sync_fixed.py', ROOT/'tests'/'test_lms_fixed.py', ROOT/'tests'/'test_ldpc_fixed.py', ROOT/'tests'/'test_mmse_fixed.py', ROOT/'tests'/'test_rls_fixed.py', ROOT/'tests'/'test_omlsa_fixed.py']+[p.parent/'tests'/'test_modem.py' for p in configs]
    files.extend(ROOT/'tests'/name for name in ('test_questa_symlink.py',
                 'test_sync_slip_evidence.py', 'test_sync_precision.py', 'test_costas_stream_acquisition.py', 'test_costas_stream_runner.py', 'test_bpsk_rx_continuous_rate.py',
                 'test_costas_acquisition.py', 'test_sync_disturbance.py',
                 'test_sync_grid_evidence.py', 'test_timing_precision.py',
                 'test_psk_precision.py', 'test_mmse3_fixed.py', 'test_mmse_n_fixed.py', 'test_loop_delay_study.py', 'test_fir_width_sweep.py', 'test_pfb_width_sweep.py', 'test_istft_width_sweep.py', 'test_lms_energy_study.py', 'test_beam_energy_study.py', 'test_alamouti_width_sweep.py', 'test_rls_width_sweep.py', 'test_rls_update_sweep.py', 'test_lms_width_sweep.py', 'test_mmse2_width_sweep.py', 'test_omlsa_width_sweep.py',
                 'test_mmse3_width_sweep.py',
                 'test_mmse3_config_width_sweep.py', 'test_mmse_n_width_sweep.py', 'test_mmse_scale_updates.py', 'test_mmse_norm_back.py', 'test_axis_fifo.py',
                 'test_fifo_budget.py', 'test_fifo_load_sweep.py',
                 'test_lms_fifo_budget.py', 'test_lms_fifo_load_sweep.py', 'test_cic_models.py', 'test_filter_models.py',
                 'test_cpm_precision.py','test_oqpsk_mrc_precision.py',
                 'test_fft_fir_precision.py','test_coverage_report.py','test_stream_rates.py',
                 'test_bpsk_ser_evidence.py','test_fft_width_sweep.py',
                 'test_adaptive_precision.py','test_suite_evidence.py',
                 'test_bpsk_uvm_evidence.py','test_uvm_floating_reference.py','test_linear_precision.py',
                 'test_sync_adaptive_rates.py','test_state_precision.py',
                 'test_ldpc_precision.py','test_spectral_precision.py','test_uvm_pilot_coverage.py',
                 'test_mmse3_rates.py','test_oqpsk_uvm_evidence.py','test_packet_rx_uvm.py','test_cpm_uvm.py','test_fft_uvm.py','test_dsp_uvm.py','test_psk_tx_uvm.py','test_dsp_stream_rates.py','test_modem_stream_rates.py'))
    files.extend(sorted((ROOT/'tests').glob('test_ext_*.py')))
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
        ACTIVE_REPORTS.append((target,evidence['started_at_utc']))
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
    for suite in targets:
        target=output/f'{suite}_results.json'
        write_json(target,{'status':'RUNNING',**evidence})
        ACTIVE_REPORTS.append((target,evidence['started_at_utc']))
    summary=dict(suite=args.suite,modems=len(configs),model_names=[p.parent.name for p in configs]); start=time.monotonic()
    if args.suite in ('python','all'):
        summary['python_tests']=python_tests(configs)
        if not args.modem:
            summary['precision_results']={}
            for name in ('psk_precision','cpm_precision','oqpsk_mrc_precision','fft_fir_precision',
                         'adaptive_precision','linear_precision','state_precision',
                         'ldpc_precision','spectral_precision','loop_delay_study','fir_width_sweep','pfb_width_sweep','istft_width_sweep','lms_energy_study','beam_energy_study','alamouti_width_sweep','rls_width_sweep','rls_update_sweep','lms_width_sweep','mmse2_width_sweep','mmse3_width_sweep','mmse3_config_width_sweep','mmse_n_width_sweep','mmse_scale_update_sweep','mmse_norm_back_sweep','axis_fifo_sweep','fifo_load_sweep','lms_fifo_load_sweep','omlsa_width_sweep'):
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
            log=output/'logs/axis_fifo.log';log.parent.mkdir(parents=True,exist_ok=True)
            result=subprocess.run([sys.executable,str(ROOT/'tools/axis_fifo_sweep.py'),'--verify-rtl'],capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'AXIS FIFO verification failed: {log}')
            from axis_fifo_sweep import verified_artifacts as verified_fifo_artifacts
            report=ROOT/'build/rtl/axis_fifo_sweep/results.json';fifo=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_fifo_artifacts(fifo)])
            summary['rtl_axis_fifo']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
            log=output/'logs/fifo_loads.log'
            fifo_output=output/'rtl/fifo_load_sweep'/f'run_{time.time_ns()}'
            result=subprocess.run([sys.executable,str(ROOT/'tools/fifo_load_sweep.py'),'--verify-rtl','--output',str(fifo_output)],capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'FIFO load verification failed: {log}')
            from fifo_load_sweep import verified_artifacts as verified_fifo_load_artifacts
            report=fifo_output/'results.json';loads=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_fifo_load_artifacts(loads)])
            summary['rtl_fifo_loads']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
            log=output/'logs/lms_fifo_loads.log'
            fifo_output=output/'rtl/lms_fifo_load_sweep'/f'run_{time.time_ns()}'
            result=subprocess.run([sys.executable,str(ROOT/'tools/lms_fifo_load_sweep.py'),'--verify-rtl','--output',str(fifo_output)],capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'LMS FIFO load verification failed: {log}')
            from lms_fifo_load_sweep import verified_artifacts as verified_lms_fifo_load_artifacts
            report=fifo_output/'results.json';loads=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_lms_fifo_load_artifacts(loads)])
            summary['rtl_lms_fifo_loads']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
            log=output/'logs/bpsk_uvm.log';log.parent.mkdir(parents=True,exist_ok=True)
            result=subprocess.run([sys.executable,str(ROOT/'tools/run_bpsk_uvm.py'),'--suite','all'],
                                  capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'BPSK RTL UVM pilot failed: {log}')
            report=ROOT/'build/rtl/bpsk_uvm/all_results.json'
            pilot=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_bpsk_uvm_artifacts(pilot)])
            summary['rtl_uvm_pilot']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
            log=output/'logs/oqpsk_uvm.log'
            result=subprocess.run([sys.executable,str(ROOT/'tools/run_oqpsk_uvm.py'),'--suite','all'],
                                  capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'OQPSK TX UVM failed: {log}')
            report=ROOT/'build/rtl/oqpsk_uvm/all_results.json'
            pilot=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_oqpsk_uvm_artifacts(pilot)])
            summary['rtl_oqpsk_uvm']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
            log=output/'logs/packet_rx_uvm.log'
            result=subprocess.run([sys.executable,str(ROOT/'tools/run_packet_rx_uvm.py'),'--suite','all'],
                                  capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'Packet RX UVM failed: {log}')
            report=ROOT/'build/rtl/packet_rx_uvm/all_results.json'
            pilot=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_packet_rx_uvm_artifacts(pilot)])
            summary['rtl_packet_rx_uvm']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
            log=output/'logs/cpm_uvm.log'
            result=subprocess.run([sys.executable,str(ROOT/'tools/run_cpm_uvm.py'),'--suite','all'],
                                  capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'CPM TX UVM failed: {log}')
            report=ROOT/'build/rtl/cpm_uvm/all_results.json'
            pilot=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_cpm_uvm_artifacts(pilot)])
            summary['rtl_cpm_uvm']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
            log=output/'logs/psk_tx_uvm.log'
            result=subprocess.run([sys.executable,str(ROOT/'tools/run_psk_tx_uvm.py'),'--suite','all'],
                                  capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'PSK/QAM TX UVM failed: {log}')
            report=ROOT/'build/rtl/psk_tx_uvm/all_results.json'
            pilot=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_psk_tx_uvm_artifacts(pilot)])
            summary['rtl_psk_tx_uvm']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
            log=output/'logs/fft_uvm.log'
            result=subprocess.run([sys.executable,str(ROOT/'tools/run_fft_uvm.py'),'--suite','all'],
                                  capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'FFT UVM failed: {log}')
            report=ROOT/'build/rtl/fft_uvm/all_results.json'
            pilot=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_fft_uvm_artifacts(pilot)])
            summary['rtl_fft_uvm']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
            log=output/'logs/dsp_uvm.log'
            result=subprocess.run([sys.executable,str(ROOT/'tools/run_dsp_uvm.py'),'--suite','all'],
                                  capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'DSP UVM failed: {log}')
            report=ROOT/'build/rtl/dsp_uvm/all_results.json'
            pilot=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_dsp_uvm_artifacts(pilot)])
            summary['rtl_dsp_uvm']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
            log=output/'logs/dsp_rates.log'
            result=subprocess.run([sys.executable,str(ROOT/'tools/dsp_stream_rates.py')],capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'DSP pin rate measurement failed: {log}')
            report=ROOT/'build/rtl/dsp_rates/results.json'
            measurement=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_dsp_rates_artifacts(measurement)])
            summary['rtl_dsp_rates']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
            log=output/'logs/modem_rates.log'
            result=subprocess.run([sys.executable,str(ROOT/'tools/modem_stream_rates.py')],capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'Modem pin rate measurement failed: {log}')
            report=ROOT/'build/rtl/modem_rates/results.json'
            measurement=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_modem_rates_artifacts(measurement)])
            summary['rtl_modem_rates']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
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


if __name__=='__main__':
    try:main()
    except Exception as exc:
        mark_failed_reports(ACTIVE_REPORTS,exc)
        raise
