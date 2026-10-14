#!/usr/bin/env python3
"""Merge GitHub Actions artifacts without silently inventing missing thresholds."""
import csv
import json
import sys
from pathlib import Path

FIELDS = ["mode", "kind", "condition", "spread_hz", "delay_ms", "drift_hz_s",
          "status", "p50_snr_2500_db", "bound_db", "total_trials"]


def main():
    src = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    dest.mkdir(parents=True, exist_ok=True)
    collected = []
    raw = []
    for f in sorted(src.rglob("results.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        collected.extend(data["results"])
    for f in sorted(src.rglob("points.csv")):
        with f.open(newline="", encoding="utf-8") as h:
            raw.extend(list(csv.DictReader(h)))
    with (dest / "thresholds.csv").open("w", newline="", encoding="utf-8") as h:
        writer = csv.DictWriter(h, FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(collected)
    if raw:
        with (dest / "points.csv").open("w", newline="", encoding="utf-8") as h:
            writer = csv.DictWriter(h, raw[0].keys())
            writer.writeheader()
            writer.writerows(raw)
    found = {(r["mode"], r["kind"], r["condition"]) for r in collected}
    expected = {(m, "spread", c) for m in ("jtty", "ft4", "ft8")
                for c in ("AWGN", "MD", "HM", "HD")}
    expected |= {(m, "drift", "DRIFT_%02d" % d)
                 for m in ("jtty", "ft4", "ft8") for d in range(21)}
    missing = sorted(expected-found)
    def value(row):
        if row["status"] == "interpolated":
            return "%.2f" % row["p50_snr_2500_db"]
        return "%s (%s dB)" % (row["status"], row.get("bound_db", "?"))
    out = ["# WSJT-X channel robustness: 50% decoding probability",
           "", "SNR is referred to a 2500 Hz noise bandwidth (SNR_2500).",
           "Thresholds are Monte Carlo estimates; no invented values or extrapolation.",
           "One JTTY frame is not the same semantic information payload as FT8/FT4.",
           "AP disabled for FT4/FT8. Watterson and chirp are separate experiments.",
           ""]
    for kind in ("spread", "drift"):
        out += ["## "+kind, "", "| Mode | Condition | P50 / censoring | Trials |",
                "|---|---|---:|---:|"]
        for r in sorted((x for x in collected if x["kind"] == kind),
                        key=lambda x: (x["mode"], x["drift_hz_s"]
                                       if kind=="drift" else x["spread_hz"])):
            out.append("| %s | %s | %s | %s |" %
                       (r["mode"], r["condition"], value(r), r["total_trials"]))
        out.append("")
    if missing:
        out += ["## Incomplete conditions", "",
                "%s of 75 expected conditions are missing; failed/unfinished "
                "runs must **not** be interpreted as decode failure." % len(missing),
                "", ", ".join("%s/%s/%s" % k for k in missing), ""]
    else:
        out += ["All 75 requested separate-mode conditions have recorded results.", ""]
    (dest/"summary.md").write_text("\n".join(out), encoding="utf-8")
    (dest/"metadata.json").write_text(
        json.dumps({"expected_conditions": len(expected),
                    "recorded_conditions": len(found),
                    "missing": missing}, indent=2)+"\n", encoding="utf-8")
    print("Report:", len(found), "of", len(expected), "conditions")


if __name__ == "__main__":
    main()
