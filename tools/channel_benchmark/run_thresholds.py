#!/usr/bin/env python3
"""Monte-Carlo 50% decode-threshold benchmark for JTTY, FT4 and FT8.

Uses the WSJT-X simulators and decoders directly. Results are reported in
SNR_2500 dB. Each trial contains exactly one target message, so a successful
trial means that exact message appears in decoder output.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

WATTERSON = {
    "awgn": (0.0, 0.0),
    "1hz": (1.0, 2.0),   # ITU-R F.1487 mid-latitude disturbed
    "10hz": (10.0, 3.0), # ITU-R F.1487 high-latitude moderate
    "30hz": (30.0, 7.0), # ITU-R F.1487 high-latitude disturbed
}

MODE = {
    "jtty": {
        "message": "CQ K1ABC CQ",
        "sim": "sjtty",
        "decoder": "rjtty",
    },
    "ft4": {
        "message": "K1ABC W9XYZ EN37",
        "sim": "ft4sim",
        "decoder": "jt9",
    },
    "ft8": {
        "message": "K1ABC W9XYZ EN37",
        "sim": "ft8sim",
        "decoder": "jt9",
    },
}


def norm(s: str) -> str:
    return " ".join(s.strip().split())


def run_checked(cmd: list[str], cwd: Path, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stdout[-12000:]}"
        )
    return proc


def count_decodes(stdout: str, message: str) -> int:
    target = norm(message)
    count = 0
    for line in stdout.splitlines():
        if target in norm(line):
            count += 1
    return count


def wilson(success: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = success / n
    den = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / den
    half = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n) / den
    return max(0.0, center - half), min(1.0, center + half)


def pava(rows: list[dict]) -> list[tuple[float, float]]:
    """Weighted nondecreasing isotonic fit: returns (snr, fitted p)."""
    pts = sorted(rows, key=lambda r: float(r["snr_db"]))
    blocks: list[dict] = []
    for r in pts:
        w = int(r["trials"])
        block = {
            "lo": float(r["snr_db"]),
            "hi": float(r["snr_db"]),
            "w": w,
            "s": int(r["successes"]),
            "xs": [float(r["snr_db"])],
        }
        blocks.append(block)
        while len(blocks) >= 2:
            a, b = blocks[-2], blocks[-1]
            pa = a["s"] / a["w"]
            pb = b["s"] / b["w"]
            if pa <= pb:
                break
            blocks[-2:] = [{
                "lo": a["lo"],
                "hi": b["hi"],
                "w": a["w"] + b["w"],
                "s": a["s"] + b["s"],
                "xs": a["xs"] + b["xs"],
            }]
    fitted = {}
    for b in blocks:
        p = b["s"] / b["w"]
        for x in b["xs"]:
            fitted[x] = p
    return [(float(r["snr_db"]), fitted[float(r["snr_db"])]) for r in pts]


def crossing_50(rows: list[dict]) -> float | None:
    fit = pava(rows)
    if not fit or max(p for _, p in fit) < 0.5 or min(p for _, p in fit) >= 0.5:
        return None
    for i in range(1, len(fit)):
        x0, p0 = fit[i - 1]
        x1, p1 = fit[i]
        if p0 < 0.5 <= p1:
            if p1 == p0:
                return 0.5 * (x0 + x1)
            return x0 + (0.5 - p0) * (x1 - x0) / (p1 - p0)
    return None


class Runner:
    def __init__(self, mode: str, bin_dir: Path, source_dir: Path, keep_failed: bool = False):
        self.mode = mode
        self.cfg = MODE[mode]
        self.bin_dir = bin_dir.resolve()
        self.source_dir = source_dir.resolve()
        self.keep_failed = keep_failed
        self.sim = self.bin_dir / self.cfg["sim"]
        self.decoder = self.bin_dir / self.cfg["decoder"]
        for exe in (self.sim, self.decoder):
            if not exe.exists():
                raise FileNotFoundError(exe)

    def evaluate(self, spread: float, delay: float, drift: float, snr: float, trials: int) -> dict:
        started = time.time()
        temp_root = Path(tempfile.mkdtemp(prefix=f"wsjtx-{self.mode}-"))
        try:
            msg = self.cfg["message"]
            if self.mode == "jtty":
                cmd = [
                    str(self.sim), msg, "1500", "0.100",
                    f"{spread:g}", f"{delay:g}", "384", str(trials),
                    f"{snr:g}", f"{drift:g}",
                ]
            else:
                cmd = [
                    str(self.sim), msg, "1500", "0.000",
                    f"{spread:g}", f"{delay:g}", str(trials),
                    f"{snr:g}", f"{drift:g}",
                ]
            gen = run_checked(cmd, temp_root)
            wavs = sorted(temp_root.glob("000000_*.wav"))
            if len(wavs) != trials:
                raise RuntimeError(
                    f"{self.mode}: simulator generated {len(wavs)} WAVs, expected {trials}\n"
                    + gen.stdout[-8000:]
                )

            if self.mode == "jtty":
                dcmd = [
                    str(self.decoder), "4.6", "0", "384", "1500", "500",
                    *[str(p) for p in wavs],
                ]
            elif self.mode == "ft4":
                data = temp_root / "data"
                data.mkdir()
                dcmd = [
                    str(self.decoder), "-5", "-q", "-d", "3", "-Q", "0",
                    "-c", "b", "-x", "b", "-f", "1500", "-F", "500",
                    "-p", "7.5", "-a", str(data), "-r", str(self.source_dir),
                    *[str(p) for p in wavs],
                ]
            else:
                data = temp_root / "data"
                data.mkdir()
                dcmd = [
                    str(self.decoder), "-8", "-q", "-d", "3", "-Q", "0",
                    "-c", "b", "-x", "b", "-f", "1500", "-F", "500",
                    "-p", "15", "-a", str(data), "-r", str(self.source_dir),
                    *[str(p) for p in wavs],
                ]
            dec = run_checked(dcmd, temp_root)
            successes = count_decodes(dec.stdout, msg)
            if successes > trials:
                raise RuntimeError(
                    f"{self.mode}: counted {successes} target decodes for {trials} trials; "
                    "duplicate decoder output would invalidate probability estimates"
                )
            lo, hi = wilson(successes, trials)
            return {
                "mode": self.mode,
                "spread_hz": spread,
                "delay_ms": delay,
                "drift_hz_s": drift,
                "snr_db": round(float(snr), 4),
                "trials": trials,
                "successes": successes,
                "p_decode": successes / trials,
                "wilson95_low": lo,
                "wilson95_high": hi,
                "elapsed_s": round(time.time() - started, 3),
            }
        except Exception:
            if self.keep_failed:
                print(f"preserved failed fixture: {temp_root}", flush=True)
                temp_root = None
            raise
        finally:
            if temp_root is not None:
                shutil.rmtree(temp_root, ignore_errors=True)


def estimate_threshold(
    runner: Runner,
    spread: float,
    delay: float,
    drift: float,
    quick_trials: int,
    final_trials: int,
    resolution: float,
    snr_low: float,
    snr_high: float,
) -> tuple[dict, list[dict]]:
    samples: dict[float, dict] = {}

    def eval_at(snr: float, trials: int) -> dict:
        snr = round(snr / resolution) * resolution
        previous = samples.get(snr)
        if previous is not None and int(previous["trials"]) >= trials:
            return previous
        row = runner.evaluate(spread, delay, drift, snr, trials)
        samples[snr] = row  # replace, don't double-count repeated pseudo-random sequences
        print(
            f"{runner.mode:4s} spread={spread:5.1f} delay={delay:4.1f} "
            f"drift={drift:5.1f} snr={snr:6.2f}: "
            f"{row['successes']:3d}/{trials}={row['p_decode']:.3f}",
            flush=True,
        )
        return row

    low, high = snr_low, snr_high
    rlow = eval_at(low, quick_trials)
    rhigh = eval_at(high, quick_trials)

    while rlow["p_decode"] >= 0.5 and low > -50.0:
        high, rhigh = low, rlow
        low = max(-50.0, low - 10.0)
        rlow = eval_at(low, quick_trials)

    while rhigh["p_decode"] < 0.5 and high < 40.0:
        low, rlow = high, rhigh
        high = min(40.0, high + 10.0)
        rhigh = eval_at(high, quick_trials)

    reached = rlow["p_decode"] < 0.5 <= rhigh["p_decode"]
    if reached:
        while high - low > resolution + 1e-9:
            mid = round(((low + high) / 2.0) / resolution) * resolution
            if mid <= low or mid >= high:
                break
            rmid = eval_at(mid, quick_trials)
            if rmid["p_decode"] >= 0.5:
                high, rhigh = mid, rmid
            else:
                low, rlow = mid, rmid

        # High-statistics measurements around the transition. Repeated SNR
        # points replace the quick probe rather than being summed.
        eval_at(low, final_trials)
        eval_at(high, final_trials)
        if high - low > resolution * 0.5:
            eval_at((low + high) / 2.0, final_trials)

    rows = sorted(samples.values(), key=lambda r: float(r["snr_db"]))
    threshold = crossing_50(rows)
    if threshold is not None:
        status = "ok"
    elif all(float(r["p_decode"]) >= 0.5 for r in rows):
        status = "below_range"
    elif all(float(r["p_decode"]) < 0.5 for r in rows):
        status = "not_reached"
    else:
        status = "indeterminate"

    summary = {
        "mode": runner.mode,
        "spread_hz": spread,
        "delay_ms": delay,
        "drift_hz_s": drift,
        "threshold_50_snr2500_db": None if threshold is None else round(threshold, 3),
        "status": status,
        "search_low_db": low,
        "search_high_db": high,
        "quick_trials": quick_trials,
        "final_trials": final_trials,
        "resolution_db": resolution,
    }
    return summary, rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "mode", "condition", "spread_hz", "delay_ms", "drift_hz_s", "snr_db",
        "trials", "successes", "p_decode", "wilson95_low",
        "wilson95_high", "elapsed_s",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=MODE, required=True)
    ap.add_argument("--family", choices=("watterson", "doppler"), required=True)
    ap.add_argument("--bin-dir", type=Path, required=True)
    ap.add_argument("--source-dir", type=Path, default=Path("."))
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--quick-trials", type=int, default=24)
    ap.add_argument("--final-trials", type=int, default=96)
    ap.add_argument("--resolution-db", type=float, default=0.5)
    ap.add_argument("--snr-low", type=float, default=-30.0)
    ap.add_argument("--snr-high", type=float, default=20.0)
    ap.add_argument("--keep-failed", action="store_true")
    args = ap.parse_args()

    runner = Runner(args.mode, args.bin_dir, args.source_dir, args.keep_failed)
    if args.family == "watterson":
        conditions = [
            {"name": name, "spread": spread, "delay": delay, "drift": 0.0}
            for name, (spread, delay) in WATTERSON.items()
        ]
    else:
        conditions = [
            {"name": f"{rate:02d}hz_s", "spread": 0.0, "delay": 0.0, "drift": float(rate)}
            for rate in range(0, 21)
        ]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    all_raw: list[dict] = []
    summaries: list[dict] = []
    for c in conditions:
        print(f"\n=== {args.mode} {args.family} {c['name']} ===", flush=True)
        summary, rows = estimate_threshold(
            runner,
            c["spread"],
            c["delay"],
            c["drift"],
            args.quick_trials,
            args.final_trials,
            args.resolution_db,
            args.snr_low,
            args.snr_high,
        )
        summary["condition"] = c["name"]
        summaries.append(summary)
        for row in rows:
            row["condition"] = c["name"]
        all_raw.extend(rows)

        # Incremental checkpoint survives a later condition failure in local runs.
        (args.output_dir / "summary.json").write_text(
            json.dumps(summaries, indent=2) + "\n", encoding="utf-8"
        )
        write_csv(args.output_dir / "raw.csv", all_raw)

    with (args.output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        fields = [
            "mode", "condition", "spread_hz", "delay_ms", "drift_hz_s",
            "threshold_50_snr2500_db", "status", "search_low_db",
            "search_high_db", "quick_trials", "final_trials", "resolution_db",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(summaries)

    metadata = {
        "mode": args.mode,
        "family": args.family,
        "target_message": MODE[args.mode]["message"],
        "snr_definition": "SNR in 2500 Hz reference bandwidth (SNR_2500)",
        "watterson_conditions": WATTERSON,
        "doppler_definition": "df(t)=drift_hz_s*(t-T/2); phase=pi*drift_hz_s*(t-T/2)^2",
        "ft4_ft8_ap": "disabled by QSO progress 0 and blank my/his calls",
        "decoder_search_tolerance_hz": 500,
    }
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
