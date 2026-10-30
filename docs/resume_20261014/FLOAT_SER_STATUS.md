# Floating SER — paused draft

User requested continuation tomorrow. Root remains unchanged.

Only `tools/uvm_floating_reference.py` exists as a new draft, copied from the prepared independent helper with relative ROOT. No CLI attempt, tests or UVM integration have run in this batch. No active CLI process group exists. The previous QPSK/PSK8 UVM package was already accepted; its final evidence is `<local-tmp>`.

Status: `build/rtl/uvm_float_ser/paused.json`. Draft diff: `<local-tmp>`.

## Next steps

1. One bounded Pi attempt (idle90/hard240), then fallback on backend failure.
2. Verify complete float modem_core RX and float MRC independence on original Q15 pin waveforms/gains.
3. Create and independently validate immutable float decisions/original truth/error/denominator files before making negative vectors.
4. Extend actual RX UVM payload scoring/comparison and metadata/denominator negatives. Keep all old BPSK/QPSK/PSK8 RX and TX keys/controls/reset coverage and default both/all.
5. Run helper/tests and full actual Questa gate with fresh evidence, then stage root review. Synthesis stays paused.

Expected prepared-reference float payload errors (original first4, before integration): BPSK `[0,0,0,54]`, QPSK_DIFF `[0,0,16,308]`, PSK8_FB `[0,0,0,408]`; current accepted RTL UVM `[0,0,0,58]`, `[0,0,14,277]`, `[0,0,0,402]`. Differences are measured diagnostics, no truth rotation or tuned acceptance budget. These values are not a new passing UVM comparison claim.
