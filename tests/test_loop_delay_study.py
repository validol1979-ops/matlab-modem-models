"""Loop-delay study: characteristic polynomials against the update recurrences, the
phase-margin delay limit against roots, and delay overrides of the integer receivers."""
from pathlib import Path
import math
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
sys.path.insert(0, str(ROOT/'common/python'))
import loop_delay_study as L
import oqpsk_fixed as o
import cpm_fixed as c
import psk_fixed as p


def recurrence(D, a, b, form, steps=6000):
    """Exact update order of the receivers with a linear detector e = -estimate (unit
    step input). Returns the final absolute error and its peak over the last quarter."""
    pending = [0.]*D; u = f = 0.; history = []
    for _ in range(steps):
        e = pending.pop(0)
        if form == 'psk':
            # psk_fixed: frequency += b e; phase += a e; use; phase += frequency.
            f += b*e; u += a*e; used = u; u += f
        elif form == 'angle':
            # oqpsk/cpm: frequency += b e; phase += frequency + a e; use.
            f += b*e; u += f+a*e; used = u
        else:
            # timing/AGC: state += k e; use.
            u += a*e; used = u
        pending.append(1.-used); history.append(abs(1.-used))
    return history[-1], max(history[-steps//4:])


class TestLoopDelayStudy(unittest.TestCase):
    def test_polynomials_match_update_recurrences(self):
        cases = [('psk', .04, .0002), ('psk', .4, .02), ('angle', .04, .0002), ('angle', .3, .01),
                 ('first', .01, 0), ('first', .5, 0)]
        for form, a, b in cases:
            for D in (1, 2, 4, 8, 16, 40):
                poly = L.poly_first(D, a) if form == 'first' else L.poly_carrier(D, a, b, form)
                final, peak = recurrence(D, a, b, form)
                with self.subTest(form=form, a=a, b=b, D=D):
                    rho = L.radius(poly)
                    if rho < .999:self.assertLess(peak, 1e-3)
                    elif rho > 1.001:self.assertGreater(peak, 10)

    def test_phase_margin_limit_equals_root_search(self):
        for form, a, b in (('psk', .04, .0002), ('angle', .02, .0001), ('first', .03, 0)):
            if form == 'first':
                make = lambda D, g: L.poly_first(D, g*a); opened = L.open_first(a)
            else:
                make = lambda D, g: L.poly_carrier(D, g*a, g*b, form); opened = L.open_carrier(a, b, form)
            D, wc, pm0, verified = L.max_delay(make, opened)
            with self.subTest(form=form):
                self.assertTrue(verified)
                self.assertTrue(L.stable(make(D, 1.)))
                self.assertFalse(L.stable(make(D+1, 1.)))
                self.assertLessEqual(abs(D-math.floor(pm0/wc)), 1)

    def test_gain_margin_is_the_stability_boundary(self):
        make = lambda D, g: L.poly_carrier(D, g*.04, g*.0002, 'psk')
        g = L.margin(make, 4)
        self.assertTrue(L.stable(make(4, g*.999)))
        self.assertFalse(L.stable(make(4, g*1.01)))

    def test_detector_gain_matches_design_normalisation(self):
        # imag(value*conj(target))/|target|^2 in Q15: 32768 per radian.
        for name in ('qpsk', 'qam16'):
            with self.subTest(name=name):
                self.assertAlmostEqual(L.detector_gain(name, 'phase', .02)/32768, 1, delta=.01)
        # GMSK uses the angle itself (2^32 per turn).
        self.assertAlmostEqual(L.detector_gain('gmsk', 'phase', .02)/(2**32/(2*math.pi)), 1, delta=.01)

    def test_delay_override_is_applied_and_restored(self):
        preamble, symbols, wave = L.frame('qpsk', 3, dict(snr_db=25, frequency=3e-4, phase_noise=.006))
        default = L.run_receiver('qpsk', wave, preamble)
        explicit = L.run_receiver('qpsk', wave, preamble, delay=p.QPSK.loop_delay)
        changed = L.run_receiver('qpsk', wave, preamble, delay=24)
        self.assertEqual(default['trace'], explicit['trace'])
        self.assertNotEqual(default['trace'], changed['trace'])
        for name, module, attribute in (('oqpsk', o, 'LOOP_DELAY'), ('gmsk', c, 'COHERENT_DELAY')):
            before = getattr(module, attribute)
            pre, _, w = L.frame(name, 3, {})
            L.run_receiver(name, w, pre, delay=3)
            L.run_receiver(name, w, pre, open_loop=True)
            self.assertEqual(getattr(module, attribute), before)
        before = p.GAIN_DELAY
        pre, _, w = L.frame('qam16', 3, {})
        L.run_receiver('qam16', w, pre, gain_delay=2)
        self.assertEqual(p.GAIN_DELAY, before)


if __name__ == '__main__':
    unittest.main()
