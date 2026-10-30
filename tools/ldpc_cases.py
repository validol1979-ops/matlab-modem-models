"""LDPC decoder + GF(2) encoder RTL vectors: the bit-exact outputs of common/python/ldpc_fixed.py
for rtl/common/ldpc_decoder.sv and rtl/common/gf2_encoder.sv (one folder holds both streams).

A configuration is a stream of single matrix bits accepted while cfg_ready with cfg_last on the last
bit, the matrix rows in row-major order (decoder: H, m x n; encoder: A, m x k); the header fields
(cfg_m, cfg_n / cfg_k, iterations, mode, alpha, beta) are held stable during the whole configuration.
dec_cfg.txt is the line `m n iterations mode alpha beta` (alpha = round(alpha*256), beta =
round(beta*256), as the cfg_alpha / cfg_beta fields) followed by the m*n bits, one per line;
enc_cfg.txt is the line `m k` followed by the m*k bits. Every file starts with its row count line
(cfg files: the header line only, so the bits start on line 2).

A decoder transaction is n LLRs (Q8 signed, s_last on the n-th) and answers n outputs (bit and
posterior, m_last on the n-th); an encoder transaction is k message bits (s_last on the k-th) and
answers m parity bits then the k message bits (m_last on the last).

Code 'model' is the systematic code H = [I A] of tests/test_ldpc_fixed.py (6 x 12) with iterations
20, alpha .8 and beta .15: the first decoder transaction is the model case (codeword of the message
[1,0,1,1,0,1], llr = (1-2*word)*6 with llr[7] *= -.12), the encoder takes the model message first.
Code 'big' is a random regular-ish H of size 12 x 24 (each row weight 4..6, every column used) with
iterations 10 and its own random encoder A of size 12 x 12; the LLR streams of both codes are drawn
from codewords of the systematic encoder of that folder, some of them are undecodable (the streams
are compared bit-exactly anyway). Files: dec_cfg.txt, dec_in.txt (`llr last`), dec_out.txt
(`bit posterior last`), enc_cfg.txt, enc_in.txt (`bit last`), enc_out.txt (`bit last`).

OUTPUT OVERLOAD TRANSACTION (sat16 of the posterior, the `ldpc_decoder m` covergroup bins, whose full
scale is 2^15 - 1 because the LLR field is 16 bit Q8). The last decoder transaction is a VALID
CODEWORD AT MAXIMUM MAGNITUDE: a non-zero GF(2) word of the kernel of H (kernel_word) turned into
llr = +32767 on its 0 positions and -32767 on its 1 positions, the largest magnitude that both signs
of the field hold. Every check is satisfied by the channel alone, so the messages keep the sign of the
bit they support and have magnitude min |v| = 32767 (mode 1; mode 2 scales it by ALPHA and mode 3
subtracts BETA, still thousands, and sum-product mode 0 maps the huge |v| to the top of INV = 32767),
so P = sat16(llr + sum of the messages) sticks to +32767 on the 0 positions and to -32768 on the 1
positions in the FIRST iteration - the syndrome is already zero, the decoder breaks there. A codeword
of the kernel (not the systematic encoder of the folder) is used because for code 'big' the encoder A
is not the systematic partner of H, and a codeword that is not valid would run all 10 iterations and
drive an intermediate v to exactly -32768, whose absolute value needs 17 bits (that corner is outside
the bit-exact range of the message field, so the vector must not step on it; -32767 keeps |v| <= 32767
everywhere). `gf2_encoder m` needs no transaction of its own: its field is 1 bit wide, so FULL = 2^0 - 1
= 0 and any 0/1 stream already covers pos (v >= 0) and neg (v <= 0).

SATURATION EVIDENCE: every decode above runs with one shared sat_diag.SatTrace (ldpc_fixed.decode
stats=), which counts the pre-clamp signed16 values of the two saturating stages, 'v' (post[col]
minus the old message, once per real edge per iteration) and 'post' (llr[c] plus the new messages,
once per active column per iteration); the trace clamps exactly like sat16, so the vectors are
unchanged by the instrumentation. Each folder gets ldpc_sat_expected.txt (write_expected: FIELDS=2,
then evaluations/positive/negative for v and post) and saturation.json (save_json model_only_evidence
plus a formula recomputed independently from the iteration counts the decoder returned, the edge
count of H and n). The overload transaction is what produces the post events.

STRESS CONFIGURATION (stress=True, NEW separate config folder, never used by the old model/big
calls): one extra deterministic decoder transaction is appended after the overload, the kernel word
at +-32767 with the sign of column STRESS_FLIP flipped. It is not a codeword, the syndrome never
clears (all iterations run) and from iteration 2 on the rail-to-rail v = post[col] - old message
clamps on the positive side (v pos events, never a negative clamp, so no v reaches -32768).
"""
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common/python'))
import ldpc_fixed as d
import sat_diag

# saturation stages recorded by ldpc_fixed.decode(stats=...): 'v' = pre-clamp post[col] - old
# message on every real edge of every iteration, 'post' = pre-clamp llr[c] + sum of the new
# messages on every active column of every iteration (both sat16, asymmetric rails).
SAT_STAGES = ('v', 'post')
# stress transaction: the overload kernel word with the sign of this column flipped, so the
# channel alone is contradictory; the decoder walks all `iterations` iterations with messages
# at the rails and drives positive v clamps (never a negative clamp, so no v lands on -32768).
STRESS_FLIP = 1

A_MODEL = np.array([[1, 1, 0, 1, 0, 0],
                    [0, 1, 1, 0, 1, 0],
                    [1, 0, 1, 0, 0, 1],
                    [1, 1, 0, 0, 1, 0],
                    [0, 1, 1, 1, 0, 0],
                    [1, 0, 1, 0, 1, 1]])
OVERLOAD_LLR = (1 << 15) - 1
H_MODEL = np.c_[np.eye(6, dtype=int), A_MODEL]
MODEL_MESSAGE = [1, 0, 1, 1, 0, 1]
ITERATIONS = 20
ALPHA = .8
BETA = .15
BIG_M = 12
BIG_N = 24
BIG_ITERATIONS = 10
BIG_SEED = 11


def save(path, rows):
    rows = list(rows)
    path.write_text(str(len(rows)) + '\n' + '\n'.join(' '.join(map(str, row)) for row in rows) + '\n')
    return len(rows)


def save_cfg(path, header, bits):
    """Header line, then the matrix bits row-major, one per line."""
    path.write_text(header + '\n' + '\n'.join(str(int(bit)) for bit in bits) + '\n')


def quantize(llr):
    """LLR wave as Q8 signed integers (ldpc_fixed.quantize_llr)."""
    values = d.quantize_llr(llr)
    assert all(-32768 <= v <= 32767 for v in values)
    return values


def big_matrices():
    """Random regular-ish H (BIG_M x BIG_N, each row weight 4..6, every column used) plus an
    encoder A of size BIG_M x BIG_M; the matrix draw uses its own seed so both 'big' cases share it."""
    rng = np.random.default_rng(BIG_SEED)
    H = np.zeros((BIG_M, BIG_N), dtype=int)
    for row in range(BIG_M):
        H[row, rng.choice(BIG_N, size=int(rng.integers(4, 7)), replace=False)] = 1
    for column in np.flatnonzero(H.sum(axis=0) == 0):
        H[int(rng.choice(np.flatnonzero(H.sum(axis=1) <= 5))), column] = 1
    A = np.zeros((BIG_M, BIG_M), dtype=int)
    for row in range(BIG_M):
        A[row, rng.choice(BIG_M, size=int(rng.integers(4, 7)), replace=False)] = 1
    assert H.sum(axis=1).min() >= 4 and H.sum(axis=1).max() <= 6
    assert (H.sum(axis=0) > 0).all() and H.shape == (BIG_M, BIG_N) and A.shape == (BIG_M, BIG_M)
    return H.tolist(), A.tolist()


def code_for(code):
    """(H, A, iterations) of the named code."""
    if code == 'model':
        return H_MODEL.tolist(), A_MODEL.tolist(), ITERATIONS
    if code == 'big':
        H, A = big_matrices()
        return H, A, BIG_ITERATIONS
    raise ValueError(f'Unknown LDPC code {code}')


def kernel_word(H):
    """One non-zero GF(2) word with H word = 0: Gaussian elimination over GF(2), a free column set to
    1 and the pivot columns read back from the reduced rows. Every column of a code with n > m is
    covered by some check, so such a word always exists for these matrices."""
    m, n = len(H), len(H[0])
    rows = [[int(bit) for bit in row] for row in H]
    pivot, row = {}, 0
    for column in range(n):
        found = next((i for i in range(row, m) if rows[i][column]), None)
        if found is None:
            continue
        rows[row], rows[found] = rows[found], rows[row]
        for i in range(m):
            if i != row and rows[i][column]:
                rows[i] = [a ^ b for a, b in zip(rows[i], rows[row])]
        pivot[column] = row
        row += 1
        if row == m:
            break
    free = [column for column in range(n) if column not in pivot]
    if not free:
        raise ValueError('LDPC: H has a trivial kernel, no overload codeword')
    word = [0] * n
    word[free[0]] = 1
    for column, source in pivot.items():
        word[column] = rows[source][free[0]]
    assert all(sum(a & b for a, b in zip(check, word)) % 2 == 0 for check in H)
    return word


def build_decoder(folder, H, A, iterations, mode, transactions, rng, model, trace, stress):
    """dec_cfg.txt (`m n iterations mode alpha beta` then the H bits), dec_in.txt / dec_out.txt.
    Every decode is instrumented with `trace` (one SatTrace for the whole folder; the recorded
    clamps ARE the model clamps, so the vectors are unchanged); with `stress` one more
    deterministic transaction is appended after the overload."""
    m, n = len(H), len(H[0])
    save_cfg(folder / 'dec_cfg.txt',
             f'{m} {n} {iterations} {mode} {int(round(ALPHA * 256))} {int(round(BETA * 256))}',
             [bit for row in H for bit in row])
    in_rows, out_rows = [], []
    usages = []
    for index in range(transactions):
        if index == 0 and model is not None:
            word = np.array(d.encode(list(MODEL_MESSAGE), A))
            llr = (1 - 2 * word) * 6.
            llr[7] *= -.12
        else:
            word = np.array(d.encode(list(rng.integers(0, 2, len(A))), A))
            llr = (1 - 2 * word) * 2 + rng.normal(size=n) * 1.2
        assert len(llr) == n
        llr = quantize(llr)
        bits, posterior, used = d.decode(llr, H, iterations, mode, ALPHA, BETA, stats=trace)
        usages.append(used)
        assert len(bits) == n and len(posterior) == n
        assert all(-32768 <= p <= 32767 for p in posterior)
        in_rows.extend((llr[c], int(c == n - 1)) for c in range(n))
        out_rows.extend((int(bits[c]), int(posterior[c]), int(c == n - 1)) for c in range(n))
    # the overload transaction: a codeword of the kernel at the largest magnitude of both signs, the
    # posterior sticks to both rails (sat16) and the decoder stops after the first iteration
    word = kernel_word(H)
    assert 0 < sum(word) < n
    llr = [OVERLOAD_LLR if bit == 0 else -OVERLOAD_LLR for bit in word]
    assert len(llr) == n and max(llr) == OVERLOAD_LLR and min(llr) == -OVERLOAD_LLR
    bits, posterior, used = d.decode(llr, H, iterations, mode, ALPHA, BETA, stats=trace)
    usages.append(used)
    assert max(posterior) == 32767 and min(posterior) == -32768 and used == 1
    overload_rails = (max(posterior), min(posterior))
    overload_counts = dict(trace.counts.get('post', {'pos': 0, 'neg': 0}))
    assert overload_counts['pos'] and overload_counts['neg'], \
        f'LDPC overload produced no post clamp ({overload_counts})'
    in_rows.extend((llr[c], int(c == n - 1)) for c in range(n))
    out_rows.extend((int(bits[c]), int(posterior[c]), int(c == n - 1)) for c in range(n))
    if stress:
        # new separate configuration transaction (old folders never set stress): the overload
        # word with STRESS_FLIP sign flipped is NOT a codeword, so the syndrome never clears and
        # the decoder runs every iteration with rail-to-rail messages; iteration 2+ subtracts a
        # nonzero old message from a railed posterior, which clamps v on the positive side only
        # (no negative clamp, so no v lands on -32768 and the message field stays in range).
        llr[STRESS_FLIP] = -llr[STRESS_FLIP]
        before = {k: dict(c) for k, c in trace.counts.items()}
        bits, posterior, used = d.decode(llr, H, iterations, mode, ALPHA, BETA, stats=trace)
        usages.append(used)
        v = trace.counts.get('v', {'pos': 0, 'neg': 0})
        assert used >= 2, f'LDPC stress decoded in {used} iterations, expected 2+'
        assert v['neg'] == 0, 'LDPC stress produced a negative v clamp (v would land on -32768)'
        assert v['pos'] > before.get('v', {}).get('pos', 0), 'LDPC stress produced no v clamp'
        assert max(posterior) == 32767 and min(posterior) == -32768
        assert all(-32768 <= p <= 32767 for p in posterior)
        in_rows.extend((llr[c], int(c == n - 1)) for c in range(n))
        out_rows.extend((int(bits[c]), int(posterior[c]), int(c == n - 1)) for c in range(n))
    inputs = save(folder / 'dec_in.txt', in_rows)
    outputs = save(folder / 'dec_out.txt', out_rows)
    return inputs, outputs, overload_rails, usages


def build_encoder(folder, A, transactions, rng, model):
    """enc_cfg.txt (`m k` then the A bits), enc_in.txt / enc_out.txt."""
    m, k = len(A), len(A[0])
    save_cfg(folder / 'enc_cfg.txt', f'{m} {k}', [bit for row in A for bit in row])
    in_rows, out_rows = [], []
    for index in range(transactions):
        message = list(MODEL_MESSAGE) if (index == 0 and model is not None) else list(rng.integers(0, 2, k))
        assert len(message) == k
        outputs = [int(bit) for bit in d.encode(message, A)]
        assert len(outputs) == m + k
        in_rows.extend((int(message[c]), int(c == k - 1)) for c in range(k))
        out_rows.extend((outputs[c], int(c == m + k - 1)) for c in range(m + k))
    inputs = save(folder / 'enc_in.txt', in_rows)
    outputs = save(folder / 'enc_out.txt', out_rows)
    return inputs, outputs


def vectors(folder, mode, transactions=6, seed=31, code='model', stress=False):
    """Files in `folder`: dec_cfg.txt / dec_in.txt / dec_out.txt / enc_cfg.txt / enc_in.txt /
    enc_out.txt for the given LDPC code and decoder mode, plus ldpc_sat_expected.txt
    (sat_diag.write_expected over SAT_STAGES = v, post: FIELDS line, then evaluations/
    positive/negative per field) and saturation.json (sat_diag.save_json: model_only_evidence
    plus the trace counts and an independent evaluation formula built from the actual iteration
    counts of every scored decoder transaction, the edge count of H and its active columns).
    The one SatTrace instruments exactly the decodes whose outputs are streamed, so the
    expected files describe the streamed transactions bit-for-bit. `stress=True` is a NEW
    separate configuration (new folder): it appends one deterministic stress transaction after
    the overload and nothing else changes; the default (stress=False) keeps every vector file
    byte-identical to the pre-saturation generator (same RNG draws, same order)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    H, A, iterations = code_for(code)
    rng = np.random.default_rng(seed)
    model = MODEL_MESSAGE if code == 'model' else None
    trace = sat_diag.SatTrace()
    di, do, posterior_rails, usages = build_decoder(folder, H, A, iterations, mode, transactions,
                                                    rng, model, trace, stress)
    ei, eo = build_encoder(folder, A, transactions, rng, model)
    # independent formula: 'v' is evaluated once per real edge of every iteration actually run
    # (iterations stop early on a clear syndrome), 'post' once per active column of every such
    # iteration; the edges and active columns come from H itself, the iteration counts from the
    # decoder returns, so nothing is copied from the trace.
    n = len(H[0])
    edges = sum(sum(row) for row in H)
    active = sum(1 for c in range(n) if any(H[j][c] for j in range(len(H))))
    assert active == n, f'LDPC saturation formula: {n - active} of {n} columns are inactive'
    formula = dict(edges=edges, n=n, active_columns=active,
                   iterations=list(usages), iterations_total=sum(usages),
                   v_evaluations=sum(usages) * edges,
                   post_evaluations=sum(usages) * n)
    assert trace.evaluations == {'v': formula['v_evaluations'], 'post': formula['post_evaluations']}, \
        f'LDPC saturation formula {formula} != trace evaluations {trace.evaluations}'
    sat_diag.write_expected(folder / 'ldpc_sat_expected.txt', trace, SAT_STAGES)
    payload = sat_diag.save_json(
        folder / 'saturation.json', trace, code=code, mode=mode, iterations=iterations,
        alpha=ALPHA, beta=BETA, stages=list(SAT_STAGES), formula=formula, stress=bool(stress),
        stress_flip=STRESS_FLIP if stress else None,
        expected_files=dict(ldpc_sat='ldpc_sat_expected.txt'))
    return dict(code=code, mode=mode, transactions=transactions + 1, m=len(H), n=n,
                decoder_transactions=transactions + 1 + int(stress), encoder_transactions=transactions,
                enc_m=len(A), k=len(A[0]), iterations=iterations, alpha=ALPHA, beta=BETA,
                dec_inputs=di, dec_outputs=do, enc_inputs=ei, enc_outputs=eo,
                overload=True, posterior_rails=list(posterior_rails),
                stress=bool(stress), saturation=payload,
                saturation_markers={stage: (trace.evaluations.get(stage, 0),
                                            trace.counts.get(stage, {}).get('pos', 0)
                                            + trace.counts.get(stage, {}).get('neg', 0))
                                    for stage in SAT_STAGES})


if __name__ == '__main__':
    print(vectors(ROOT / 'build/rtl/ldpc/vectors/model', 0))
    print(vectors(ROOT / 'build/rtl/ldpc/vectors/big', 0, code='big'))
    # new separate stress configuration: same model-code config plus the appended stress
    # transaction (ldpc_tb/runner keep only the two folders above; this folder is extra)
    print(vectors(ROOT / 'build/rtl/ldpc/vectors/stress', 0, stress=True))
