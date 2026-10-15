# Refined JTTY / FT4 / FT8 QEX-style measurements

**Recorded:** 75/75 conditions; **Trials:** 81,872.
Models: two-path Watterson (ITU-R F.1487) or native TX-only chirp + AWGN.
Pilot coarse SNR grid and predeclared three-message ensemble; SNR50 is an isotonic 50% crossing, with model-based Jeffreys-beta posterior interval.
Unresolved conditions are NOT assigned a fabricated SNR50.

## Watterson summary

|Channel|JTTY|FT4|FT8|QEX FT4 / FT8 (reference)|
|---|---:|---:|---:|---|
|AWGN|-15.90 dB [-16.15, -15.68]|-18.29 dB [-18.40, -18.13]|-21.67 dB [-21.80, -21.58]|-17.5 / -20.8 dB|
|MQ|-15.65 dB [-15.83, -15.51]|-18.17 dB [-18.32, -17.98]|-21.05 dB [-21.27, -20.81]|—|
|MM|-13.95 dB [-14.51, -13.49]|-16.67 dB [-16.86, -16.23]|-20.32 dB [-20.60, -19.98]|—|
|MD|-13.75 dB [-14.09, -13.37]|-16.00 dB [-16.21, -15.71]|-19.81 dB [-20.05, -19.52]|-15.2 / -18.6 dB|
|HM|-12.61 dB [-12.79, -12.41]|-11.19 dB [-11.52, -10.88]|-5.93 dB [-10.13, -5.13]|-12.2 / -8.6 dB|
|HD|-7.66 dB [-8.03, -7.15]|no_P50_error_floor|no_P50_error_floor|—|

## Validity gates

- Missing conditions: none
- Unexpected conditions: none
- Each condition stores all attempted per-trial seeds and exact decoded-message matches.
- Correlations between SNR conditions are intentionally induced by reusing trial seed (paired common random numbers), not independent SNR samples.
- Interval estimates are model-based and do not account for waveform/calibration systematic errors.
- FT4/FT8 packets and JTTY atoms carry different useful application information; do not interpret SNR50 ranking alone as throughput superiority.

## Source
[Franke, Somerville, Taylor, QEX 2020](https://wsjt.sourceforge.io/FT4_FT8_QEX.pdf)
[GitHub Actions refined branch](https://github.com/Iu-yang1/wsjtx/tree/bench/refined-channel-robustness)
