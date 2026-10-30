"""Pre-edge VCD timing must survive NBA changes and reject incomplete/forged traffic."""
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
import copy,json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from dsp_stream_rates import SIGNALS,read_vcd,measure,beats_summary


def fixture():
    names=['clk',*SIGNALS];codes={name:chr(33+k) for k,name in enumerate(names)}
    lines=['$timescale 1ps $end','$scope module dsp_uvm_top $end',f'$var reg 1 {codes["clk"]} clk $end',
           '$scope module bus $end']
    lines.extend(f'$var wire 1 {codes[name]} {name} $end' for name in SIGNALS)
    lines.extend(['$upscope $end','$upscope $end','$enddefinitions $end','#0','$dumpvars'])
    initial={name:0 for name in names};initial.update(rst=1,s_ready=1,m_ready=1,w_ready=1)
    lines.extend(str(value)+codes[name] for name,value in initial.items());lines.append('$end')
    changes=[(5000,dict(clk=1)),(10000,dict(clk=0,rst=0,configured=1,s_valid=1)),
             (15000,dict(clk=1,m_valid=1)),(20000,dict(clk=0,s_last=1)),
             (25000,dict(clk=1,m_last=1)),(30000,dict(clk=0,s_valid=0)),
             (35000,dict(clk=1,m_valid=0)),(40000,dict(clk=0))]
    for time,pins in changes:
        lines.append('#'+str(time));lines.extend(str(value)+codes[name] for name,value in pins.items())
    return '\n'.join(lines)+'\n',codes


MODEL=dict(name='fixture',lengths=[(2,2)],weight_lengths=[0],weight_port=False,config_rows=0)


class TestDspStreamRates(unittest.TestCase):
    def test_preedge_handshakes_ignore_same_timestamp_nba_values(self):
        text,codes=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pins.vcd';path.write_text(text)
            result=read_vcd(path,1)
            self.assertEqual(result['frames']['s'],[[1,2]])
            self.assertEqual(result['frames']['m'],[[2,3]])
            measured=measure(path,MODEL,1)['per_frame'][0]
            self.assertEqual(measured['first_output_latency_cycles'],1)
            self.assertEqual(measured['final_output_latency_cycles'],1)
            self.assertTrue(measured['input']['every_cycle']);self.assertTrue(measured['output']['every_cycle'])

    def test_intervals_include_bubbles_and_singletons_remain_undefined(self):
        result=beats_summary([7,8,12,13,14,20])
        self.assertEqual(result['minimum_interval'],1);self.assertEqual(result['maximum_interval'],6)
        self.assertEqual(result['adjacent_pairs'],3);self.assertEqual(result['longest_consecutive'],3)
        self.assertFalse(result['every_cycle']);self.assertIsNone(beats_summary([10])['every_cycle'])
        for bad in ([],[1,1],[2,1]):
            with self.assertRaises(ValueError):beats_summary(bad)

    def test_missing_clock_unknown_controls_period_and_time_order_rejected(self):
        text,codes=fixture()
        bad_cases=[text.replace(f'$var reg 1 {codes["clk"]} clk $end\n',''),
                   text.replace('1'+codes['s_valid'],'x'+codes['s_valid']),
                   text.replace('#25000','#24000'),text.replace('#25000','#14000'),
                   text.replace('$timescale 1ps','$timescale 10ps')]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pins.vcd'
            for bad in bad_cases:
                path.write_text(bad)
                with self.assertRaises(ValueError):read_vcd(path,1)
            path.write_text(text)
            with self.assertRaises(ValueError):read_vcd(path,True)

    def test_missing_last_geometry_and_unexpected_reset_rejected(self):
        text,codes=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pins.vcd'
            for bad in (text.replace('1'+codes['m_last'],'0'+codes['m_last']),
                        text.replace('#20000\n','#20000\n1'+codes['rst']+'\n')):
                path.write_text(bad)
                with self.assertRaises(ValueError):read_vcd(path,1)
            path.write_text(text)
            with self.assertRaises(RuntimeError):measure(path,dict(MODEL,lengths=[(3,2)]),1)

    def test_parent_recomputes_both_polarities_and_rejects_forged_records(self):
        import dsp_stream_rates as rates
        from regression_evidence import begin,finish
        text,codes=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'tools').mkdir();(root/'tools/snapshot.py').write_text('# source fixture\n')
            child=root/'build/rtl/dsp_uvm/all_results.json';child.parent.mkdir(parents=True);child.write_text('{}\n')
            model_path=child.parent/'fixture_vectors/model.json';model_path.parent.mkdir();model_path.write_text(json.dumps(MODEL))
            records={};files=[child,model_path]
            for active in (1,0):
                work=root/'build/rtl/dsp_rates'/f'fixture_reset_{active}';work.mkdir(parents=True)
                vcd=text if active else text.replace('1'+codes['rst'],'X'+codes['rst']).replace('0'+codes['rst'],'1'+codes['rst']).replace('X'+codes['rst'],'0'+codes['rst'])
                (work/'pins.vcd').write_text(vcd);(work/'run.log').write_text('Numerical child checked separately')
                records[f'fixture_reset_{active}']=measure(work/'pins.vcd',MODEL,active);files.extend([work/'pins.vcd',work/'run.log'])
            original=dict(finish(begin(root),files,root),status='PASS',case_selection='all',records=records,python_tests=5)
            with patch.object(rates,'CASES',{'fixture':{}}),patch('run_tests.verified_dsp_uvm_artifacts',return_value=[]):
                self.assertEqual(set(rates.verified_artifacts(original,root)),set(files))
                for fault in ('partial','missing','bool','latency','artifact'):
                    data=copy.deepcopy(original)
                    if fault=='partial':data['case_selection']='fixture'
                    elif fault=='missing':data['records'].pop('fixture_reset_0')
                    elif fault=='bool':data['records']['fixture_reset_0']['reset_active']=False
                    elif fault=='latency':data['records']['fixture_reset_1']['per_frame'][0]['first_output_latency_cycles']=0
                    else:data['artifact_hashes'].pop('build/rtl/dsp_rates/fixture_reset_1/pins.vcd')
                    with self.subTest(fault=fault),self.assertRaises(RuntimeError):rates.verified_artifacts(data,root)
                (root/'build/rtl/dsp_rates/fixture_reset_0/pins.vcd').write_text(text)
                with self.assertRaisesRegex(RuntimeError,'artifact'):rates.verified_artifacts(original,root)


if __name__=='__main__':unittest.main()
