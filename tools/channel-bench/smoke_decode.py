#!/usr/bin/env python3
"""High-SNR end-to-end decoder sanity check before any expensive Monte Carlo."""
import argparse
from pathlib import Path

from run_thresholds import Runner, stable_seed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin-dir", type=Path, required=True)
    ap.add_argument("--mode", choices=["jtty", "ft4", "ft8"], required=True)
    args = ap.parse_args()
    runner = Runner(args.bin_dir.resolve(), args.mode, 120)
    # +12 dB noise (not the synthetic no-noise special value 99) exercises gating.
    for trial in range(3):
        if runner.trial("spread", "AWGN", 0., 0., 0., 12.,
                        stable_seed("smoke", args.mode, trial)):
            print(args.mode, "end-to-end decode PASS")
            return
    raise SystemExit(args.mode + ": +12 dB end-to-end decode failed")

if __name__ == "__main__":
    main()
