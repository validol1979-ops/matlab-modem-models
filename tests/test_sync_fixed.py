"""Integer Costas and Gardner loops (sync_fixed) against research_core.run('costas'/'timing')."""
from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
sys.path.insert(0,str(ROOT/'tools'))
import sync_fixed as s
from research_core import run
from bpsk_fixed import interp
from modem_core import load_config,transmit,rrc_taps,cubic
from sat_diag import SatTrace
from sync_scenarios import (costas_scenario, costas_slip_scenario, costas_slip_metrics,
                            timing_scenario, costas_metrics, timing_metrics)


def q15(z):return [(max(-131072,min(131071,int(round(complex(v).real*32768)))),max(-131072,min(131071,int(round(complex(v).imag*32768))))) for v in z]
def complex_of(rows):return np.array([re+1j*im for re,im in rows])/32768


class TestSyncFixed(unittest.TestCase):
    def setUp(self):
        self.cfg=load_config(ROOT/'modems/qpsk_script_costas/config.json')
        rng=np.random.default_rng(0);self.labels=rng.integers(0,4,768)
        self.symbols=(np.array(self.cfg['constellation'])@[1,1j])[self.labels]

    def test_costas_model_case(self):
        wave=self.symbols*np.exp(1j*(.3+.006*np.arange(len(self.symbols))))
        values,phases=s.costas(q15(wave),s.costas_gains(.08,.001));y=complex_of(values)
        expected=run('costas',[.08,.001],wave);n=len(wave)
        # The loop locks like the floating one: same residual after 200 symbols.
        self.assertLess(np.mean(abs(y[200:]-self.symbols[200:])**2),.01*np.mean(abs(wave[200:]-self.symbols[200:])**2))
        self.assertLess(np.max(abs(y[200:]-expected[200:n])),2e-3)
        phase=np.array(phases)/2**32*2*np.pi;reference=expected[n:].real
        self.assertLess(np.max(abs(np.angle(np.exp(1j*(phase[200:]-reference[200:]))))),2e-3)

    def test_gardner_model_case(self):
        shaped=transmit(self.cfg,self.labels)['waveform'];matched=np.convolve(shaped,rrc_taps(8,32,1))
        delayed=cubic(matched,np.arange(len(matched))-1.25)
        values,positions=s.timing(q15(delayed),8,700,s.timing_gains(32,.1,.00005))
        y=complex_of(values);expected=run('timing',[8,700,32,.1,.00005],delayed)
        before=np.mean(abs(cubic(delayed,32+8*np.arange(700))[300:]-self.symbols[300:700])**2)
        self.assertLess(np.mean(abs(y[300:700]-self.symbols[300:700])**2),.4*before)
        # The fixed loop follows the floating positions to a fraction of a sample.
        self.assertLess(np.max(abs(np.array(positions)/65536-expected[700:].real)),.05)
        self.assertLess(np.max(abs(y-expected[:700])),.05)

    def test_costas_pipelined_reduces_to_the_per_sample_loop(self):
        # Delay one: the error of a sample is applied before the next one is rotated, i.e. exactly
        # costas(). Every gain set, including the zero-gain control.
        rng=np.random.default_rng(3)
        samples=[(int(re),int(im)) for re,im in rng.integers(-131072,131072,size=(300,2))]
        for gains in ((.08,.001),(.3,.01),(.02,.0001),(0,0)):
            k=s.costas_gains(*gains)
            self.assertEqual(s.costas(samples,k),s.costas_pipelined(samples,k,1))

    def test_costas_pipelined_delay_and_gap_semantics(self):
        # A larger delay changes the trajectory (it is a different loop, not an optimisation), and a
        # gap of two advances is not the same as a dense stream: both are the parameters the RTL
        # bench measures. Backpressure stalls are NOT gaps (they remove whole advances).
        k=s.costas_gains(.08,.001)
        wave=q15(self.symbols[:300]*np.exp(1j*(.3+.006*np.arange(300))))
        dense=s.costas_pipelined(wave,k,10)
        self.assertNotEqual(dense,s.costas_pipelined(wave,k,1))
        self.assertEqual(dense,s.costas_pipelined(wave,k,10,[1]*len(wave)))
        bubbled=s.costas_pipelined(wave,k,10,[2 if n%7==0 else 1 for n in range(len(wave))])
        self.assertNotEqual(dense[0],bubbled[0])

    def test_costas_pipelined_rejects_impossible_arguments(self):
        wave=[(1000,1000)]*4
        k=s.costas_gains(.08,.001)
        with self.assertRaises(ValueError):s.costas_pipelined(wave,k,0)
        with self.assertRaises(ValueError):s.costas_pipelined(wave,k,2,[1,1])
        with self.assertRaises(ValueError):s.costas_pipelined(wave,k,2,[1,0,1,1])

    def test_rejects(self):
        with self.assertRaises(ValueError):s.costas_gains(-1,0)
        with self.assertRaises(ValueError):s.timing([(0,0)]*10,1,3,(0,0,0))

    def test_costas_phase_jump_acquisition_and_recovery(self):
        _, _, _, metrics, reference, disabled = costas_scenario()
        self.assertTrue(all(metrics[k] for k in ('acquired','lost','recovered')),metrics)
        control = costas_metrics(disabled, disabled, reference)
        self.assertFalse(control['acquired'])
        self.assertFalse(control['recovered'])

    def test_costas_quadrant_cycle_slip(self):
        """costas_slip_scenario has the costas_scenario API and reports a QUADRANT CHANGE: the two
        median phase errors differ by about -90 degrees while the loop stays locked modulo 90. The
        two medians alone do not prove a single continuous cycle slip, and this test does not claim
        one; the disabled loop (gains 0,0) is the negative control."""
        samples, values, phases, metrics, reference, disabled = costas_slip_scenario()
        gains = s.costas_gains(.08, .001)
        # Bit-exact outputs of sync_fixed.costas on the returned inputs, plus the known reference.
        self.assertEqual((values, phases), s.costas(samples, gains))
        self.assertEqual(len(samples), len(reference))
        self.assertEqual(len(values), len(phases))
        self.assertAlmostEqual(reference[0], .3)
        self.assertAlmostEqual(reference[299] - reference[298], .006)
        self.assertAlmostEqual(reference[300] - reference[299], .006 + np.deg2rad(100))
        self.assertAlmostEqual(reference[301] - reference[300], .006)
        # The disabled control: zero gains never rotate, so its phase is 0 for every sample.
        self.assertEqual(disabled, [0] * len(samples))
        # The enabled loop: locked before the jump, still locked modulo 90 degrees after it, but its
        # true phase sits one quadrant away (about -90 degrees of median shift).
        self.assertLess(metrics['before_mod90_rms_deg'], 1)
        self.assertLess(metrics['recovery_mod90_rms_deg'], 1)
        self.assertTrue(metrics['locked_mod90'])
        self.assertLess(abs(metrics['quadrant_change_deg'] + 90), 2)
        self.assertLess(metrics['quadrant_change_deg'], -88)
        self.assertLess(abs(metrics['recovery_true_rms_deg'] - 90), 2)
        self.assertTrue(metrics['quadrant_change_observed'])
        self.assertTrue(metrics['slipped'], metrics)
        self.assertTrue(metrics['acquired'])
        self.assertTrue(metrics['disabled_rejected'])
        # The disabled loop holds neither view of the phase error -> not a slip, a free-running loop.
        self.assertFalse(metrics['disabled_locked'])
        self.assertGreater(metrics['disabled_recovery_mod90_rms_deg'], 20)
        self.assertGreater(metrics['disabled_recovery_true_rms_deg'], 20)
        # Recompute from the evidence, then feed the disabled loop as the measured stream.
        self.assertEqual(costas_slip_metrics(phases, disabled, reference), metrics)
        self.assertFalse(costas_slip_metrics(disabled, disabled, reference)['slipped'])
        self.assertFalse(costas_slip_metrics(disabled, disabled, reference)['disabled_locked'])

    def test_costas_slip_metrics_rejects_missing_or_invalid_evidence(self):
        _, _, phases, _, reference, disabled = costas_slip_scenario()
        for bad_phases, bad_disabled, bad_reference in (
                (phases[:-1], disabled, reference),
                (phases[:849], disabled[:849], reference[:849]),
                (phases, disabled, np.full(900, np.nan)),
                (np.full(900, np.inf), disabled, reference),
                (phases, np.zeros((900, 1)), reference)):
            with self.subTest(reference_shape=np.shape(bad_reference), phases_len=len(bad_phases)):
                with self.assertRaises(ValueError):
                    costas_slip_metrics(bad_phases, bad_disabled, bad_reference)
        # A phase capture rotated by one quadrant from the start cannot prove acquisition in the
        # transmitted quadrant even if both measured windows are locked modulo 90 degrees.
        shifted = [s.wrap32(v + (1 << 30)) for v in phases]
        shifted_metrics = costas_slip_metrics(shifted, disabled, reference)
        self.assertTrue(shifted_metrics['locked_mod90'])
        self.assertFalse(shifted_metrics['acquired'])
        self.assertFalse(shifted_metrics['slipped'])

    def test_costas_quadrant_slip_no_jump_control(self):
        """jump_degrees=0: the same signal without the carrier step keeps the true phase, so the two
        medians agree, the true and the modulo 90 views coincide and no quadrant change shows up."""
        samples, values, phases, metrics, reference, disabled = costas_slip_scenario(jump_degrees=0)
        self.assertEqual((values, phases), s.costas(samples, s.costas_gains(.08, .001)))
        self.assertAlmostEqual(reference[300] - reference[299], .006)
        self.assertFalse(metrics['quadrant_change_observed'])
        self.assertFalse(metrics['slipped'], metrics)
        self.assertLess(abs(metrics['quadrant_change_deg']), 1)
        self.assertLess(metrics['recovery_true_rms_deg'], 1)
        self.assertTrue(metrics['locked_mod90'])
        self.assertEqual(disabled, [0] * len(samples))
        self.assertFalse(metrics['disabled_locked'])
        self.assertGreater(metrics['disabled_recovery_mod90_rms_deg'], 20)

    def test_costas_slip_transaction_vectors_and_metadata(self):
        """The model configuration appends the 900 sample slip transaction AFTER every existing
        Costas transaction: the rows before row_start are byte-identical to a replay of the old
        pipeline on the same RNG stream (the slip draws no random numbers), the transaction block is
        the bit-exact scenario output and cl_slip.json is the metadata of that exact row range."""
        import sync_cases as c
        seed, transactions = 7, 2
        gains = s.costas_gains(*c.COSTAS_MODEL)
        cfg, rng = c.pilot(), np.random.default_rng(seed)
        prefix = []
        for index in range(transactions):  # the streamed transactions, in the original rng order
            samples = c.quantize(c.costas_signal(cfg, rng, index == 0))
            prefix.extend((re, im, int(k == len(samples) - 1)) for k, (re, im) in enumerate(samples))
        overload = c.costas_overload()  # the overload transaction
        prefix.extend((re, im, int(k == len(overload) - 1)) for k, (re, im) in enumerate(overload))
        scenario, *_ = c.costas_scenario()  # the tracking scenario transaction
        prefix.extend((re, im, int(k == len(scenario) - 1)) for k, (re, im) in enumerate(scenario))
        work = Path(tempfile.mkdtemp())
        try:
            folder = work / 'model'
            report = c.vectors(folder, transactions=transactions, seed=seed)
            meta = json.loads((folder / 'cl_slip.json').read_text())
            inputs = [tuple(map(int, line.split()))
                      for line in (folder / 'cl_in.txt').read_text().splitlines()[1:]]
            outputs = [tuple(map(int, line.split()))
                       for line in (folder / 'cl_out.txt').read_text().splitlines()[1:]]
            start, stop = meta['row_start'], meta['row_stop']
            # 0-based data rows, stop exclusive; later disturbance transactions follow this one.
            self.assertEqual((report['cl_inputs'], report['cl_outputs']), (len(inputs), len(outputs)))
            self.assertEqual(len(inputs), len(outputs))
            self.assertTrue(0 <= start < stop <= len(inputs), (start, stop, len(inputs)))
            self.assertEqual(stop+2000+12*2400, len(inputs))
            self.assertEqual(stop - start, 900)
            self.assertEqual(report['cl_slip_rows'], [start, stop])
            self.assertEqual(report['costas_transactions'], transactions + 17)
            # Exact prefix of the pre-existing transactions on the unchanged RNG stream.
            self.assertEqual(inputs[:start], prefix)
            self.assertEqual(len(prefix), start)
            samples, values, phases, metrics, reference, disabled = costas_slip_scenario()
            self.assertEqual(meta['metrics'], metrics)
            self.assertTrue(meta['metrics']['slipped'])
            self.assertIs(meta['rtl_verified'], False)
            self.assertEqual(meta['reference_file'], 'cl_slip_reference.txt')
            self.assertEqual(meta['disabled_file'], 'cl_slip_disabled.txt')
            disabled_rows = (folder / meta['disabled_file']).read_text().splitlines()
            self.assertEqual(int(disabled_rows[0]), len(disabled))
            self.assertEqual([int(row) for row in disabled_rows[1:]], disabled)
            self.assertEqual(inputs[start:stop],
                             [(re, im, int(k == len(samples) - 1))
                              for k, (re, im) in enumerate(samples)])
            self.assertEqual(outputs[start:stop],
                             [(re, im, phase, int(k == len(samples) - 1)) for k,
                              ((re, im), phase) in enumerate(zip(values, phases))])
            # The reference file: save() header + one float radian per row, in range of the scenario.
            self.assertEqual(meta['reference_file'], 'cl_slip_reference.txt')
            rows = (folder / meta['reference_file']).read_text().splitlines()
            self.assertEqual(rows[0], '900')
            self.assertEqual(len(rows), 901)
            written = [float(row) for row in rows[1:] if row.strip()]
            self.assertEqual(len(written), 900)
            for value, expected in zip(written, reference):
                self.assertEqual(value, float(expected))  # save() writes a round trip repr
            self.assertAlmostEqual(written[300] - written[299], .006 + np.deg2rad(100))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_costas_slip_transaction_only_for_the_model_configuration(self):
        """Any other configuration keeps its stream untouched: cl_slip.json is JSON null, no
        reference file is written and the transaction count does not grow by the slip."""
        import sync_cases as c
        work = Path(tempfile.mkdtemp())
        try:
            for name, costas, timing in (('off', (0, 0), (2, 30, 3.5, 0, 0)),
                                         ('random', (.02, .0001), (4, 40, 10, .05, .0001))):
                folder = work / name
                report = c.vectors(folder, costas, timing, transactions=1, seed=11)
                self.assertEqual((folder / 'cl_slip.json').read_text().strip(), 'null')
                self.assertFalse((folder / 'cl_slip_reference.txt').exists())
                self.assertFalse((folder / 'cl_slip_disabled.txt').exists())
                self.assertIsNone(report['cl_slip'])
                self.assertIsNone(report['cl_slip_rows'])
                self.assertIsNone(report['cl_tracking'])
                self.assertEqual(report['costas_transactions'], 2)  # streamed + overload only
                rows = (folder / 'cl_in.txt').read_text().splitlines()
                self.assertEqual(int(rows[0]), len(rows) - 1)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_gardner_delay_excursion_acquisition_and_recovery(self):
        _, _, _, metrics, reference, disabled = timing_scenario()
        self.assertTrue(all(metrics[k] for k in ('acquired','lost','recovered')),metrics)
        control = timing_metrics(disabled, disabled, reference)
        self.assertFalse(control['acquired'])
        self.assertFalse(control['recovered'])

    def test_timing_gradient_stats_bit_exact(self):
        """stats=SatTrace only observes: outputs/positions are bit-identical to the default call,
        one 'gradient' evaluation per output and deterministic pos/neg counts on the model case."""
        shaped=transmit(self.cfg,self.labels)['waveform'];matched=np.convolve(shaped,rrc_taps(8,32,1))
        delayed=q15(cubic(matched,np.arange(len(matched))-1.25))
        gains=s.timing_gains(32,.1,.00005)
        values,positions=s.timing(delayed,8,700,gains)
        trace=SatTrace()
        traced_values,traced_positions=s.timing(delayed,8,700,gains,stats=trace)
        self.assertEqual(traced_values,values);self.assertEqual(traced_positions,positions)
        self.assertEqual(trace.evaluations['gradient'],700)
        again=SatTrace();s.timing(delayed,8,700,gains,stats=again)
        self.assertEqual(again.counts,trace.counts)
        # The model case is full scale: the gradient really does leave the +/-2^30 rails there.
        self.assertGreater(trace.counts['gradient']['pos'],0)
        self.assertGreater(trace.counts['gradient']['neg'],0)

    def test_timing_gradient_step_clips_both_rails(self):
        """Deterministic high-amplitude step: +full, -full, +full with zero gains (the trajectory is
        fixed at position + t*sps), crossing the two step edges at different alignments so the
        preclamp gradient exceeds +ONE30 AND -ONE30. Also checks the unclamped gradients behind the
        two events against a direct interp() recomputation and that stats never change the outputs."""
        full=(1<<17)-1;pos=(full,full);neg=(-full-1,-full-1)
        x=[pos]*19+[neg]*11+[pos]*34
        gains=s.timing_gains(8,0,0)
        trace=SatTrace()
        values,positions=s.timing(x,4,12,gains,stats=trace)
        self.assertEqual(trace.evaluations['gradient'],12)
        self.assertEqual(trace.counts['gradient'],{'pos':1,'neg':1})
        self.assertEqual(trace.total(),trace.counts['gradient']['pos']+trace.counts['gradient']['neg'])
        # Zero gains: the position advances by exactly sps per output, so the taps of output t sit
        # at samples 8+4t; recompute the preclamp gradient directly (bpsk_fixed.interp, integer P16).
        half=4<<15;gradients=[]
        for t in range(12):
            p16=(8+4*t)<<16
            early,mid,late=interp(x,p16-half),interp(x,p16),interp(x,p16+half)
            gradients.append((late[0]-early[0])*mid[0]+(late[1]-early[1])*mid[1])
        clipped=[g for g in gradients if abs(g)>s.ONE30]
        self.assertEqual(len(clipped),2)
        self.assertGreater(sum(1 for g in clipped if g>s.ONE30),0)
        self.assertGreater(sum(1 for g in clipped if g<-s.ONE30),0)
        # The clamped error feeding the loop is exactly +/-ONE30 there: with zero gains and rate 0
        # the output values are pure interpolations, but an out-of-rail gradient must not move P.
        self.assertEqual(positions,[(8+4*t)<<16 for t in range(12)])
        default_values,default_positions=s.timing(x,4,12,gains)
        self.assertEqual(values,default_values);self.assertEqual(positions,default_positions)

    def test_gradient_vector_artifacts(self):
        """sync_cases writes sync_gradient_expected.txt (one field, evaluations positive negative,
        evaluations == total scored timing output count) and a matching saturation.json."""
        import sync_cases
        work=Path(tempfile.mkdtemp())
        try:
            folder=work/'vectors'
            report=sync_cases.vectors(folder,(.02,.0001),(4,40,10,.05,.00005),transactions=1,seed=5)
            rows=(folder/'sync_gradient_expected.txt').read_text().split()
            self.assertEqual(rows[0],'1')
            evaluations,positive,negative=map(int,rows[1:4])
            scored=sum(1 for line in (folder/'gt_out.txt').read_text().splitlines()[1:] if line)
            self.assertEqual(evaluations,scored)
            self.assertEqual(evaluations,report['gt_gradient_evaluations'])
            payload=json.loads((folder/'saturation.json').read_text())
            self.assertEqual(payload['stages']['gradient'],{'pos':positive,'neg':negative})
            self.assertEqual(payload['evaluations']['gradient'],evaluations)
            self.assertEqual(payload['total'],positive+negative)
            self.assertEqual(payload['scored_outputs'],scored)
            self.assertTrue(payload['model_only_evidence'])
        finally:
            shutil.rmtree(work,ignore_errors=True)


if __name__=='__main__':unittest.main()
