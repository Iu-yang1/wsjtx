#!/usr/bin/env python3
"""QEX-inspired, independently reproducible three-mode channel benchmark.

Real WSJT-X simulators/decoders. Fixed SNR pilot + dense local P50 sweep.
Predeclared message ensemble; shared fading seeds across SNR at fixed trial ID.
Separate ITU Watterson frequency spread and signal-only Doppler chirp.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

from run_thresholds import Runner, stable_seed, wilson

ITU = {
    "AWGN": (0.0, 0.0), "MQ": (0.1, 0.5), "MM": (0.5, 1.0),
    "MD": (1.0, 2.0), "HM": (10.0, 3.0), "HD": (30.0, 7.0)
}
DRIFT_LOW = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
DRIFT_HIGH = [4., 5., 6., 8., 10., 12., 15., 18., 20.]
MESSAGES = {
    "jtty": ("CQ K1ABC CQ", "CQ W9XYZ CQ", "CQ DL1ABC CQ"),
    "ft4": ("CQ K1ABC FN42", "CQ W9XYZ EN37", "CQ DL1ABC JO62"),
    "ft8": ("CQ K1ABC FN42", "CQ W9XYZ EN37", "CQ DL1ABC JO62"),
}
RESULT_FIELDS = ("mode", "group", "condition", "spread_hz", "delay_ms",
                 "drift_hz_s", "snr_2500_db", "trials", "successes",
                 "probability", "wilson_low", "wilson_high", "stage")
TRIAL_FIELDS = ("mode", "group", "condition", "snr_2500_db", "trial_index",
                "message", "seed", "decoded")


def isotonic(success: np.ndarray, trials: np.ndarray) -> np.ndarray:
    """Weighted pool-adjacent-violators, monotone nondecreasing in SNR."""
    blocks = []
    for success_i, trials_i in zip(success, trials):
        blocks.append([float(success_i), float(trials_i), 1])
        while len(blocks) > 1:
            a, b = blocks[-2], blocks[-1]
            if a[0] * b[1] <= b[0] * a[1]:
                break
            blocks[-2:] = [[a[0] + b[0], a[1] + b[1], a[2] + b[2]]]
    return np.asarray([s/n for s,n,m in blocks for _ in range(m)])


def interpolate_crossing(snr: np.ndarray, prob: np.ndarray, target=0.5):
    """No extrapolation. A plateau straddling 50% is treated as uncertain."""
    if len(snr) < 2 or prob[0] >= target or prob[-1] < target:
        return None
    for i in range(1, len(snr)):
        if prob[i] >= target and prob[i-1] < target:
            if prob[i] == prob[i-1]:
                return None
            return float(snr[i-1] + (snr[i] - snr[i-1]) *
                         (target - prob[i-1])/(prob[i] - prob[i-1]))
    return None


def analyze(rows: list[dict], seed: int, bootstrap: int = 700) -> dict:
    rows = sorted(rows, key=lambda r: float(r["snr_2500_db"]))
    xs = np.array([float(r["snr_2500_db"]) for r in rows], dtype=float)
    s = np.array([int(r["successes"]) for r in rows], dtype=int)
    n = np.array([int(r["trials"]) for r in rows], dtype=int)
    p = s/n
    fitted = isotonic(s, n)
    crossing = interpolate_crossing(xs, fitted)
    upper = wilson(int(s[-1]), int(n[-1]))[1]
    lower = wilson(int(s[-1]), int(n[-1]))[0]
    # Detect significantly nonmonotone empirical behavior without calling it noise.
    violations = []
    for i in range(len(xs)-1):
        if wilson(int(s[i]), int(n[i]))[0] > wilson(int(s[i+1]), int(n[i+1]))[1]:
            violations.append([float(xs[i]), float(xs[i+1])])
    if crossing is None:
        if p[0] >= .5:
            state = "below_range"
        elif upper < .5:
            state = "no_P50_error_floor"
        elif lower < .5:
            state = "no_P50_uncertain"
        else:
            state = "unresolved_nonmonotone"
    else:
        state = "estimated"
    ci = None
    valid_samples = 0
    if crossing is not None:
        # Jeffreys Beta(1/2,1/2) probability posterior + isotonic constraint.
        # This produces a MODEL-BASED posterior uncertainty interval, NOT an
        # exact frequentist confidence interval or independent repeated RF trial.
        rng = np.random.default_rng(seed)
        estimates = []
        for _ in range(bootstrap):
            q = rng.beta(s + .5, n - s + .5)
            y = isotonic(q*n, n)
            b = interpolate_crossing(xs, y)
            if b is not None:
                estimates.append(b)
        valid_samples = len(estimates)
        if valid_samples >= max(100, int(bootstrap*.8)):
            ci = np.quantile(estimates, [.025,.975]).round(4).tolist()
        else:
            state = "unstable_threshold"
    return {
        "status": state,
        "p50_snr_2500_db": round(crossing, 4) if crossing is not None else None,
        "p50_model_interval_95_db": ci,
        "p50_interval_method": "Jeffreys-beta posterior and weighted isotonic P50",
        "bootstrap_valid_samples": valid_samples,
        "total_trials": int(n.sum()),
        "end_snr_2500_db": float(xs[-1]),
        "end_success_probability": round(float(p[-1]), 4),
        "end_wilson95": [round(wilson(int(s[-1]),int(n[-1]))[0],4),
                         round(wilson(int(s[-1]),int(n[-1]))[1],4)],
        "nonmonotone_confident_steps": violations,
        "fitted_probability": [{"snr_2500_db":float(x),
                                 "decode_probability":round(float(v),6)}
                                for x,v in zip(xs,fitted)],
    }


def conditions(group):
    if group == "spread":
        return [("spread", key, float(v[0]), float(v[1]), 0.)
                for key,v in ITU.items()]
    rates = DRIFT_LOW if group == "drift-low" else DRIFT_HIGH
    return [("drift", "RATE_%05.2f" % r, 0., 0., r) for r in rates]


def run_condition(runner, cfg, condition, points, raw_trials):
    kind, name, spread, delay, rate = condition
    counts = {}
    msgs = MESSAGES[cfg.mode]
    def measure(snr, n_target, stage):
        snr = round(float(snr), 3)
        current = counts.setdefault(snr, [0, 0, "pilot"])
        for trial_i in range(current[1], n_target):
            msg = msgs[trial_i % len(msgs)]
            seed = stable_seed(cfg.base_seed, cfg.mode, cfg.group,
                               name, trial_i)  # Crucially independent of SNR.
            ok = bool(runner.trial(kind, name, spread, delay, rate,
                                   snr, seed, message=msg))
            current[0] += int(ok)
            current[1] += 1
            raw_trials.writerow(dict(mode=cfg.mode, group=cfg.group,
                       condition=name, snr_2500_db=snr, trial_index=trial_i,
                       message=msg, seed=seed, decoded=int(ok)))
        if stage == "dense":
            current[2] = stage
        return current[0] / current[1]

    coarse = np.arange(cfg.snr_min, cfg.snr_max + 0.01, cfg.coarse_step)
    for x in coarse:
        measure(float(x), cfg.pilot_trials, "pilot")

    baseline = [{"snr_2500_db": x,"successes": v[0],"trials": v[1]}
                for x,v in counts.items()]
    pre = analyze(baseline, stable_seed(cfg.base_seed,name), bootstrap=0)

    # Full probability-vs-SNR curve near the observed 50% transition.
    # If no crossing, scrutinize high-SNR/error-floor instead of inventing P50.
    if pre["p50_snr_2500_db"] is not None:
        center = pre["p50_snr_2500_db"]
        grid = np.arange(center-cfg.dense_radius,
                         center+cfg.dense_radius+0.01,cfg.dense_step)
        for x in grid:
            if cfg.snr_min <= x <= cfg.snr_max:
                measure(x, cfg.dense_trials, "dense")
    else:
        # This distinguishing step is essential in 30 Hz / severe chirp:
        # high SNR does not imply that a decoder can demodulate the waveform.
        for x in (cfg.snr_max-cfg.coarse_step, cfg.snr_max):
            measure(x, cfg.dense_trials, "dense")

    # Even if the coarse stage crossed 0.5, measure the upper endpoint
    # more densely to detect a plateau or an implausible non-monotonic curve.
    measure(cfg.snr_max, max(cfg.dense_trials, cfg.pilot_trials), "dense")

    rows = []
    for snr, (ok, n, stage) in sorted(counts.items()):
        lo, hi = wilson(ok,n)
        row = dict(mode=cfg.mode,group=cfg.group,condition=name,
            spread_hz=spread,delay_ms=delay,drift_hz_s=rate,
            snr_2500_db=snr,trials=n,successes=ok,
            probability=round(ok/n,6),
            wilson_low=round(lo,6),wilson_high=round(hi,6),stage=stage)
        points.writerow(row)
        rows.append(row)
    detail = analyze(rows, stable_seed(cfg.base_seed,cfg.mode,cfg.group,name),
                     bootstrap=cfg.bootstrap)
    detail.update(mode=cfg.mode, group=cfg.group, condition=name,
                  spread_hz=spread,delay_ms=delay,drift_hz_s=rate,
                  message_ensemble=list(msgs),no_ap=True,
                  channel="ITU-R F.1487 Watterson" if kind == "spread"
                          else "AWGN plus native TX-only linear Doppler")
    print(json.dumps({key:val for key,val in detail.items()
                      if key != "fitted_probability"},sort_keys=True),flush=True)
    return detail


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bin-dir",required=True,type=Path)
    ap.add_argument("--mode",required=True,choices=tuple(MESSAGES))
    ap.add_argument("--group",required=True,choices=("spread","drift-low","drift-high"))
    ap.add_argument("--out",required=True,type=Path)
    ap.add_argument("--snr-min",type=float,default=-30.)
    ap.add_argument("--snr-max",type=float,default=20.)
    ap.add_argument("--coarse-step",type=float,default=5.)
    ap.add_argument("--pilot-trials",type=int,default=16)
    ap.add_argument("--dense-trials",type=int,default=128)
    ap.add_argument("--dense-step",type=float,default=.5)
    ap.add_argument("--dense-radius",type=float,default=2.0)
    ap.add_argument("--bootstrap",type=int,default=700)
    ap.add_argument("--base-seed",type=int,default=20261015)
    ap.add_argument("--timeout",type=int,default=120)
    cfg=ap.parse_args()
    if not (cfg.snr_min < cfg.snr_max and cfg.coarse_step > 0
            and cfg.dense_step > 0 and cfg.dense_radius>0 and
            cfg.pilot_trials>=6 and cfg.dense_trials>=cfg.pilot_trials):
        ap.error("Invalid grid or trial limits")
    cfg.out.mkdir(parents=True,exist_ok=True)
    runner=Runner(cfg.bin_dir.resolve(),cfg.mode,cfg.timeout)
    output=[]
    with (cfg.out/"points.csv").open("w",newline="",encoding="utf8") as fp, \
         (cfg.out/"trials.csv").open("w",newline="",encoding="utf8") as ft:
        pointwriter=csv.DictWriter(fp,fieldnames=RESULT_FIELDS)
        trialwriter=csv.DictWriter(ft,fieldnames=TRIAL_FIELDS)
        pointwriter.writeheader()
        trialwriter.writeheader()
        for cond in conditions(cfg.group):
            output.append(run_condition(runner,cfg,cond,pointwriter,trialwriter))
            fp.flush()
            ft.flush()
            (cfg.out/"results.json").write_text(
                json.dumps({"config":vars(cfg)|{"bin_dir":str(cfg.bin_dir),"out":str(cfg.out)},
                            "results":output},indent=2),encoding="utf8")
    print(f"FINISHED {cfg.mode} {cfg.group}: {len(output)} conditions",flush=True)


if __name__=="__main__":
    main()
