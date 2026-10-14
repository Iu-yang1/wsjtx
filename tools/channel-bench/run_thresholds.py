#!/usr/bin/env python3
"""Monte Carlo decoding thresholds for original WSJT-X JTTY, FT4 and FT8.

Uses upstream sjtty/ft4sim/ft8sim and rjtty/jt9 executables, not surrogate decoders.
Python only orchestrates trials, applies deterministic chirp and estimates P50.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import hilbert

SCENARIOS = {"AWGN": (0.0, 0.0), "MD": (1.0, 2.0),
             "HM": (10.0, 3.0), "HD": (30.0, 7.0)}
MESSAGES = {"jtty": "CQ K1ABC CQ", "ft4": "CQ K1ABC FN42",
            "ft8": "CQ K1ABC FN42"}
# (time the transmitted waveform begins, duration, Watterson-source temporal alignment)
TIMING = {"jtty": (0.10, 1.888), "ft4": (0.45, 5.04),
          "ft8": (0.50, 12.64)}
OUTPUT_WAV = "000000_000001.wav"
RAW_FIELDS = ("mode", "kind", "condition", "spread_hz", "delay_ms", "drift_hz_s",
              "snr_2500_db", "trials", "successes", "probability", "wilson_low",
              "wilson_high")


def stable_seed(*keys: object) -> int:
    data = "|".join(map(str, keys)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(data).digest()[:4], "big")


def wilson(nok: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return 0.0, 1.0
    p = nok / n
    d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return max(0., c-h), min(1., c+h)


def p50(points: list[dict], min_snr: float, max_snr: float) -> dict:
    """Interpolate adjacent observed probabilities; no extrapolation at the limits."""
    rows = sorted(points, key=lambda r: r["snr_2500_db"])
    if not rows:
        return {"status": "not_measured", "p50_snr_2500_db": None}
    # Pool-adjacent-violators: monotonic success probability with SNR.
    blocks: list[list[float]] = []
    for row in rows:
        blocks.append([float(row["successes"]), float(row["trials"]), 1.0])
        while len(blocks) >= 2 and (blocks[-2][0] / blocks[-2][1] >
                                     blocks[-1][0] / blocks[-1][1]):
            a, b = blocks[-2:]
            blocks[-2:] = [[a[0]+b[0], a[1]+b[1], a[2]+b[2]]]
    fitted = []
    for successes, trials, count in blocks:
        fitted.extend([successes/trials]*int(count))
    if fitted[0] >= 0.5:
        return {"status": "below_range", "p50_snr_2500_db": None,
                "bound_db": rows[0]["snr_2500_db"]}
    if fitted[-1] < 0.5:
        return {"status": "above_range_or_floor", "p50_snr_2500_db": None,
                "bound_db": rows[-1]["snr_2500_db"]}
    for i in range(1, len(rows)):
        if fitted[i] >= 0.5:
            lo, hi = rows[i-1], rows[i]
            p0, p1 = fitted[i-1], fitted[i]
            x = float(lo["snr_2500_db"])
            if p1 > p0:
                x += (float(hi["snr_2500_db"])-x) * (0.5-p0)/(p1-p0)
            return {"status": "interpolated", "p50_snr_2500_db": round(x, 3),
                    "bracket_db": [lo["snr_2500_db"], hi["snr_2500_db"]]}
    raise RuntimeError("P50 estimator inconsistency")


def chirp_wav(path: Path, slope: float, mid_time: float) -> None:
    """Frequency offset is slope*(t-mid_time) Hz; this is not random spread."""
    fs, raw = wavfile.read(path)
    if fs != 12000 or raw.dtype != np.int16 or raw.ndim != 1:
        raise ValueError("Expected upstream mono 12 kHz signed 16-bit WAV")
    # Analytic signal avoids doubling negative-frequency image under FM.
    analytic = hilbert(raw.astype(np.float64))
    t = np.arange(raw.size, dtype=np.float64)/float(fs)-mid_time
    shifted = (analytic * np.exp(1j*np.pi*slope*t*t)).real
    if np.max(np.abs(shifted)) > 32767:
        raise ValueError("Doppler injection clipped PCM")
    wavfile.write(path, fs, np.rint(shifted).astype(np.int16))


class Runner:
    def __init__(self, binaries: Path, mode: str, timeout: int):
        self.binaries, self.mode, self.timeout = binaries, mode, timeout
        for name in (("sjtty", "rjtty") if mode == "jtty" else
                     (mode+"sim", "jt9")):
            if not (binaries/name).is_file():
                raise FileNotFoundError(binaries/name)

    def trial(self, kind: str, name: str, spread: float, delay: float,
              drift: float, snr: float, seed: int, message: str | None = None) -> bool:
        msg = message or MESSAGES[self.mode]
        with tempfile.TemporaryDirectory(prefix="wsjtx-p50-") as td:
            path = Path(td)
            env = os.environ.copy()
            env["WSJT_SIM_SEED"] = str(seed)
            fdop = spread if kind == "spread" else 0.0
            dms = delay if kind == "spread" else 0.0
            if self.mode == "jtty":
                args = [msg, "1500", "0.10", str(fdop), str(dms),
                        "384", "1", str(snr)]
            else:
                args = [msg, "1500", "0.0", str(fdop), str(dms),
                        "1", str(snr)]
            # All three simulators support a native optional chirp argument.
            # Chirp the TX complex waveform BEFORE Watterson fading and AWGN.
            if kind == "drift" and drift:
                args.append(str(drift))
            cmd = [str(self.binaries/(self.mode+"sim" if self.mode != "jtty"
                                      else "sjtty")), *args]
            gen = subprocess.run(cmd, cwd=path, env=env, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 timeout=self.timeout)
            if gen.returncode != 0:
                raise RuntimeError("Simulator failed: " + gen.stdout[-1200:])
            wav = path/OUTPUT_WAV
            if not wav.is_file():
                raise RuntimeError("Simulator did not produce WAV: " + gen.stdout[-1200:])
            if self.mode == "jtty":
                decode = [str(self.binaries/"rjtty"), "4.6", "0", "384",
                          "1500", "450", str(wav)]
            else:
                decode = [str(self.binaries/"jt9"),
                          "-5" if self.mode == "ft4" else "-8",
                          "-p", "7.5" if self.mode == "ft4" else "15",
                          "-f", "1500", "-F", "450", "-d", "3",
                          "-X", "0", "-c", "b", "-x", "b", str(wav)]
            proc = subprocess.run(decode, cwd=path, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=self.timeout)
            if proc.returncode != 0:
                raise RuntimeError("Decoder failed: " + proc.stdout[-1200:])
            # Require exact decoded message, not a nonzero decode count.
            normalized_msg = " ".join(msg.upper().split())
            for line in proc.stdout.upper().splitlines():
                if self.mode == "jtty":
                    m = re.match(r"^\s*\d+\s{2,}(.*?)\s*$", line)
                    if m and " ".join(m.group(1).split()) == normalized_msg:
                        return True
                elif re.search(r"(?<![A-Z0-9])" + re.escape(normalized_msg) +
                               r"(?![A-Z0-9])", " ".join(line.split())):
                    return True
            return False


def run_condition(runner: Runner, kind: str, name: str, spread: float,
                  delay: float, drift: float, cfg: argparse.Namespace,
                  writer: csv.DictWriter) -> dict:
    counts: dict[float, list[int]] = {}
    def measure(snr: float, target: int) -> float:
        snr = round(float(snr), 3)
        succeeded, n = counts.get(snr, [0, 0])
        for trial in range(n, target):
            seed = stable_seed(cfg.base_seed, runner.mode, kind, name, snr, trial)
            ok = runner.trial(kind, name, spread, delay, drift, snr, seed)
            succeeded += int(ok)
            n += 1
        counts[snr] = [succeeded, n]
        return succeeded/n

    # Coarse bisection: never claim a finite threshold for censored data.
    low, high = cfg.snr_min, cfg.snr_max
    p_low = measure(low, cfg.pilot_trials)
    p_high = measure(high, cfg.pilot_trials)
    if p_low < 0.5 and p_high >= 0.5:
        for _ in range(cfg.bisect_steps):
            middle = round((low+high)/2.0, 3)
            if middle in (low, high):
                break
            if measure(middle, cfg.pilot_trials) >= 0.5:
                high = middle
            else:
                low = middle
        center = 0.5*(low+high)
        # Confirm a small contiguous SNR neighborhood with more trials.
        for snr in sorted({max(cfg.snr_min, min(cfg.snr_max,
                                                  round(center + offset, 3)))
                           for offset in (-2.0, -1.0, 0.0, 1.0, 2.0)}):
            measure(snr, cfg.final_trials)
    else:
        # Endpoints confirm a censored result; no fabricated threshold.
        measure(cfg.snr_min, cfg.final_trials)
        measure(cfg.snr_max, cfg.final_trials)

    all_rows = []
    for snr, (successes, trials) in sorted(counts.items()):
        ci_low, ci_high = wilson(successes, trials)
        row = {"mode": runner.mode, "kind": kind, "condition": name,
               "spread_hz": spread, "delay_ms": delay, "drift_hz_s": drift,
               "snr_2500_db": snr, "trials": trials, "successes": successes,
               "probability": round(successes/trials, 6),
               "wilson_low": round(ci_low, 6),
               "wilson_high": round(ci_high, 6)}
        writer.writerow(row)
        all_rows.append(row)
    summary = p50(all_rows, cfg.snr_min, cfg.snr_max)
    summary.update(mode=runner.mode, kind=kind, condition=name,
                   spread_hz=spread, delay_ms=delay, drift_hz_s=drift,
                   total_trials=sum(x["trials"] for x in all_rows),
                   snr_2500_reference_bandwidth_hz=2500,
                   decoder_ap_enabled=False)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=tuple(MESSAGES), required=True)
    parser.add_argument("--kind", choices=("spread", "drift", "both"), default="both")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pilot-trials", type=int, default=12)
    parser.add_argument("--final-trials", type=int, default=48)
    parser.add_argument("--bisect-steps", type=int, default=6)
    parser.add_argument("--snr-min", type=float, default=-32)
    parser.add_argument("--snr-max", type=float, default=20)
    parser.add_argument("--max-drift", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--base-seed", type=int, default=20261014)
    args = parser.parse_args()
    if min(args.pilot_trials, args.final_trials) < 1 or args.max_drift < 0:
        parser.error("trials must be positive and max-drift nonnegative")
    if args.snr_min >= args.snr_max:
        parser.error("snr-min must be < snr-max")
    args.out.mkdir(parents=True, exist_ok=True)
    runner = Runner(args.bin_dir.resolve(), args.mode, args.timeout)
    summaries = []
    with (args.out/"points.csv").open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=RAW_FIELDS)
        writer.writeheader()
        if args.kind in ("spread", "both"):
            for name, (spread, delay) in SCENARIOS.items():
                summaries.append(run_condition(runner, "spread", name, spread,
                                               delay, 0., args, writer))
                csvfile.flush()
        if args.kind in ("drift", "both"):
            for rate in range(args.max_drift+1):
                name = f"DRIFT_{rate:02d}"
                summaries.append(run_condition(runner, "drift", name, 0., 0.,
                                               float(rate), args, writer))
                csvfile.flush()
    metadata = {"upstream_tag": "v3.2.0-rc1", "base_seed": args.base_seed,
                "mode": args.mode, "kind": args.kind,
                "pilot_trials": args.pilot_trials, "final_trials": args.final_trials,
                "bisect_steps": args.bisect_steps,
                "snr_range": [args.snr_min, args.snr_max],
                "notes": "Thresholds interpolate empirical monotone P(success). "
                         "No AP; exact decoded message only. Censored points are not extrapolated."}
    (args.out/"results.json").write_text(
        json.dumps({"metadata": metadata, "results": summaries},
                   indent=2, ensure_ascii=False)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
