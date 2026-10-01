# WSJT-X channel robustness benchmark

This benchmark measures the SNR_2500 value at which the stock WSJT-X decoders
successfully recover a fixed target message with 50% probability.

The benchmark branch is based on `v3.2.0-rc1`, because the current upstream
`master` no longer contains `lib/jtty/`. The workflow records both the JTTY
baseline commit and the current upstream master commit in its result metadata.

## Modes

| Mode | Simulator | Decoder | Test message |
| --- | --- | --- | --- |
| JTTY | `sjtty` | `rjtty` | `CQ K1ABC CQ` |
| FT4 | `ft4sim` | `jt9 -5` | `K1ABC W9XYZ EN37` |
| FT8 | `ft8sim` | `jt9 -8` | `K1ABC W9XYZ EN37` |

FT4/FT8 AP decoding is disabled for the benchmark by using QSO progress 0 and
blank local/DX calls. Decoder frequency tolerance is deliberately wide
(±500 Hz), so deterministic-chirp failures are dominated by synchronization
and demodulation rather than an artificially narrow search window.

## Channel families

### Watterson / ITU-R-style spread

The signal passes through the existing WSJT-X `watterson()` implementation.

| Label | Frequency spread | Differential delay |
| --- | ---: | ---: |
| AWGN | 0 Hz | 0 ms |
| 1 Hz | 1 Hz | 2 ms |
| 10 Hz | 10 Hz | 3 ms |
| 30 Hz | 30 Hz | 7 ms |

The last three pairs correspond to the parameter pairs commonly used for
ITU-R F.1487 mid-latitude disturbed, high-latitude moderate, and high-latitude
disturbed tests.

### Deterministic Doppler rate

A linear chirp is injected into the complex simulator waveform before AWGN is
added:

```text
df(t) = drift_rate * (t - T/2)
phase(t) = pi * drift_rate * (t - T/2)^2
```

The sweep is 0, 1, 2, ... 20 Hz/s. Centering the chirp at `T/2` keeps the
nominal simulator frequency as the midpoint frequency and avoids mixing a
static frequency offset into the Doppler-rate measurement.

The simulator CLI extensions are backward compatible: the final
`drift_hz_s` argument is optional and defaults to zero.

## 50% threshold estimator

For each mode/channel point the Python driver:

1. generates a batch of independent noisy WAV files with the native simulator;
2. runs the native decoder and counts exact target-message decodes;
3. adaptively brackets 50% probability over SNR;
4. bisects the bracket to 0.5 dB resolution;
5. repeats the transition measurements with a larger Monte-Carlo sample;
6. applies weighted nondecreasing isotonic regression to the sampled
   decode-probability curve and interpolates its 0.5 crossing.

Every raw measurement stores sample count, number of successful decodes,
decode probability, and a 95% Wilson interval. If a mode cannot reach 50%
decode probability even at the configured upper SNR bound, the result is
reported as `not_reached` rather than inventing a threshold.

## Running locally

Build these targets from this branch:

```bash
cmake -S . -B build \
  -DWSJT_ENABLE_TESTS=OFF \
  -DWSJT_SKIP_MANPAGES=ON \
  -DWSJT_GENERATE_DOCS=OFF \
  -DWSJT_SKIP_QMAP=ON \
  -DWSJT_BUILD_JT9STREAM=OFF \
  -DWSJT_FORTRAN_LIBRARY_VARIANTS=NON_OPENMP_ONLY

cmake --build build --target jt9 ft8sim ft4sim sjtty rjtty -j"$(nproc)"
```

Then, for example:

```bash
python3 tools/channel_benchmark/run_thresholds.py \
  --mode jtty --family watterson \
  --bin-dir build --source-dir . \
  --output-dir results/jtty-watterson
```

The GitHub Actions workflow runs all six mode/family combinations and uploads
raw CSV, JSON metadata, per-job summaries, and a combined result table.
