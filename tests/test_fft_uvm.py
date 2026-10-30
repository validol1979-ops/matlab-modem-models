"""FFT UVM evidence: independent frames, actual pins, reset/error conservation."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from run_fft_uvm import CASES, SCENARIOS, CONTROLS, prepare_vectors, parse_report, verify_negative
from run_tests import verified_fft_uvm_artifacts
from regression_evidence import begin, finish


def report_text(model,scenario='stream'):
    n=1<<model['log2n'];normal=n*model['frames']
    mid,out,bad=scenario=='midreset',scenario=='outreset',scenario=='badlast'
    reset=mid or out or bad
    inputs=normal+(n//2 if mid else n if out or bad else 0)
    outputs=normal+(n-1 if out else n if bad else 0)
    discard=n if mid else 1 if out else 0
    lines=[f'UVM FFT FRAME id={f} samples={n} inverse={mode}' for f,mode in enumerate(model['frame_modes'])]
    lines += [f'UVM FFT checked={outputs} inputs={inputs} frames={model["frames"]} discarded={discard} '
              f'discarded_inputs={n//2 if mid else 0} expected={normal+n*int(reset)} expected_inputs={normal+n*int(reset)} '
              f'resets={1+int(reset)} before_reset={n-1 if out else 0} terminal_resets={int(out)} bad_completed={int(bad)} modes={model["mode_mask"]}',
              f'UVM FFT WIDTH log2n={model["log2n"]} input={model["in_width"]} output={model["width"]}',
              f'UVM FFT HANDSHAKES input={inputs} output={outputs} input_stalls={30 if scenario=="stalled" else 0} '
              f'output_stalls={50 if scenario in ("stalled","outreset","badlast") else 0} gaps={3 if scenario=="gaps" else 0} '
              f'pending_resets={int(out)} error_cycles={50 if bad else 0}',
              'UVM_ERROR : 0','UVM_FATAL : 0']
    return '\n'.join(lines)


class TestFftUvm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();cls.folder=Path(cls.temporary.name)
        cls.models={name:prepare_vectors(cls.folder/name,name) for name in CASES}
    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def test_native_vectors_preserved_and_forward_agrees_with_numpy(self):
        from run_fft import BOUNDARY
        from fft_cases import vectors,boundary_vectors
        for name,model in self.models.items():
            original=self.folder/(name+'_native');log2n,frames,in_width,width=CASES[name]
            if CASES[name]==BOUNDARY:boundary_vectors(original)
            else:vectors(original,log2n,frames=frames,in_width=in_width,width=width)
            for filename in ('in.txt','out.txt','saturation_expected.txt'):
                self.assertEqual((original/filename).read_bytes(),(self.folder/name/filename).read_bytes())
            source=np.loadtxt(original/'in.txt',skiprows=1,dtype=int)
            output=np.loadtxt(original/'out.txt',skiprows=1,dtype=int)
            n=1<<log2n
            self.assertEqual(model['samples'],n*frames)
            self.assertEqual(int(source[:,3].sum()),frames)
            for f,mode in enumerate(model['frame_modes']):
                if mode:continue
                block=source[f*n:(f+1)*n]
                expected=np.fft.fft(block[:,0]+1j*block[:,1])/n
                actual=output[f*n:(f+1)*n,0]+1j*output[f*n:(f+1)*n,1]
                self.assertLess(np.max(abs(actual-expected)),8*(log2n+1))

    def test_every_geometry_scenario_and_polarity(self):
        for name,model in self.models.items():
            for active in (1,0):
                for scenario in SCENARIOS:
                    row=parse_report(report_text(model,scenario),model,scenario,active)
                    self.assertEqual(row['case'],name)
                    self.assertEqual(row['checked']+row['discarded_outputs'],row['expected_outputs'])
                    self.assertEqual(row['input_checked']+row['discarded_inputs'],row['expected_inputs'])

    def test_incomplete_false_healthy_width_and_direction_reports_rejected(self):
        for model in self.models.values():
            text=report_text(model)
            for bad in (text+text,text.replace('UVM_FATAL : 0','UVM_FATAL : 1'),
                        text.replace('UVM FFT WIDTH','UVM FFT WRONG_WIDTH'),text.replace('modes=','wrong_modes='),
                        text.replace('input_stalls=0','input_stalls=1'),text.replace('error_cycles=0','error_cycles=1')):
                with self.subTest(case=model['case']),self.assertRaises(RuntimeError):parse_report(bad,model,'stream',1)
            with self.assertRaises(RuntimeError):parse_report(text,model,'stream',1,13)
            changed=dict(model,outputs=model['outputs']-1)
            with self.assertRaises(RuntimeError):parse_report(text,changed,'stream',1)

    def test_partial_terminal_and_sticky_error_recovery_required(self):
        for model in self.models.values():
            n=1<<model['log2n']
            for scenario,old,new in [('midreset',f'discarded={n} ',f'discarded={n-1} '),
                                     ('outreset',f'before_reset={n-1}',f'before_reset={n-2}'),
                                     ('outreset','terminal_resets=1','terminal_resets=0'),
                                     ('badlast','bad_completed=1','bad_completed=0'),
                                     ('badlast','error_cycles=50','error_cycles=0'),
                                     ('gaps','gaps=3','gaps=0'),
                                     ('stalled','output_stalls=50','output_stalls=0')]:
                with self.subTest(case=model['case'],scenario=scenario),self.assertRaises(RuntimeError):
                    parse_report(report_text(model,scenario).replace(old,new),model,scenario,0)

    def test_negative_must_fail_with_intended_uvm_category_before_completion(self):
        for tag in ('NUMERIC','PROTOCOL','STALL','ERROR'):
            text=f'UVM_FATAL @ 1: reporter [{tag}] fault\nUVM_FATAL : 1'
            verify_negative(text,13,tag)
            for bad,rc in ((text,0),(text.replace(f'[{tag}]','[OTHER]'),13),
                           (text.replace('UVM_FATAL : 1','UVM_FATAL : 0'),13),
                           (text+'\n'+report_text(next(iter(self.models.values()))),13)):
                with self.assertRaises(RuntimeError):verify_negative(bad,rc,tag)

    def test_parent_requires_every_native_geometry_and_negative(self):
        from run_fft import CASES as native,case_name
        self.assertEqual(set(CASES),{case_name(*row) for row in native})
        records={}
        for name,model in self.models.items():
            for active in (1,0):
                for scenario in SCENARIOS:records[f'{name}_{scenario}_reset_{active}']=parse_report(report_text(model,scenario),model,scenario,active)
                for key,(tag,_,_) in CONTROLS.items():records[f'{name}_negative_{key}_reset_{active}']=dict(returncode=13,detected_tag=tag)
        log=self.folder/'coverage.log';log.write_text('FFT fixture')
        original=dict(finish(begin(),[log]),status='PASS',case_selection='all',records=records)
        self.assertEqual(verified_fft_uvm_artifacts(original),[log])
        for fault in ('case','missing','width','reset_bool','negative','tag','rc0','bool_rc','artifact'):
            data=copy.deepcopy(original)
            if fault=='case':data['case_selection']='n4'
            elif fault=='missing':data['records'].pop('n1024_outreset_reset_0')
            elif fault=='width':data['records']['n64_w24_stream_reset_1']['width']=20
            elif fault=='reset_bool':data['records']['n4_stream_reset_1']['reset_active']=True
            elif fault=='negative':data['records'].pop('n4_boundaries_negative_error_clear_reset_0')
            elif fault=='tag':data['records']['n32_negative_direction_reset_1']['detected_tag']='PROTOCOL'
            elif fault=='rc0':data['records']['n4_negative_numeric_reset_1']['returncode']=0
            elif fault=='bool_rc':data['records']['n4_negative_numeric_reset_1']['returncode']=True
            else:data['artifact_hashes']={}
            with self.assertRaises(RuntimeError):verified_fft_uvm_artifacts(data)
        log.write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'artifact'):verified_fft_uvm_artifacts(original)


if __name__=='__main__':unittest.main()
