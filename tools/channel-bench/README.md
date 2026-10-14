# Channel robustness benchmark — JTTY / FT4 / FT8

**Repository**: [Iu-yang1/wsjtx](https://github.com/Iu-yang1/wsjtx)  
**Experiment branch**: `bench/jtty-ft4-ft8-channel-thresholds`  
**Reproducible source baseline**: `v3.2.0-rc1` (tag commit `567ad29ce6abf3d4a44f181cdbc7ceba0d73e5f4`).

The upstream default branch was inspected at `967c85a6119110788b0df3782cf796485b2cee14` and **did not contain `lib/jtty/`**. This is why experiments use the rc1 tag instead of claiming the current default branch contains JTTY. No experimental code has been merged into `master`.

## Objective

Estimate the 2500 Hz noise-bandwidth SNR corresponding to **50% exact-message decoding probability** for each of:

- JTTY: original `sjtty` TX + `rjtty` RX
- FT4: original `ft4sim` TX + `jt9 -5` RX
- FT8: original `ft8sim` TX + `jt9 -8` RX

Decoding is counted **only when the intended entire decoded message is found**, never when the decoder merely exits successfully. The receiver uses the ordinary blind mode with `-X 0` and callsign priors suppressed for FT4/FT8. JTTY has no analogous external AP setting in this experiment.

## Channels and experiment grid

These are two **separate** groups of trials, not an unrequested 4×21 Cartesian product.

| Experiment | Propagation model | Values | Notes |
|---|---|---|---|
| AWGN | additive Gaussian noise | 0 Hz / 0 ms | reference |
| MD | Watterson 2-path | 1 Hz, differential delay 2 ms | mid-latitude disturbed |
| HM | Watterson 2-path | 10 Hz, delay 3 ms | high-latitude moderate |
| HD | Watterson 2-path | 30 Hz, delay 7 ms | high-latitude disturbed |
| Linear chirp | AWGN + deterministic baseband Doppler | 0, 1, ..., 20 Hz/s | *not* Watterson; rate not spread |

Thus there are `3 modes × (4 spread + 21 rate) = 75` independent channel/mode conditions.

For a chirp rate `k`, the analytic received signal is multiplied by:

```math
exp(jπk(t − t_mid)²)
```

so that its **instantaneous frequency offset** is `k(t − t_mid)` Hz, centered within the transmitted frame. Analytic-signal modulation is used to avoid introducing a spurious negative-frequency mixing image.

Watterson scenarios use the **unaltered upstream** Fortran `watterson` implementation from the same revision as the simulator, not a generic uncorrelated fading stand-in. The original simulators supply AWGN, Watterson delay/spread, audio framing, and signal-level calibration. The external Python script applies chirp **after generating AWGN**, so the Watterson and deterministic rate experiments remain distinguishable.

## Probability estimator and censoring

For each condition, the harness first samples two endpoints of the SNR range and performs coarse binary search with Monte Carlo trials. It then samples neighboring values more heavily around the transition. The 50% crossing is interpolated between adjacent empirical decoding probabilities after a weighted isotonic/monotone fit (PAVA). Per-SNR Wilson 95% binomial probability intervals are stored in `points.csv`.

Default configuration: 12 pilot trials per tested SNR, 48 confirmation trials at up to five near-threshold SNRs, SNR from −32 through +20 dB, and six binary-search steps. The default total budget is intentionally a pilot-scale benchmark rather than a publication-grade confidence interval for SNR50. The CSV records every attempted trial count, and the estimate is **not** extrapolated outside the tested SNR range.

If the success probability never exceeds 50%, the result is marked `above_range_or_floor` (rather than fabricating an SNR50). In particular, strong uncompensated chirp may impose an **error floor** that increasing SNR cannot remove. If the lowest tested SNR already reaches 50%, it is marked `below_range`.

For a rigorous publication, increase `--final-trials`, add multiple independent messages/callsigns, directly measure SNR calibration and fit confidence bands for the P50 crossing.

## Reproducibility

`WSJT_SIM_SEED` deterministically initializes the upstream C `rand()` through `sgran_`. With the environment variable omitted, the original entropy-based behavior is retained.

The rc1 `sjtty.f90` had its `call sgran()` commented out. This benchmark enables it, otherwise repeatedly executing the one-file simulator could incorrectly reuse identical channel/noise realizations.

Each trial uses a SHA256-derived seed indexed by mode, channel, SNR and trial number; a failed step can be rerun identically.

### Build

The GitHub Actions workflow installs the required native dependencies and builds the original upstream programs, with only benchmark RNG changes:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DWSJT_SKIP_MANPAGES=ON -DWSJT_ENABLE_TESTS=OFF \
  -DWSJT_BUILD_UTILS=ON \
  -DWSJT_FORTRAN_LIBRARY_VARIANTS=NON_OPENMP_ONLY
cmake --build build --target sjtty rjtty ft4sim ft8sim jt9 -j4
```

### Run

Python 3 + NumPy + SciPy are required.

```bash
python3 tools/channel-bench/smoke_decode.py --bin-dir build --mode ft8
python3 tools/channel-bench/run_thresholds.py --bin-dir build --mode jtty \
  --kind spread --out results/jtty-spread
python3 tools/channel-bench/run_thresholds.py --bin-dir build --mode ft4 \
  --kind drift --out results/ft4-drift
```

The GitHub Actions workflow `Channel robustness P50 (JTTY / FT4 / FT8)` builds once, smoke-tests all three modes, and runs six matrix jobs. The `report` job combines their CSV/JSON artifacts, explicitly reporting uncompleted scenarios.

### Outputs

- `points.csv`: raw decoded counts, probabilities, and Wilson bounds for each measured SNR.
- `results.json`: per-condition SNR50 estimate or an explicit censoring status, with provenance.
- `thresholds.csv` and `summary.md`: merged 75-condition comparison.

**Interpretation warning**: These are decoder-performance measurements for selected message types, **not** absolute physical receiver sensitivity; JTTY source atoms and FT4/FT8 messages carry different amounts of application-layer information, and different receiver architectures have different latency/computation budgets. Neither a JTTY 1-frame result nor a point obtained using one callsign should be generalized to all real-world chat traffic.

## Primary source

- [Original JTTY experiment driver](https://github.com/WSJTX/wsjtx/blob/v3.2.0-rc1/lib/jtty/sjtty.f90)
- [Original FT4 simulator](https://github.com/WSJTX/wsjtx/blob/v3.2.0-rc1/lib/ft4/ft4sim.f90)
- [Original FT8 simulator](https://github.com/WSJTX/wsjtx/blob/v3.2.0-rc1/lib/ft8/ft8sim.f90)
- [ITU-R F.1487](https://www.itu.int/rec/R-REC-F.1487)
