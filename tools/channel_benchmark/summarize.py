#!/usr/bin/env python3
from __future__ import annotations
import argparse
import csv
from pathlib import Path

def fmt(v: str) -> str:
    return "—" if v in ("", "None", "null") else v

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, required=True)
    args=ap.parse_args()

    rows=[]
    for p in sorted(args.root.rglob("summary.csv")):
        if p.resolve() == args.csv.resolve():
            continue
        with p.open(newline="",encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))

    rows.sort(key=lambda r: (
        r["mode"],
        0 if float(r["spread_hz"]) > 0 or r["condition"]=="awgn" else 1,
        float(r["spread_hz"]),
        float(r["drift_hz_s"]),
    ))
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    fields=[
        "mode","condition","spread_hz","delay_ms","drift_hz_s",
        "threshold_50_snr2500_db","status","search_low_db","search_high_db",
        "quick_trials","final_trials","resolution_db",
    ]
    with args.csv.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    lines=[
        "# JTTY / FT4 / FT8 50% decode thresholds",
        "",
        "| Mode | Condition | Spread (Hz) | Delay (ms) | Drift (Hz/s) | 50% SNR_2500 (dB) | Status |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['mode'].upper()} | {r['condition']} | {r['spread_hz']} | "
            f"{r['delay_ms']} | {r['drift_hz_s']} | "
            f"{fmt(r['threshold_50_snr2500_db'])} | {r['status']} |"
        )
    args.markdown.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
