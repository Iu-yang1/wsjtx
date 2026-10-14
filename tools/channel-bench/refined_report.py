#!/usr/bin/env python3
"""Merge refined experimental results and plot measured QEX-style figures."""
import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from refined_thresholds import ITU, DRIFT_LOW, DRIFT_HIGH

MODES=("jtty","ft4","ft8")
FIELDS=("mode","group","condition","spread_hz","delay_ms","drift_hz_s",
        "status","p50_snr_2500_db","p50_model_interval_95_db",
        "total_trials","end_success_probability","end_wilson95",
        "nonmonotone_confident_steps")
QEX={
    "AWGN":{"ft4":-17.5,"ft8":-20.8},
    "MD":{"ft4":-15.2,"ft8":-18.6},
    "HM":{"ft4":-12.2,"ft8":-8.6},
}

def main():
    origin,dest=map(Path,sys.argv[1:3])
    dest.mkdir(parents=True,exist_ok=True)
    records=[]
    points=[]
    trials=[]
    for f in sorted(origin.rglob("results.json")):
        records += json.loads(f.read_text(encoding="utf8"))["results"]
    for f in sorted(origin.rglob("points.csv")):
        with f.open(newline="",encoding="utf8") as h: points+=list(csv.DictReader(h))
    for f in sorted(origin.rglob("trials.csv")):
        with f.open(newline="",encoding="utf8") as h: trials+=list(csv.DictReader(h))
    expected={(m,"spread",s) for m in MODES for s in ITU}
    expected|={(m,"drift-low","RATE_%05.2f"%r)
               for m in MODES for r in DRIFT_LOW}
    expected|={(m,"drift-high","RATE_%05.2f"%r)
               for m in MODES for r in DRIFT_HIGH}
    found={(r["mode"],r["group"],r["condition"]) for r in records}
    missing=sorted(expected-found)
    unexpected=sorted(found-expected)
    if len(records)!=len(found):
        raise RuntimeError("Duplicate refined conditions found in outputs")
    with (dest/"thresholds.csv").open("w",newline="",encoding="utf8") as h:
        w=csv.DictWriter(h,fieldnames=FIELDS,extrasaction="ignore")
        w.writeheader()
        for r in records:
            r=r.copy()
            for key in ("p50_model_interval_95_db","end_wilson95",
                        "nonmonotone_confident_steps"):
                r[key]=json.dumps(r.get(key))
            w.writerow(r)
    if points:
        with (dest/"points.csv").open("w",newline="",encoding="utf8") as h:
            w=csv.DictWriter(h,fieldnames=points[0].keys())
            w.writeheader()
            w.writerows(points)
    if trials:
        with (dest/"trials.csv").open("w",newline="",encoding="utf8") as h:
            w=csv.DictWriter(h,fieldnames=trials[0].keys())
            w.writeheader()
            w.writerows(trials)
    index={(r["mode"],r["group"],r["condition"]):r for r in records}
    from collections import defaultdict
    by_points=defaultdict(list)
    for p in points:
        by_points[(p["mode"],p["group"],p["condition"])].append(p)
    plt.rcParams.update({"font.size":9,"figure.dpi":130,"savefig.dpi":220})
    fig,axes=plt.subplots(2,3,figsize=(12,7),sharex=True,sharey=True)
    for axis,(name,(spread,delay)) in zip(axes.flatten(),ITU.items()):
        for mode in MODES:
            rows=sorted(by_points.get((mode,"spread",name),[]),
                        key=lambda r:float(r["snr_2500_db"]))
            if not rows: continue
            x=np.array([float(v["snr_2500_db"]) for v in rows])
            y=np.array([float(v["probability"]) for v in rows])
            lo=np.array([float(v["wilson_low"]) for v in rows])
            hi=np.array([float(v["wilson_high"]) for v in rows])
            line,=axis.plot(x,y,marker=".",markersize=3,linewidth=1,label=mode.upper())
            axis.fill_between(x,lo,hi,alpha=.16,color=line.get_color())
        axis.axhline(.5,color="0.45",linestyle="--",linewidth=.6)
        axis.set_title(f"{name}: {spread:g} Hz spread, {delay:g} ms delay")
        axis.set_ylim(-.03,1.03)
        axis.set_xlim(-30,20)
        axis.grid(alpha=.2)
    for a in axes[-1,:]:a.set_xlabel(r"SNR$_{2500}$ (dB)")
    for a in axes[:,0]:a.set_ylabel("Decode probability")
    axes[0,0].legend(loc="lower right")
    fig.suptitle("WSJT-X JTTY / FT4 / FT8 — measured decode probability",
                 fontsize=14,weight="bold")
    fig.text(.5,.01,"Shading = Wilson 95% interval at each SNR; three-message ensemble; no AP.",
             ha="center",fontsize=8)
    fig.tight_layout(rect=[0,.02,1,.96])
    for ext in ("png","svg"):
        fig.savefig(dest/f"figure1_qex_probability.{ext}")
    plt.close(fig)

    fig,ax=plt.subplots(figsize=(11,5))
    x=np.arange(len(ITU))
    width=.25
    for j,mode in enumerate(MODES):
        y=[]
        for key in ITU:
            r=index.get((mode,"spread",key))
            y.append(float(r["p50_snr_2500_db"]) if r and r["status"]=="estimated"
                    else np.nan)
        bars=ax.bar(x+(j-1)*width,y,width,label=mode.upper(),alpha=.82)
        for bar,value in zip(bars,y):
            if np.isfinite(value):
                ax.text(bar.get_x()+bar.get_width()/2,value-0.7,
                        f"{value:.1f}",ha="center",va="top",fontsize=8)
    ax.set_xticks(x,list(ITU))
    ax.set_ylabel(r"50% decode SNR$_{2500}$ (dB); lower is better")
    ax.set_title("ITU-R F.1487 Watterson — 50% decoding thresholds")
    ax.legend()
    ax.grid(axis="y",alpha=.25)
    fig.tight_layout()
    for ext in ("png","svg"):
        fig.savefig(dest/f"figure2_itu_thresholds.{ext}")
    plt.close(fig)

    fig,ax=plt.subplots(figsize=(11,5.5))
    for mode in MODES:
        rs=sorted((r for r in records if r["mode"]==mode and
                   r["group"].startswith("drift")),
                  key=lambda r:r["drift_hz_s"])
        x=[r["drift_hz_s"] for r in rs if r["status"]=="estimated"]
        y=[r["p50_snr_2500_db"] for r in rs if r["status"]=="estimated"]
        if not x:continue
        ax.plot(x,y,marker="o",linewidth=1.5,markersize=4,label=mode.upper())
        xs=[r["drift_hz_s"] for r in rs if r["status"]!="estimated"]
        if xs:
            ax.scatter(xs,[21]*len(xs),marker="x",s=25)
    ax.set_xlabel("Uncompensated linear Doppler rate (Hz/s), signal-only injection")
    ax.set_ylabel(r"SNR$_{2500}$ at 50% decode (dB)")
    ax.set_title("Deterministic Doppler robustness (× above frame = unresolved)")
    ax.grid(alpha=.3)
    ax.legend()
    fig.tight_layout()
    for ext in ("png","svg"):
        fig.savefig(dest/f"figure3_doppler_rate.{ext}")
    plt.close(fig)

    notes=["# Refined JTTY / FT4 / FT8 QEX-style measurements","",
       f"**Recorded:** {len(found)}/{len(expected)} conditions; "+
       f"**Trials:** {len(trials):,}.",
       "Models: two-path Watterson (ITU-R F.1487) or native TX-only chirp + AWGN.",
       "Pilot coarse SNR grid and predeclared three-message ensemble; SNR50 is "+
       "an isotonic 50% crossing, with model-based Jeffreys-beta posterior interval.",
       "Unresolved conditions are NOT assigned a fabricated SNR50.",
       "",
       "## Watterson summary","",
       "|Channel|JTTY|FT4|FT8|QEX FT4 / FT8 (reference)|",
       "|---|---:|---:|---:|---|"]
    def display(r):
        if not r:return "missing"
        if r["status"]=="estimated":
            ci=r.get("p50_model_interval_95_db")
            return f'{r["p50_snr_2500_db"]:.2f} dB'+(
                f" [{ci[0]:.2f}, {ci[1]:.2f}]" if ci else " (CI unresolved)")
        return str(r["status"])
    for key in ITU:
        vals=[display(index.get((mode,"spread",key))) for mode in MODES]
        ref=QEX.get(key,{})
        notes.append(f'|{key}|'+ "|".join(vals) +"|"+
                     (f'{ref["ft4"]:.1f} / {ref["ft8"]:.1f} dB' if ref else "—")+"|")
    notes += ["","## Validity gates","",
       f"- Missing conditions: {missing or 'none'}",
       f"- Unexpected conditions: {unexpected or 'none'}",
       "- Each condition stores all attempted per-trial seeds and exact decoded-message matches.",
       "- Correlations between SNR conditions are intentionally induced by reusing trial seed (paired common random numbers), not independent SNR samples.",
       "- Interval estimates are model-based and do not account for waveform/calibration systematic errors.",
       "- FT4/FT8 packets and JTTY atoms carry different useful application information; do not interpret SNR50 ranking alone as throughput superiority.",
       "",
       "## Source",
       "[Franke, Somerville, Taylor, QEX 2020](https://wsjt.sourceforge.io/FT4_FT8_QEX.pdf)",
       "[GitHub Actions refined branch](https://github.com/Iu-yang1/wsjtx/tree/bench/refined-channel-robustness)",
    ]
    (dest/"summary.md").write_text("\n".join(notes)+"\n",encoding="utf8")
    (dest/"metadata.json").write_text(json.dumps({
        "expected_conditions":len(expected),"found_conditions":len(found),
        "missing":missing,"unexpected":unexpected,
        "individual_trials":len(trials)},indent=2),encoding="utf8")
    print(f"Refined report: {len(found)}/{len(expected)} conditions; {len(trials)} trials")
    if missing or unexpected:
        raise SystemExit("ERROR: incomplete or unexpected condition set")


if __name__=="__main__":
    main()
