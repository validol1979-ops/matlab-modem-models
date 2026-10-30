"""DSP UVM plans preserve native bits; acceptance requires complete reset accounting."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from dsp_uvm_plans import CASES,prepare,rows,split_frames,pack_pair,unpack_pair,pack_fields,unpack_fields,contract
from run_dsp_uvm import SCENARIOS,CONTROLS,CFG_CONTROLS,parse_report,verify_negative,scenarios,controls


def report_text(model,scenario='stream'):
    mid,out,cfg=scenario=='midreset',scenario=='outreset',scenario=='cfgreset';wout=scenario=='woutreset';reset=mid or out or cfg or wout
    c,ni,no=model['config_rows'],model['warm_inputs'],model['warm_outputs']
    wc=max(1,c//2) if cfg else c if mid or out or wout else 0
    wi=max(1,ni//2) if mid else ni if out or wout else 0
    prefix=no-1 if out else no if wout else 0
    configs=c+wc;inputs=model['inputs']+wi;outputs=model['outputs']+prefix
    lines=[f'UVM DSP FRAME id={k} inputs={a} outputs={b}' for k,(a,b) in enumerate(model['lengths'])]
    lines += [f'UVM DSP checked={outputs} inputs={inputs} configs={configs} frames={model["frames"]} '
              f'discarded={no-prefix if reset else 0} discarded_inputs={ni-wi if reset else 0} discarded_configs={c-wc if reset else 0} '
              f'expected={model["outputs"]+no*int(reset)} expected_inputs={model["inputs"]+ni*int(reset)} '
              f'expected_configs={c+c*int(reset)} resets={1+int(reset)} before_reset={prefix} terminal_resets={int(out)}',
              f'UVM DSP KIND id={model["case"]["kind"]}',
              'UVM DSP MEMORY '+' '.join(f'{label}={model["case"].get(key,default)}' for label,key,default in [('mmax','log2mmax',6),('kmax','log2kmax',6),('emax','log2emax',9)]),
              f'UVM DSP EXTRA log2m={model["case"].get("log2m",2)} log2nmax={model["case"].get("log2nmax",5)}',
              'UVM DSP PARAMETERS '+' '.join(f'{label}={model["case"].get(key,default)}' for label,key,default in
                  [('log2n','log2n',5),('cp','cp',8),('log2hop','log2hop',3),('lanes','log2lanes',2),('tmax','log2tmax',7)]),
              f'UVM DSP HANDSHAKES config={configs} input={inputs} output={outputs} cfg_stalls=0 input_stalls=10 '
              f'output_stalls={20 if scenario in ("stalled","outreset","woutreset") else 0} gaps={3 if scenario=="gaps" else 0} pending_resets={int(out)}',
              'UVM_ERROR : 0','UVM_FATAL : 0']
    wn=model['warm_weights'];wp=wn-1 if wout else 0
    wc=model['weight_rows']+wp
    lines.extend(f'UVM DSP WEIGHT_FRAME id={k} outputs={count}' for k,count in enumerate(model['weight_lengths']) if count)
    lines.extend([f'UVM DSP WEIGHTS checked={wc} expected={model["weight_rows"]+wn*int(reset)} '
                  f'discarded={wn-wp if reset else 0} before_reset={wp} frames={model["frames"] if model["weight_port"] else 0} terminal_resets={int(wout)}',
                  f'UVM DSP WEIGHT_HANDSHAKES outputs={wc} stalls={3 if model["weight_port"] and scenario in ("stalled","woutreset") else 0} pending_resets={int(wout)}'])
    return '\n'.join(lines)


class TestDspUvm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();cls.folder=Path(cls.temporary.name)
        cls.models={name:prepare(cls.folder/name,name) for name in CASES}
    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def test_physical_signed_packing_is_lossless_and_rejects_padding(self):
        for width in (18,24):
            lo,hi=-(1<<(width-1)),(1<<(width-1))-1
            for re,im in ((lo,hi),(hi,lo),(-1,-1),(0,0),(1,-1)):
                word=pack_pair(re,im,width)
                self.assertEqual(unpack_pair(word,width),(re,im))
                with self.assertRaises(ValueError):unpack_pair(word|(1<<(2*width)),width)
            for pair in ((lo-1,0),(0,hi+1),(1.0,0)):
                with self.assertRaises(ValueError):pack_pair(*pair,width)

    def test_unsigned_configuration_fields_labels_and_padding_are_preserved(self):
        schemas=[contract(case) for case in CASES.values()]
        for schema in schemas:
            for key in ('config_fields','input_fields','output_fields','weight_fields'):
                fields=schema[key]
                lo=[-(1<<(bits-1)) if signed else 0 for _,bits,signed in fields]
                hi=[(1<<(bits-int(signed)))-1 for _,bits,signed in fields]
                for values in (lo,hi):
                    word=pack_fields(values,fields)
                    self.assertEqual(unpack_fields(word,fields),tuple(values))
                    with self.assertRaises(ValueError):unpack_fields(word|(1<<sum(bits for _,bits,_ in fields)),fields)
                if fields:
                    with self.assertRaises(ValueError):pack_fields([hi[0]+1,*hi[1:]],fields)
                    with self.assertRaises(ValueError):pack_fields([lo[0]-1,*lo[1:]],fields)
                    with self.assertRaises(ValueError):pack_fields([True,*lo[1:]],fields)
        self.assertFalse(contract(CASES['notch_case0'])['error_port'])
        self.assertFalse(contract(CASES['notch_case0'])['cfg_last_port'])
        self.assertFalse(contract(CASES['kalman_case0'])['cfgreset_supported'])
        self.assertEqual(contract(CASES['fsk_rx_n1_m1'])['output_fields'],[('label',1,False)])

    def test_plan_decodes_every_original_native_row_without_numeric_changes(self):
        for name,model in self.models.items():
            folder=self.folder/name;case=model['case'];native=folder/'native'
            a,b=model['native_input'],model['native_output']
            original_in=rows(native/a,len(model['input_fields'])+1,header=model['native_header'])
            original_out=rows(native/b,len(model['output_fields'])+1,header=model['native_header'])
            lines=iter((folder/'plan.txt').read_text().splitlines());c,f=map(int,next(lines).split())
            self.assertEqual((c,f),(model['config_rows'],model['frames']))
            if c:
                taps=model['native_config']
                for k in range(c):
                    word,last=next(lines).split()
                    self.assertEqual(unpack_fields(int(word,16),model['config_fields']),tuple(taps[k]));self.assertEqual(int(last),int(k==c-1 and model['cfg_last_port']))
            got_in,got_out,got_weights=[],[],[]
            for index in range(f):
                ni,no,nw=map(int,next(lines).split());self.assertEqual((ni,no),tuple(model['lengths'][index]));self.assertEqual(nw,model['weight_lengths'][index])
                for k in range(ni):
                    word,last,gap=next(lines).split();got_in.append([*unpack_fields(int(word,16),model['input_fields']),int(last)])
                    self.assertEqual(int(gap),2 if k%5==1 else 0)
                for k in range(no):
                    word,last=next(lines).split();got_out.append([*unpack_fields(int(word,16),model['output_fields']),int(last)])
                for k in range(nw):
                    word,last=next(lines).split();got_weights.append([*unpack_fields(int(word,16),model['weight_fields']),int(last)])
            self.assertEqual(got_in,original_in);self.assertEqual(got_out,original_out)
            self.assertEqual(got_weights,rows(native/'w.txt',3) if model['weight_port'] else [])
            with self.assertRaises(StopIteration):next(lines)

    def test_independent_ofdm_stft_and_fir_geometry_and_reset_scenarios(self):
        for name,model in self.models.items():
            case=model['case'];n=1<<case.get('log2n',0);hop=1<<case.get('log2hop',0)
            for ni,no in model['lengths']:
                if case['kind']==1:self.assertEqual(no,ni+model['config_rows']-1)
                elif case['kind']==2:self.assertEqual((ni,no),(n,n+case['cp']))
                elif case['kind']==3:self.assertEqual((ni,no),(n+case['cp'],n))
                elif case['kind']==4:self.assertEqual(no,n*(1+(ni-n)//hop))
                elif case['kind']==5:self.assertEqual(no,(ni//n-1)*hop+n)
                elif case['kind']==6:self.assertEqual(no,(1<<case['log2m'])*((ni+case['d']-1)//case['d']))
                elif case['kind'] in (7,8):self.assertEqual(no,ni)
                elif case['kind']==9:self.assertEqual(no,ni*case['n'])
                elif case['kind']==10:self.assertEqual(ni,no*case['n'])
                elif case['kind'] in (20,21):self.assertEqual(ni,no)
                elif case['kind']==18:self.assertEqual((ni,no),(case['n'],case['n']))
                elif case['kind']==19:self.assertEqual((ni,no),(case['k'],case['m']+case['k']))
                elif case['kind']==17:self.assertEqual((no,ni>=n+1),(ni,True))
                elif case['kind']==13:self.assertEqual(no,ni)
                elif case['kind']==14:self.assertEqual(no,case['timing'][1])
                elif case['kind']==11:self.assertEqual(ni,no*case['m'])
                elif case['kind']==12:self.assertEqual((ni%2,no),(0,ni))
                elif case['kind'] in (15,16):self.assertEqual((ni%case['dimension'],no),(0,ni))
            self.assertEqual(model['frames'],contract(case)['expected_frames'])
            for active in (1,0):
                for scenario in scenarios(model):
                    row=parse_report(report_text(model,scenario),model,scenario,active)
                    self.assertEqual(row['case'],name)
                    self.assertEqual(row['checked']+row['discarded_outputs'],row['expected_outputs'])
                    self.assertEqual(row['input_checked']+row['discarded_inputs'],row['expected_inputs'])

    def test_incomplete_duplicated_wrong_kind_and_queue_conservation_rejected(self):
        for model in self.models.values():
            text=report_text(model,'outreset')
            for bad in (text+text,text.replace('UVM_FATAL : 0','UVM_FATAL : 1'),
                        text.replace('UVM DSP KIND id=','UVM DSP KIND wrong='),
                        text.replace('UVM DSP PARAMETERS log2n=','UVM DSP PARAMETERS wrong='),
                        text.replace('terminal_resets=1','terminal_resets=0'),
                        text.replace('discarded=1 ','discarded=2 '),text.replace('pending_resets=1','pending_resets=0')):
                with self.subTest(case=model['name']),self.assertRaises(RuntimeError):parse_report(bad,model,'outreset',1)
            with self.assertRaises(RuntimeError):parse_report(text,model,'outreset',1,13)
            with self.assertRaises(RuntimeError):parse_report(report_text(model,'gaps').replace('gaps=3','gaps=0'),model,'gaps',0)

    def test_configuration_applicability_and_partial_discard_required(self):
        for model in self.models.values():
            if model['cfgreset_supported']:
                text=report_text(model,'cfgreset')
                with self.assertRaises(RuntimeError):parse_report(text.replace('resets=2','resets=1'),model,'cfgreset',0)
                self.assertEqual(set(controls(model)),set(CONTROLS)|set(CFG_CONTROLS)|({'sideband'} if model['sideband_port'] else set()))
            else:
                with self.assertRaises(RuntimeError):parse_report(report_text(model),model,'cfgreset',0)
                self.assertEqual(set(controls(model)),(set(CONTROLS)-({'error_x'} if not model['error_port'] else set()))|(set(CFG_CONTROLS) if model['config_rows'] else set())|({'sideband'} if model['sideband_port'] else set())|({'desired_data','error_data','weight_numeric','weight_valid_x','weight_ready_x','weight_data_x','weight_last','weight_held'} if model['weight_port'] else set()))

    def test_weight_stream_has_independent_last_reset_width_and_handshakes(self):
        for model in self.models.values():
            if not model['weight_port']:
                with self.assertRaises(RuntimeError):parse_report(report_text(model),model,'woutreset',1)
                continue
            self.assertEqual(model['packed_input_bits'],72);self.assertEqual(model['packed_output_bits'],72)
            self.assertEqual(model['packed_weight_bits'],36)
            self.assertEqual(model['weight_rows'],model['frames']*model['case']['taps'])
            text=report_text(model,'woutreset');good=parse_report(text,model,'woutreset',0)
            self.assertEqual(good['weight_discarded'],1)
            for bad in (text.replace('UVM DSP WEIGHTS checked=','UVM DSP WEIGHTS missing='),
                        text.replace('UVM DSP WEIGHT_FRAME id=0','UVM DSP WEIGHT_FRAME id=999'),
                        text.replace('stalls=3 pending_resets=1','stalls=0 pending_resets=1'),
                        text.replace('stalls=3 pending_resets=1','stalls=3 pending_resets=0'),
                        text.replace('discarded=1 before_reset=','discarded=0 before_reset=')):
                with self.subTest(case=model['name']),self.assertRaises(RuntimeError):parse_report(bad,model,'woutreset',0)

    def test_negative_requires_intended_fatal_and_no_completed_summary(self):
        for tag in ('NUMERIC','PROTOCOL','STALL'):
            text=f'UVM_FATAL @ 1: reporter [{tag}] fault\nUVM_FATAL : 1'
            verify_negative(text,13,tag)
            for bad,rc in ((text,0),(text.replace(f'[{tag}]','[OTHER]'),13),(text.replace('UVM_FATAL : 1','UVM_FATAL : 0'),13),
                           (text+'\n'+report_text(next(iter(self.models.values()))),13)):
                with self.assertRaises(RuntimeError):verify_negative(bad,rc,tag)

    def test_parent_requires_every_geometry_and_configuration_control(self):
        from regression_evidence import begin,finish
        from run_tests import verified_dsp_uvm_artifacts
        records={}
        for name,model in self.models.items():
            for active in (1,0):
                for scenario in scenarios(model):records[f'{name}_{scenario}_reset_{active}']=parse_report(report_text(model,scenario),model,scenario,active)
                for key,(tag,_,_) in controls(model).items():records[f'{name}_negative_{key}_reset_{active}']=dict(returncode=13,detected_tag=tag)
        log=self.folder/'coverage.log';log.write_text('DSP coverage fixture')
        original=dict(finish(begin(),[log]),status='PASS',case_selection='all',records=records)
        self.assertEqual(verified_dsp_uvm_artifacts(original),[log])
        for fault in ('partial','missing','width','configuration','bool_reset','control','tag','rc0','bool_rc','pfb','notch','fsk','atomic','ldpc','gf2','weight_frame','weight_reset','weight_width','weight_control','artifact'):
            data=copy.deepcopy(original)
            if fault=='partial':data['case_selection']='ofdm_tx_n4_cp1'
            elif fault=='missing':data['records'].pop('stft_synthesis_n256_h64_outreset_reset_0')
            elif fault=='width':data['records']['stft_analysis_n4_h1_stream_reset_1']['packed_output_bits']=36
            elif fault=='configuration':data['records']['fir_single_l0_t1_cfgreset_reset_0']['configured']=False
            elif fault=='bool_reset':data['records']['ofdm_rx_n4_cp1_stream_reset_1']['reset_active']=True
            elif fault=='control':data['records'].pop('fir_complex_l2_t4_negative_cfg_data_reset_1')
            elif fault=='tag':data['records']['ofdm_tx_n8_cp8_negative_held_data_reset_0']['detected_tag']='NUMERIC'
            elif fault=='rc0':data['records']['stft_synthesis_n4_h1_negative_error_x_reset_1']['returncode']=0
            elif fault=='bool_rc':data['records']['stft_synthesis_n4_h1_negative_error_x_reset_1']['returncode']=True
            elif fault=='pfb':data['records'].pop('pfb_m64_d32_t129_l3_cfgreset_reset_0')
            elif fault=='notch':data['records'].pop('notch_case4_negative_cfg_data_reset_1')
            elif fault=='fsk':data['records']['fsk_rx_n1_m1_stream_reset_0']['packed_output_bits']=2
            elif fault=='atomic':data['records']['kalman_case1_stream_reset_1']['cfgreset_supported']=True
            elif fault=='ldpc':data['records'].pop('ldpc_model_mode0_case6_outreset_reset_0')
            elif fault=='gf2':data['records'].pop('gf2_big_mode1_case5_cfgreset_reset_1')
            elif fault=='weight_frame':data['records']['nlms_t16_case4_stream_reset_1']['per_weight_frame']=[]
            elif fault=='weight_reset':data['records']['rls_t1_case5_woutreset_reset_0']['weight_terminal_resets']=0
            elif fault=='weight_width':data['records']['lms_t1_case2_stalled_reset_1']['packed_weight_bits']=18
            elif fault=='weight_control':data['records'].pop('rls_t2_case6_negative_weight_held_reset_1')
            else:data['artifact_hashes']={}
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):verified_dsp_uvm_artifacts(data)
        log.write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'artifact'):verified_dsp_uvm_artifacts(original)


if __name__=='__main__':unittest.main()
