"""Integer M-FSK RTL vectors: the bit-exact outputs of common/python/fsk_fixed.py for
rtl/common/fsk_tx.sv and rtl/common/fsk_rx.sv (one folder holds both streams).

One configuration is M step transfers (m = 0..M-1, cfg_last on the last one, cfg_n sampled with
cfg_last), accepted only while cfg_ready; cfg.txt holds the count, one `step` row per transfer
and a last line with `n`. TX: a transaction is labels (s_last on the last one) and answers with
n samples per label (m_last on the very last). RX: a transaction is whole symbols of n samples
(s_last on the last sample) and answers with one label per symbol (m_last on the last label).

TX labels are random per transaction, except the (32,2,3,4) first transaction, the model case
[0,1,2,3]*12. RX carries the research_core.run('fsk_tx') wave of random labels plus
.1*complex normal / sqrt(2) noise; the expected RX labels are fsk_fixed.receive, which must
reproduce the transmitted labels exactly (0 symbol errors).
Files: cfg.txt (`count`, `step` rows, `n`), tx_in.txt (`label last`), tx_out.txt (`re im last`),
rx_in.txt (`re im last`) and rx_out.txt (`label last`), every one with a leading count line.

FSK TX full scale is unreachable: each component is rnd(COS[phase],2),
where COS lies in [-131072,131071]. Thus every output component lies in
[-32768,32768], well inside the 18-bit output rails. Labels and step tables
change phase, not amplitude. build_tx asserts this bound; no extra
transaction or RNG draw is added. RX produces unsigned labels, for which
signed full-scale bins do not describe saturation.
"""
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common/python'))
import fsk_fixed as r
from research_core import run

LIMIT = (1 << 17) - 1
TX_RAIL = 1 << 15   # exact reachable bound of every fsk_tx sample (see the module docstring)
MODEL = (32, 2, 3, 4)


def save(path, rows):
    rows = list(rows)
    path.write_text(str(len(rows)) + '\n' + '\n'.join(' '.join(map(str, row)) for row in rows) + '\n')
    return len(rows)


def quantize(values):
    """Complex wave as Q15 ints, clipped to the signed 18 bit range."""
    rows = []
    for v in values:
        re = int(round(float(np.real(v)) * 32768))
        im = int(round(float(np.imag(v)) * 32768))
        rows.append((max(-LIMIT - 1, min(LIMIT, re)), max(-LIMIT - 1, min(LIMIT, im))))
    return rows


def model_labels():
    """The model case of tests/test_fsk_fixed.py: [0,1,2,3]*12."""
    return [0, 1, 2, 3] * 12


def build_tx(folder, n, f0, df, order, symbols, transactions, rng):
    table = r.steps(n, f0, df, order)
    in_rows = []
    out_rows = []
    for transaction in range(transactions):
        model = (n, f0, df, order) == MODEL and transaction == 0
        labels = model_labels() if model else [int(v) for v in rng.integers(0, order, symbols)]
        assert len(labels) >= 1
        in_rows.extend((label, int(k == len(labels) - 1)) for k, label in enumerate(labels))
        outs = r.transmit(labels, n, table)
        assert len(outs) == len(labels) * n
        # constant-envelope NCO: |y| <= 2^15 for every label/step/n, so the 18 bit output never
        # saturates and the stream_cover pos/neg bins (+-(2^17 - 1)) are unreachable - no overload
        # transaction is legal. This asserts the exact bound instead of the loose 18 bit range.
        assert all(abs(re) <= TX_RAIL and abs(im) <= TX_RAIL for re, im in outs), \
            f'FSK TX sample outside the constant-envelope bound 2^15'
        out_rows.extend((re, im, int(k == len(outs) - 1)) for k, (re, im) in enumerate(outs))
    inputs = save(folder / 'tx_in.txt', in_rows)
    outputs = save(folder / 'tx_out.txt', out_rows)
    return inputs, outputs


def build_rx(folder, n, f0, df, order, symbols, transactions, rng):
    table = r.steps(n, f0, df, order)
    in_rows = []
    out_rows = []
    errors = 0
    for _ in range(transactions):
        labels = [int(v) for v in rng.integers(0, order, symbols)]
        wave = run('fsk_tx', [n, f0, df, order], np.array(labels))
        noisy = wave + .1 * (rng.normal(size=len(wave)) + 1j * rng.normal(size=len(wave))) / np.sqrt(2)
        samples = quantize(noisy)
        assert len(samples) == len(labels) * n
        in_rows.extend((re, im, int(k == len(samples) - 1))
                       for k, (re, im) in enumerate(samples))
        outs = r.receive(samples, n, table)
        assert len(outs) == len(labels)
        errors += sum(int(out != label) for out, label in zip(outs, labels))
        out_rows.extend((label, int(k == len(outs) - 1)) for k, label in enumerate(outs))
    inputs = save(folder / 'rx_in.txt', in_rows)
    outputs = save(folder / 'rx_out.txt', out_rows)
    return inputs, outputs, errors


def vectors(folder, n=32, f0=2, df=3, order=4, symbols=40, transactions=3, seed=29):
    """Files in `folder`: cfg.txt (M step rows and `n`), tx_in.txt (`label last`),
    tx_out.txt (`re im last`), rx_in.txt (`re im last`) and rx_out.txt (`label last`)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    table = r.steps(n, f0, df, order)
    assert len(table) == order >= 1
    (folder / 'cfg.txt').write_text(str(len(table)) + '\n'
                                    + '\n'.join(str(step) for step in table) + '\n' + str(n) + '\n')
    ti, to = build_tx(folder, n, f0, df, order, symbols, transactions, rng)
    ri, ro, errors = build_rx(folder, n, f0, df, order, symbols, transactions, rng)
    assert errors == 0, f'FSK reference decoded {errors} wrong symbols'
    return dict(n=n, f0=f0, df=df, order=order, symbols=symbols, transactions=transactions,
                tx_inputs=ti, tx_outputs=to, rx_inputs=ri, rx_outputs=ro, rx_errors=errors)


if __name__ == '__main__':
    print(vectors(ROOT / 'build/rtl/fsk/vectors'))
