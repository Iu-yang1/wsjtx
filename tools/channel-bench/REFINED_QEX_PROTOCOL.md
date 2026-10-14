# QEX-inspired WSJT-X channel robustness experiment — refinement round

Source: WSJT-X `v3.2.0-rc1`, with the original JTTY, FT4 and FT8 simulators and
decoders. The experiment remains on `bench/refined-channel-robustness`, not `master`.

**Reference:** Franke, Somerville, Taylor, *The FT4 and FT8 Communication
Protocols*, QEX July/August 2020, §8, Figure 7, Table 6:
https://wsjt.sourceforge.io/FT4_FT8_QEX.pdf

## Why this round?

The previous 75-condition experiment used a bisection-biased SNR grid and a
single callsign per mode with as few as 48 confirmatory draws. The revised
experiment uses a fixed pilot grid, repeated independent Monte Carlo waveform
realizations, a locally dense set of SNR values and a predeclared message
ensemble. Every successful trial requires **an exact message match**.

A scientific protocol is not implied merely by an Actions job being green:
randomization, reference SNR calibration, error-floor detection and missing-data
handling are explicitly audited.

## Three-mode conditions

The ITU-R F.1487 Watterson cases are:

| Case | Spread | Differential path delay |
|---|---:|---:|
| AWGN | 0 Hz | 0 ms |
| Mid quiet | 0.1 Hz | 0.5 ms |
| Mid moderate | 0.5 Hz | 1 ms |
| Mid disturbed | 1 Hz | 2 ms |
| High moderate | 10 Hz | 3 ms |
| High disturbed | 30 Hz | 7 ms |

Deterministic signal-only linear Doppler tests are **separate**:

- Dense onset: 0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3 Hz/s.
- Larger rates: 4, 5, 6, 8, 10, 12, 15, 18, 20 Hz/s.

Total: **3 modes × (6 Watterson + 19 Doppler) = 75 conditions**, with
higher resolution near the onset of FT8/FT4 Doppler-rate degradation.
This is deliberately not a combined Watterson+chirp experiment.

## TX-only Doppler correction in the experiment driver

All three upstream Fortran simulators have a native optional Doppler-rate
argument. Unlike the first experiment, this driver invokes those arguments,
so a chirp is applied to the **complex transmitted waveform before
AWGN**, not to an already-noisy, sampled WAV. This avoids artificially
sweeping the receiver noise as if it were Doppler-shifted radiation.

For a frame duration `T`, the Doppler injection has instantaneous frequency
offset `rate × (t − T/2)`, with the carrier centered at the frame midpoint.
No compensation is applied by the receiver under test.

## Fixed-grid QEX-style probability curves

1. Generate pilot samples on a fixed `-30, -25, ..., +20 dB SNR_2500` grid.
   Default: 16 waveform realizations per SNR.
2. Calculate an isotonic pilot P50 crossing (for **search selection only**).
3. If crossed, sample in 0.5 dB steps over ±2 dB of the pilot P50, with
   128 trials per SNR by default. Include the high-SNR endpoint with
   128 trials even when the P50 is found.
4. If no crossing, add strong samples to +15/+20 dB to determine whether
   a channel-dependent **decode error floor** may exist. Never extrapolate P50.
5. For each SNR point report decoded count / trial count, Wilson 95% binomial
   interval, fitted isotonic probability, and adjacent significant
   monotonicity violations.
6. A 95% **model-based** SNR50 interval is obtained by repeatedly sampling
   Jeffreys Beta posterior probabilities, performing weighted PAVA fitting and
   measuring the crossing. This is a posterior uncertainty interval, *not*
   a guaranteed frequentist 95% confidence interval; decoding-model
   misspecification/systematic effects are not covered.

When observed probability at +20 dB remains below 50%, the condition is
labeled as censored or potentially floor-limited, not given a numerical
threshold. Do not interpret a missing SNR50 as a specific SNR penalty.

## Message diversity and randomization

Three standard callsign formats are predeclared for each mode (K1ABC, W9XYZ,
DL1ABC) with appropriate frame type and maidenhead or JTTY CQ.
Trial `i` uses message `i mod 3` and a stable hash-derived random seed.

The **same seed is used for the same trial index at multiple SNR levels**.
This creates paired/common-random-numbers comparisons across SNR, reducing
noise from unmatched fading realizations; the trials are independently
randomized **within each SNR**. Do not count pairs as independent between-SNR
samples. The entire per-trial ledger is retained for replication.

The CI smoke stage validates all nine mode/message pairs with the original
decoders, runs statistical unit tests and checks that JTTY gives identical
WAVs for identical seeds, but different WAVs for different seeds.

## Output / reproducibility

The Actions workflow `.github/workflows/refined-channel-robustness.yml`
builds one set of native simulator/decoder binaries, then dispatches nine
matrix jobs. Each job writes:

- `trials.csv`: one record per simulated waveform with exact-message
  success, seed and message.
- `points.csv`: empirical decode probability and Wilson intervals per SNR.
- `results.json`: P50, model-based interval, censoring status, fitted
  points and monotonicity diagnostics.

The merged artifact includes a QEX-like **Figure 7 panel set** (six Watterson
channels × three modes), threshold bar comparison, Doppler-rate sensitivity
curve, raw data, and provenance.

Run locally:

```bash
python3 -m unittest discover -s tools/channel-bench -p 'test_*.py' -v
python3 tools/channel-bench/verify_rng.py --bin-dir build
python3 tools/channel-bench/verify_message_ensemble.py --bin-dir build
python3 tools/channel-bench/refined_thresholds.py --bin-dir build \
  --mode jtty --group spread --out measurements/jtty-spread
```

**Limitations:** A JTTY source atom is not equivalent to an FT8/FT4 77-bit
message in information payload or throughput. The results evaluate
decoder performance on selected legal messages, **not** energy efficiency
per useful bit, general-chat throughput, AP-assisted QSO operation,
Doppler compensation, multi-user interference or actual propagation
hardware. The original QEX Figure 7 used an earlier WSJT-X version,
so thresholds need not numerically reproduce that figure.
