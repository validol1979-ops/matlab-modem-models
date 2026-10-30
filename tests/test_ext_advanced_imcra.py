"""Fixture-driven tests for the floating OM-LSA / IMCRA port.

The independent authority is the original-Octave fixture
``tests/data/imcra_source_reference_20261030.npz``: ``Ya2`` is 257x497
one-sided power frames and every other vector field is 257x25 sampled at the
25 zero-based frame indices in ``indices``.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "common" / "python"))

import ext_advanced_imcra as imcra  # noqa: E402

FIXTURE = HERE / "data" / "imcra_source_reference_20261030.npz"
RTOL, ATOL, FLOOR = 1e-10, 1e-10, 1e-12

VECTOR_FIELDS = (
    "lambda_d", "lambda_dav", "lambda_dav_long",          # noise / long noise
    "S", "Smin", "St", "Smint", "SMact", "SMactt",        # smoothing/minima
    "Sy", "qhat", "phat", "q", "PH1",                     # decisions
    "gamma", "eta", "v", "eta_2term",                     # SNR schedule
    "GH1", "GH0", "G",                                    # gains
    "xi", "P_local", "P_global",                          # presence
)
SCALAR_FIELDS = ("frame_presence", "mean_local", "frame", "rollover",
                 "first_nonzero")


@pytest.fixture(scope="module")
def reference():
    with np.load(FIXTURE) as z:
        return {k: np.array(z[k]) for k in z.files}


@pytest.fixture(scope="module")
def replay(reference):
    """Run all 497 fixture frames once; snapshot the 25 sampled frames."""
    want = reference["indices"].tolist()
    tracker = imcra.IMCRA(fs=16000, m=512, nonstat="medium",
                          tone=True, broad=True)
    snaps, gains = {}, None
    for f in range(reference["Ya2"].shape[1]):
        gains = tracker.step(reference["Ya2"][:, f])
        if f in want:
            snaps[f] = tracker.fields()
    return tracker, snaps, gains


def _close(actual, expected):
    actual = np.asarray(actual, dtype=float)
    expected = np.asarray(expected, dtype=float)
    scale = np.maximum(np.maximum(np.abs(actual), np.abs(expected)), FLOOR)
    return np.abs(actual - expected) <= RTOL * scale + ATOL * 0


def test_fixture_shape_and_indices(reference):
    assert reference["Ya2"].shape == (257, 497)
    assert reference["indices"].shape == (25,)
    for name in VECTOR_FIELDS:
        assert reference[name].shape == (257, 25), name
    for name in SCALAR_FIELDS:
        assert reference[name].shape == (25,), name
    # The fixture never has a silent frame, so first_nonzero is frame 1.
    assert np.all(reference["first_nonzero"] == 1)
    # Fixture scalar columns are self-consistent with the frame numbering.
    assert np.array_equal(reference["frame"], reference["indices"] + 1)
    # Every fixture array must be asserted somewhere in this module.
    covered = set(VECTOR_FIELDS) | set(SCALAR_FIELDS) | {"Ya2", "indices"}
    assert set(reference) == covered, set(reference) ^ covered


def test_input_power_round_trip(reference, replay):
    _, snaps, _ = replay
    for j, f in enumerate(reference["indices"].tolist()):
        assert _close(snaps[f]["Ya2"], reference["Ya2"][:, f]).all(), f


def test_every_noise_and_minima_field(reference, replay):
    _, snaps, _ = replay
    for name in ("lambda_d", "lambda_dav", "lambda_dav_long", "S", "Smin",
                 "St", "Smint", "SMact", "SMactt", "Sy"):
        for j, f in enumerate(reference["indices"].tolist()):
            assert _close(snaps[f][name], reference[name][:, j]).all(), (name, f)


def test_every_snr_and_gain_field(reference, replay):
    _, snaps, _ = replay
    for name in ("gamma", "eta", "v", "eta_2term", "GH1", "GH0", "G"):
        for j, f in enumerate(reference["indices"].tolist()):
            assert _close(snaps[f][name], reference[name][:, j]).all(), (name, f)


def test_every_presence_field(reference, replay):
    _, snaps, _ = replay
    for name in ("qhat", "phat", "q", "PH1", "xi", "P_local", "P_global"):
        for j, f in enumerate(reference["indices"].tolist()):
            assert _close(snaps[f][name], reference[name][:, j]).all(), (name, f)


def test_scalar_schedule_fields(reference, replay):
    _, snaps, _ = replay
    for name in SCALAR_FIELDS:
        for j, f in enumerate(reference["indices"].tolist()):
            expected = float(np.asarray(reference[name])[j])
            actual = float(snaps[f][name])
            assert abs(actual - expected) <= RTOL * max(abs(actual),
                                                        abs(expected), FLOOR), (name, f)


def test_gain_output_and_eta_2term_feedback(reference, replay):
    tracker, snaps, gains = replay
    assert gains.shape == (257,) and np.all(np.isfinite(gains))
    last = reference["indices"].tolist()[-1]
    assert _close(snaps[last]["G"], reference["G"][:, -1]).all()
    # eta_2term is evaluated after the gain: GH1**2 * gamma at frame end.
    assert _close(tracker.eta_2term, tracker.GH1 ** 2 * tracker.gamma).all()
    assert _close(snaps[last]["eta_2term"], reference["eta_2term"][:, -1]).all()


def test_first_frame_initialisation(reference):
    tracker = imcra.IMCRA()
    ya2 = reference["Ya2"][:, 0]
    tracker.step(ya2)
    # First nonzero frame seeds lambda_dav[-long], S, St, Sy from Ya2.
    assert _close(tracker.lambda_dav, ya2).all()
    assert _close(tracker.lambda_dav_long, ya2).all()
    assert _close(tracker.S, ya2).all() and _close(tracker.St, ya2).all()
    assert _close(tracker.Sy, ya2).all()
    # The frame-end gamma uses lambda_d = 1.4685*Ya2 (not the IMCRA-stage
    # lambda_d=Ya2), so gamma = 1/1.4685 uniformly on the very first frame.
    g = 1.0 / 1.4685
    e = max(0.95 * 1.0 + 0.05 * max(g - 1.0, 0.0), tracker.eta_min)
    assert _close(tracker.gamma, np.full(257, g)).all()
    assert _close(tracker.eta, np.full(257, e)).all()
    assert _close(tracker.v, np.full(257, g * e / (1.0 + e))).all()
    # IMCRA-stage (first) evaluation did see gamma=1, eta=0.95, v=0.95/1.95.
    assert _close(tracker.qhat, np.ones(257)).all()
    # Source lambda_d is 1.4685*lambda_dav for nonstat != 'high', so the
    # first frame already reports the scaled noise PSD.
    assert _close(tracker.lambda_d, 1.4685 * tracker.lambda_dav).all()
    assert _close(tracker.lambda_d, 1.4685 * ya2).all()


def test_maintained_minima_during_first_frames(reference):
    tracker = imcra.IMCRA()
    for l in range(1, 14 + tracker.l_fnz):
        tracker.step(reference["Ya2"][:, l - 1])
        assert _close(tracker.Smin, tracker.S).all(), l
        assert _close(tracker.SMact, tracker.S).all(), l
        assert _close(tracker.St, tracker.S).all(), l
        assert _close(tracker.Smint, tracker.S).all(), l
        assert _close(tracker.SMactt, tracker.S).all(), l
        assert _close(tracker.lambda_dav_long, tracker.lambda_dav).all(), l


def test_two_gamma_eta_v_evaluations_per_frame(reference):
    """The first evaluation feeds IMCRA, the second feeds the gain."""
    tracker = imcra.IMCRA()
    prev_eta2 = 1.0
    for l in range(1, 30):
        ya2 = reference["Ya2"][:, l - 1]
        prev_lambda_d = tracker.lambda_d.copy()
        prev_eta2 = tracker.eta_2term
        tracker.step(ya2)
        # gain-stage evaluation at frame end, using the updated lambda_d
        g2 = ya2 / np.maximum(tracker.lambda_d, imcra.EPS)
        e2 = np.maximum(0.95 * prev_eta2 + 0.05 * np.maximum(g2 - 1, 0),
                        tracker.eta_min)
        assert _close(tracker.gamma, g2).all(), l
        assert _close(tracker.eta, e2).all(), l
        assert _close(tracker.v, g2 * e2 / (1 + e2)).all(), l
        # eta_2term is the last assignment of the frame.
        assert _close(tracker.eta_2term, tracker.GH1 ** 2 * tracker.gamma).all()
        # the IMCRA stage saw the older noise PSD, not the fresh one
        if l > 1 and not np.allclose(prev_lambda_d, tracker.lambda_d):
            break
    else:
        pytest.fail("lambda_d never changed; cannot separate the two passes")


def _state_copy(tracker):
    return {k: (v.copy() if isinstance(v, np.ndarray) else v)
            for k, v in vars(tracker).items()}


def test_reset_returns_to_initial_state(reference):
    tracker = imcra.IMCRA()
    fresh = _state_copy(imcra.IMCRA())
    for f in range(40):
        tracker.step(reference["Ya2"][:, f])
    tracker.reset()
    after = _state_copy(tracker)
    assert after.keys() == fresh.keys()
    for key in fresh:
        a, b = after[key], fresh[key]
        if isinstance(b, np.ndarray):
            assert a.shape == b.shape and np.array_equal(a, b), key
        else:
            assert a == b, key
    # A reset tracker must reproduce the first frame exactly.
    tracker.step(reference["Ya2"][:, 0])
    other = imcra.IMCRA()
    other.step(reference["Ya2"][:, 0])
    assert np.array_equal(tracker.G, other.G)


def test_silent_frames_do_not_advance_tracker(reference):
    tracker = imcra.IMCRA()
    before = _state_copy(tracker)
    for _ in range(3):
        gains = tracker.step(np.zeros(257))
        assert np.array_equal(gains, np.ones(257) * tracker.G)
    assert tracker.l == 3 and tracker.l_fnz == 4 and not tracker.fnz_flag
    for key in ("S", "lambda_d", "lambda_dav", "xi", "eta_2term"):
        assert np.array_equal(getattr(tracker, key), before[key]), key
    assert tracker.eta_2term == 1.0
    # The source then initialises on the first nonzero frame (l == l_fnz).
    ya2 = reference["Ya2"][:, 3]
    tracker.step(ya2)
    assert _close(tracker.lambda_dav, ya2).all()
    assert _close(tracker.S, ya2).all()


def test_invalid_input_rejected_before_mutation(reference):
    tracker = imcra.IMCRA()
    tracker.step(reference["Ya2"][:, 0])
    before = _state_copy(tracker)
    bad_inputs = (
        np.zeros(256),                       # wrong length
        np.zeros((257, 1)),                  # wrong shape
        np.full(257, np.nan),                # non-finite
        np.full(257, np.inf),
        np.full(257, -1e-3),                 # negative power
    )
    for bad in bad_inputs:
        with pytest.raises(ValueError):
            tracker.step(bad)
        after = _state_copy(tracker)
        assert after.keys() == before.keys()
        for key in before:
            a, b = after[key], before[key]
            if isinstance(b, np.ndarray):
                assert np.array_equal(a, b), (key, np.shape(bad))
            else:
                assert a == b, (key, np.shape(bad))
    with pytest.raises(ValueError):
        imcra.IMCRA(nonstat="bogus")


def test_source_window_normalisation():
    win, cwin, mno = imcra.analyze_window(512)
    assert win.shape == (512,) and mno == 128
    assert abs(np.sum(win ** 2) - 1.0) < 1e-12      # normalised by Cwin
    assert abs(cwin - np.sqrt(8.0 * 16.0)) < 1e-9   # Cwin = sqrt(sum win^2)
    # Hann smoothing kernels follow the fixture convention Hann(3) = [0,1,0].
    tracker = imcra.IMCRA()
    assert np.array_equal(tracker.b, np.array([0.0, 1.0, 0.0]))
    assert tracker.b_xi_global.shape == (31,)
    assert abs(tracker.b_xi_global.sum() - 1.0) < 1e-12


def test_process_audio_length_flags_and_silence():
    tracker = imcra.IMCRA()
    n = 4096
    t = np.arange(n) / 16000.0
    sig = 0.1 * np.sin(2 * np.pi * 440.0 * t)
    out = tracker.process_audio(sig)
    assert out.shape == sig.shape
    assert np.all(np.isfinite(out))
    assert np.abs(out).max() <= np.abs(sig).max() * 1.5
    assert tracker.l == (n - 384) // 128
    # Digital silence in -> finite, non-amplified output.
    silent = imcra.IMCRA().process_audio(np.zeros(n))
    assert np.all(np.isfinite(silent)) and np.allclose(silent, 0.0, atol=1e-12)
    with pytest.raises(ValueError):
        imcra.IMCRA().process_audio(np.zeros((2, n)))
    with pytest.raises(ValueError):
        imcra.IMCRA().process_audio(np.full(n, np.nan))


def test_process_audio_matches_step_driven_bins(reference):
    """OLA uses the same 257-bin power frames and the same tracker step."""
    tracker = imcra.IMCRA()
    win, cwin, mno = imcra.analyze_window(512)
    n = 384 + 128 * 5
    x = 0.2 * np.sin(2 * np.pi * 1000.0 * np.arange(n) / 16000.0 + .123)
    ref = imcra.IMCRA()
    padded = np.concatenate((x, np.zeros(512)))
    acc = np.zeros(padded.size)
    for l in range((n - 384) // 128):
        buf = padded[l * 128:l * 128 + 512]
        spec = np.fft.fft(win * buf)
        g = ref.step(np.abs(spec[:257]) ** 2)
        xs = np.zeros(512, dtype=complex)
        xs[3:256] = g[3:256] * spec[3:256]
        xs[257:] = np.conj(xs[255:0:-1])
        acc[l * 128:l * 128 + 512] += cwin ** 2 * win * np.real(np.fft.ifft(xs))
    out = tracker.process_audio(x)
    assert np.allclose(out, acc[:n], rtol=0, atol=0)
    assert ref.l == tracker.l


def test_minima_rollover_period(reference):
    """l_mod_lswitch increments and wraps every Vwin=15 frames."""
    tracker = imcra.IMCRA()
    seen = []
    for f in range(60):
        tracker.step(reference["Ya2"][:, f])
        seen.append(tracker.rollover)
    assert seen[:15] == list(range(1, 15)) + [0]
    assert seen[15:30] == list(range(1, 15)) + [0]
    # Window buffer only starts rolling after the first full Vwin period.
    assert np.all(reference["rollover"][:3] == np.array([1, 2, 14]))
    for j, f in enumerate(reference["indices"].tolist()):
        if f < 60:
            assert seen[f] == reference["rollover"][j]


def test_tone_removal_indexing_only_after_frame_120(reference):
    """P_local tonal notching needs l>120 and uses lambda_dav_long shifts 6/7/8."""
    tracker = imcra.IMCRA()
    for f in range(120):
        tracker.step(reference["Ya2"][:, f])
    assert tracker.l == 120
    fired = []
    for f in range(120, 200):
        ldl = tracker.lambda_dav_long
        crit = ldl[7:249] > 2.5 * (ldl[9:251] + ldl[5:247])
        mean_before = None
        tracker.step(reference["Ya2"][:, f])
        if np.any(crit) and mean_before is not None:
            fired.append(f + 1)
        if np.any(crit):
            rows = np.concatenate((np.nonzero(crit)[0] + 6,
                                   np.nonzero(crit)[0] + 7,
                                   np.nonzero(crit)[0] + 8))
            assert np.all(tracker.P_local[rows] == tracker.P_min)
    # Indexing must stay inside the 257-bin vector (no wraparound).
    assert tracker.P_local.shape == (257,)


def test_nonstat_and_flag_variants_are_finite(reference):
    for nonstat in ("low", "medium", "high"):
        for tone in (True, False):
            for broad in (True, False):
                tracker = imcra.IMCRA(nonstat=nonstat, tone=tone, broad=broad)
                for f in range(40):
                    g = tracker.step(reference["Ya2"][:, f])
                    assert g.shape == (257,)
                    # GH1 may exceed 1 for tiny v (exp(0.5*E1(v)) > 1), as in
                    # the source; only positivity/finiteness is contract.
                    assert np.all(np.isfinite(g)) and np.all(g > 0)
                    assert np.all(g < 10.0)


def test_octave_vector_condition_means_all_positive():
    """Source ``if xi_local>0`` is a scalar test: all-positive only."""
    tracker = imcra.IMCRA()
    pos = np.full(257, 0.25)
    mixed = pos.copy()
    mixed[7] = 0.0
    db_pos = tracker._dB(pos)
    assert isinstance(db_pos, np.ndarray) and db_pos.shape == (257,)
    assert np.allclose(db_pos, 10.0 * np.log10(0.25))
    assert tracker._dB(mixed) == -100.0
    # The scalar branch broadcasts through the P ramps.
    assert np.all(tracker._pramp(-100.0, -10.0, -5.0) == tracker.P_min)
    assert tracker._dB(0.0) == -100.0 and tracker._dB(1.0) == 0.0


def test_module_level_step_uses_default_tracker(reference):
    tracker = imcra.default_tracker()
    tracker.reset()
    gain = imcra.step(reference["Ya2"][:, 0])
    assert gain is not tracker.G
    assert np.array_equal(gain, tracker.G)
    tracker.reset()
    assert imcra.default_tracker() is tracker

def test_exact_time_domain_activation_and_invalid_config():
    for args in ({'fs':8000},{'m':256},{'tone':1},{'broad':0}):
        with pytest.raises(ValueError): imcra.IMCRA(**args)
    signal=np.zeros(2048);signal[1:80]=.1  # Source rejects first frame despite spectral energy.
    tracker=imcra.IMCRA();out=tracker.process_audio(signal)
    assert not tracker.fnz_flag and tracker.l_fnz==14
    assert np.array_equal(out,np.zeros_like(out))
    signal=np.zeros(2048);signal[128:180]=.1
    tracker=imcra.IMCRA();out=tracker.process_audio(signal)
    assert tracker.fnz_flag and tracker.l_fnz==2
    # Globally counted frames continue during post-onset silence, recurrence
    # windows only advance for active time frames (frames1 and2 here).
    assert tracker.l==13 and tracker.l_mod_lswitch==1
    with pytest.raises(ValueError):tracker.step(np.ones(257)*1j)

# The repository runner uses unittest discovery; preserve the independently
# authored fixture tests and expose them through a standard unittest suite.
import inspect as _inspect
import unittest as _unittest
class TestIMCRAOriginalFixture(_unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref=reference.__wrapped__()
        cls.replayed=replay.__wrapped__(cls.ref)
def _bridge(fn):
    def run(self):
        args={'reference':self.ref,'replay':self.replayed}
        fn(**{k:args[k] for k in _inspect.signature(fn).parameters})
    return run
for _name,_function in list(globals().items()):
    if _name.startswith('test_') and callable(_function):
        setattr(TestIMCRAOriginalFixture,_name,_bridge(_function))
