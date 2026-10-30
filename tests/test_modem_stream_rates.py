"""Physical modem timing: pre-edge sampling, vector aliases, capture bounds and evidence."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import modem_stream_rates as rates
from regression_evidence import begin,finish


def fixture(rx=False,simo=False,active=1,split=False):
    spec=rates.case_spec('qpsk_diff_rx' if simo else 'bpsk_rx' if rx else 'bpsk_tx')
    pins=rates.pin_spec(spec); codes={name:'v'+str(k) for k,name in enumerate(pins)}
    codes['wr_index']='A'  # Upper-case identifiers must not be lower-cased with values.
    lines=['$timescale 1ps $end'];parts={};bit_codes={}
    for name,(path,width) in pins.items():
        elements=path.split('/');lines.extend('$scope module '+scope+' $end' for scope in elements[:-1])
        if name=='wr_index' and split:
            for bit in range(width):
                code='Z'+str(bit);bit_codes[bit]=code
                lines.append(f'$var wire 1 {code} {elements[-1]} [{bit}] $end')
        else:lines.append(f'$var wire {width} {codes[name]} {elements[-1]} $end')
        lines.extend('$upscope $end' for scope in elements[:-1])
    lines.extend(['$enddefinitions $end','#0','$dumpvars'])
    values={name:0 for name in pins};values.update(rst=active,s_ready=1,m_ready=1)
    if rx:values.update(cfg_ready=1)
    if simo:values.update(gain_ready=1)
    def encoded(name,value):
        width=pins[name][1]
        raw=value if isinstance(value,str) else format(value,'b')
        if name=='wr_index' and split:
            raw=raw.rjust(width,'0')
            return [raw[width-1-bit]+code for bit,code in bit_codes.items()]
        return [raw+codes[name] if width==1 else 'b'+raw+' '+codes[name]]
    for name,value in values.items():lines.extend(encoded(name,value))
    lines.append('$end');changes={};nba={}
    def at(cycle,**values):changes.setdefault(cycle,{}).update(values)
    at(1,rst=1-active)
    if rx:
        at(1,cfg_valid=1);at(192,cfg_last=1);at(193,cfg_valid=0,cfg_last=0)
        nba[192]=dict(configured=1)
        start=195
        at(start+2,wr_en=1,wr_frame=0,wr_index=0,occupied=1)
        at(start+3,wr_index=1,acquisition_valid=1)
        at(start+4,wr_en=0,acquisition_valid=0)
        if simo:
            at(193,gain_valid=1);at(194,gain_valid=0);nba[193]=dict(gain_configured=1)
    else:start=1
    at(start,s_valid=1);at(start+1,s_last=1);at(start+2,s_valid=0,s_last=0)
    # NBA m_valid/last updates are visible only on the following sampled edge.
    nba.setdefault(start+3 if rx else start,{}).update(m_valid=1)
    nba.setdefault(start+4 if rx else start+1,{}).update(m_last=1)
    nba.setdefault(start+5 if rx else start+2,{}).update(m_valid=0,m_last=0)
    end=start+7
    for cycle in range(end):
        if cycle:
            lines.append('#'+str(cycle*10000));lines.extend(encoded('clk',0))
            for name,value in changes.get(cycle,{}).items():lines.extend(encoded(name,value))
        lines.append('#'+str(cycle*10000+5000));lines.extend(encoded('clk',1))
        for name,value in nba.get(cycle,{}).items():lines.extend(encoded(name,value))
    model=dict(name=spec['name'],direction=spec['direction'],simo=simo,input_lengths=[2],output_lengths=[2],memory_depth=16640 if rx else None,filter_tail=0)
    return '\n'.join(lines)+'\n',pins,model,codes


class TestModemStreamRates(unittest.TestCase):
    def measure(self,text,pins,model,active=1):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pins.vcd';path.write_text(text)
            return rates.measure(path,model,active,pins)

    def test_preedge_nba_and_both_polarities(self):
        for active in (1,0):
            text,pins,model,_=fixture(active=active)
            row=self.measure(text,pins,model,active)['per_frame'][0]
            self.assertEqual(row['input']['first_cycle'],1)
            self.assertEqual(row['output']['first_cycle'],2)
            self.assertEqual(row['first_output_latency_cycles'],1)
            self.assertEqual(row['final_output_latency_cycles'],1)
            self.assertTrue(row['output']['every_cycle'])

    def test_capture_acquisition_and_simo_units(self):
        for simo in (False,True):
            text,pins,model,_=fixture(rx=True,simo=simo)
            measured=self.measure(text,pins,model);row=measured['per_frame'][0]
            self.assertEqual(row['acquisition_latency_cycles'],3)
            self.assertEqual(row['input_samples_at_acquisition'],2)
            self.assertEqual(row['capture_high_water_samples'],2)
            self.assertEqual(row['capture_headroom_samples'],16638)
            self.assertEqual(measured['configuration']['transfers'],192)
            self.assertEqual(measured['configuration']['final_transfer_to_configured_cycles'],0)
            self.assertEqual(measured['capture_memory']['peak_occupied_buffers'],1)
            self.assertEqual(measured['gain_configuration'] is not None,simo)
            self.assertEqual('two SIMO branches' in measured['input_unit'],simo)

    def test_split_vector_ports_case_sensitive_identifiers(self):
        a,pins,model,_=fixture(rx=True);b,_,_,_=fixture(rx=True,split=True)
        self.assertEqual(self.measure(a,pins,model),self.measure(b,pins,model))
        b=b.replace('$var wire 1 Z14 wr_index [14] $end\n','')
        with self.assertRaisesRegex(ValueError,'Complete unique'):self.measure(b,pins,model)

    def test_missing_unknown_width_period_and_reset_rejected(self):
        text,pins,model,codes=fixture()
        cases=[text.replace(f'$var wire 1 {codes["clk"]} clk $end\n',''),
               text.replace('1'+codes['s_valid'],'x'+codes['s_valid']),
               text.replace('#25000','#24000'),text.replace('#25000','#14000'),
               text.replace('$timescale 1ps','$timescale 10ps'),
               text.replace(f'$var wire 1 {codes["s_ready"]}',f'$var wire 2 {codes["s_ready"]}'),
               text.replace('#20000\n','#20000\n1'+codes['rst']+'\n')]
        for bad in cases:
            with self.subTest(bad=bad[-100:]),self.assertRaises(ValueError):self.measure(bad,pins,model)
        with self.assertRaises(ValueError):self.measure(text,pins,model,True)

    def test_partial_frames_and_sink_backpressure_rejected(self):
        text,pins,model,codes=fixture()
        for name in ('s_last','m_last','m_ready'):
            bad=text.replace('1'+codes[name],'0'+codes[name])
            with self.subTest(pin=name),self.assertRaises(ValueError):self.measure(bad,pins,model)
        with self.assertRaisesRegex(RuntimeError,'immutable frame'):self.measure(text,pins,dict(model,input_lengths=[3]))

    def test_capture_address_bounds_counts_and_acquisition_causality(self):
        text,pins,model,codes=fixture(rx=True)
        for bad in (text.replace('b1 '+codes['wr_index'],'b10 '+codes['wr_index']),
                    text.replace('0'+codes['wr_frame'],'1'+codes['wr_frame'])):
            with self.assertRaisesRegex(ValueError,'capture-memory'):self.measure(bad,pins,model)
        with self.assertRaisesRegex(RuntimeError,'capacity'):self.measure(text,pins,dict(model,memory_depth=1))
        with self.assertRaisesRegex(RuntimeError,'write count'):self.measure(text,pins,dict(model,filter_tail=32))
        with self.assertRaisesRegex(RuntimeError,'acquisition/configuration'):
            self.measure(text.replace('1'+codes['acquisition_valid'],'0'+codes['acquisition_valid']),pins,model)
        # Move the event earlier than the first input, while preserving one pulse.
        bad=text.replace('1'+codes['acquisition_valid'],'0'+codes['acquisition_valid']).replace('#15000\n','#15000\n1'+codes['acquisition_valid']+'\n').replace('#25000\n','#25000\n0'+codes['acquisition_valid']+'\n')
        with self.assertRaisesRegex(RuntimeError,'Non-causal acquisition'):self.measure(bad,pins,model)

    def test_all_production_profiles_and_lossless_tlast_geometry(self):
        self.assertEqual(len(rates.CASES),34)
        self.assertEqual(set(rates.PROFILES),{'bpsk',*rates.RX_PROFILES,'oqpsk','msk','gmsk'})
        for name in rates.CASES:
            spec=rates.case_spec(name)
            self.assertEqual(spec['direction']=='rx','occupied' in rates.pin_spec(spec))
            self.assertEqual(name=='qpsk_diff_rx','gain_valid' in rates.pin_spec(spec))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'vectors.txt';path.write_text('3\n1 2 3 4 0\n5 6 7 8 1\n9 0 1 2 1\n')
            self.assertEqual(rates.vector_lengths(path,5),[2,1])
            with self.assertRaises(ValueError):rates.vector_lengths(path,3)
            path.write_text('1\n0 0 0\n')
            with self.assertRaisesRegex(ValueError,'TLAST'):rates.vector_lengths(path,3)

    def test_parent_recomputes_and_rejects_forged_or_incomplete_evidence(self):
        text,pins,model,codes=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'tools').mkdir();(root/'tools/source.py').write_text('# fixture\n')
            child=root/'build/rtl/bpsk_uvm/all_results.json';child.parent.mkdir(parents=True);child.write_text('{}\n')
            records={};files=[child]
            for active in (1,0):
                wave,_,_,_=fixture(active=active)
                work=root/'build/rtl/modem_rates'/f'bpsk_tx_reset_{active}';work.mkdir(parents=True)
                (work/'pins.vcd').write_text(wave);(work/'run.log').write_text('Numeric child checked independently\n');(work/'model.json').write_text(json.dumps(model))
                records[f'bpsk_tx_reset_{active}']=self.measure(wave,pins,model,active)
                files.extend([work/file for file in ('pins.vcd','run.log','model.json')])
            original=dict(finish(begin(root),files,root),status='PASS',records=records,case_selection='all',python_tests=rates.PYTHON_TESTS)
            with patch.object(rates,'CASES',('bpsk_tx',)),patch.object(rates,'validate_children',return_value=[child]),patch.object(rates,'model_for',return_value=(model,[])),patch.object(rates,'numeric_record'):
                self.assertEqual(set(rates.verified_artifacts(original,root)),set(files))
                for fault in ('selection','case','bool','latency','artifact'):
                    data=copy.deepcopy(original)
                    if fault=='selection':data['case_selection']='bpsk_tx'
                    elif fault=='case':data['records'].pop('bpsk_tx_reset_0')
                    elif fault=='bool':data['records']['bpsk_tx_reset_0']['reset_active']=False
                    elif fault=='latency':data['records']['bpsk_tx_reset_1']['per_frame'][0]['first_output_latency_cycles']=0
                    else:data['artifact_hashes'].pop('build/rtl/modem_rates/bpsk_tx_reset_1/pins.vcd')
                    with self.subTest(fault=fault),self.assertRaises(RuntimeError):rates.verified_artifacts(data,root)
                (root/'build/rtl/modem_rates/bpsk_tx_reset_0/pins.vcd').write_text(text)
                with self.assertRaisesRegex(RuntimeError,'artifact'):rates.verified_artifacts(original,root)


if __name__=='__main__':unittest.main()
