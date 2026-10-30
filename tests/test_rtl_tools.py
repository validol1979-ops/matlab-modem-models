"""Guard strict timing/warning acceptance and the single-source constraints."""
from pathlib import Path
import copy
import json
import sys
import tempfile
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from rtl_constraints import generate,load
from run_rtl_synth import warnings,timing_acceptance
from run_stream_cfg_priority import check_run


class RTLToolsTests(unittest.TestCase):
    def test_cfg_priority_regression_requires_diagnostic_and_exit_code(self):
        marker='PASS STREAM CFG priority family=0'
        check_run(0,marker,marker)
        check_run(13,'** Fatal: [NUMERIC] mismatch',marker,negative=True)
        for rc,text in ((0,'[NUMERIC] mismatch'),(1,'[NUMERIC] mismatch'),(13,'[TIMEOUT]'),(13,'[NUMERIC] merely echoed'),
                        (13,'[NUMERIC] mismatch\n'+marker)):
            with self.assertRaises(RuntimeError):check_run(rc,text,marker,negative=True)
        for rc,text in ((1,marker),(0,''),(0,marker+'\n** Fatal: failed'),(0,marker+'\n[CONFIG_ARB] failed')):
            with self.assertRaises(RuntimeError):check_run(rc,text,marker)

    def test_constraints_equivalent_clock_and_io_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec=generate(ROOT/'rtl/constraints/common.yaml',tmp)
            xdc=(Path(tmp)/'timing.xdc').read_text().splitlines()
            sdc=(Path(tmp)/'timing.sdc').read_text().splitlines()
            self.assertEqual(xdc[:2],sdc[:2]);self.assertEqual(xdc[3:7],sdc[3:]);self.assertEqual(xdc[7],'set_load 5.000000000 [all_outputs]')
            self.assertIn('10.000000000',xdc[0]);self.assertEqual(spec['clock']['frequency_mhz'],100)

    def test_invalid_timing_and_tcl_injection_rejected(self):
        spec=load(ROOT/'rtl/constraints/common.yaml')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'timing.yaml'
            for clock in ({'port':'clk; exit','frequency_mhz':100,'uncertainty_ns':.2},
                          {'port':'clk','frequency_mhz':0,'uncertainty_ns':.2},
                          {'port':'clk','frequency_mhz':float('nan'),'uncertainty_ns':.2}):
                value=copy.deepcopy(spec);value['clock']=clock;path.write_text(yaml.safe_dump(value))
                with self.assertRaises(ValueError):load(path)

    def test_unknown_or_critical_warning_is_an_error(self):
        allowed={'10335':'Foreign attribute'}
        self.assertEqual(len(warnings('Warning (10335): ignored attribute','altera',allowed)),1)
        for line in ('Warning (999): surprise','Critical Warning (10335): unexpected','    Critical Warning (10335): nested'):
            with self.assertRaises(RuntimeError):warnings(line,'altera',allowed)
        with self.assertRaises(RuntimeError):warnings('WARNING: [Route 35-328] Timing failed','xilinx',{})

    def test_only_unused_rom_write_ports_are_allowed(self):
        policy=json.loads((ROOT/'rtl/warnings.json').read_text())['altera']
        good='Warning (10030): Net "memory.we_a" at sync_rom.sv(9) has no driver or initial value, using a default initial value \'0\''
        self.assertEqual(len(warnings(good,'altera',policy)),1)
        for bad in (good.replace('memory.we_a','memory.rd_data'),good.replace('sync_rom.sv','sync_ram.sv'),good.replace('Warning','Critical Warning',1)):
            with self.assertRaises(RuntimeError):warnings(bad,'altera',policy)

    def test_pilot_warning_exceptions_do_not_hide_missing_logic(self):
        policy=json.loads((ROOT/'rtl/warnings.json').read_text())
        good='Warning (10036): Verilog HDL or VHDL warning at bpsk_fir.sv(16): object "unused_im" assigned a value but never read'
        self.assertEqual(len(warnings(good,'altera',policy['altera'])),1)
        with self.assertRaises(RuntimeError):warnings(good.replace('unused_im','training'),'altera',policy['altera'])
        good="WARNING: [Synth 8-3936] Found unconnected internal register 'intercept_reg' and it is trimmed from '64' to '48' bits. [/tmp/bpsk_acquire.sv:123]"
        self.assertEqual(len(warnings(good,'xilinx',policy['xilinx'])),1)
        with self.assertRaises(RuntimeError):warnings(good.replace('intercept_reg','valid_reg'),'xilinx',policy['xilinx'])
        with self.assertRaises(RuntimeError):warnings('WARNING: [Route 35-328] Router estimated timing not met.','xilinx',policy['xilinx'])

    def test_slack_required_including_cyclone_margin(self):
        spec=load(ROOT/'rtl/constraints/common.yaml')
        timing_acceptance(.1,.01,spec,'xilinx');timing_acceptance(1,.01,spec,'altera')
        for setup,hold,vendor in ((0,.1,'xilinx'),(2,0,'altera'),(.99,.1,'altera'),(float('nan'),1,'xilinx')):
            with self.assertRaises(RuntimeError):timing_acceptance(setup,hold,spec,vendor)


if __name__=='__main__':unittest.main()
