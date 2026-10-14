#!/usr/bin/env python3
"""End-to-end signal generation and exact-message decoding for the 3 profiles."""
from pathlib import Path
import argparse
from refined_thresholds import MESSAGES
from run_thresholds import Runner, stable_seed


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--bin-dir",type=Path,required=True)
    args=parser.parse_args()
    for mode,messages in MESSAGES.items():
        rx=Runner(args.bin_dir.resolve(),mode,120)
        for i,msg in enumerate(messages):
            works=False
            for n in range(3):
                works|=rx.trial("spread","AWGN",0.,0.,0.,12.,
                                stable_seed("refined-profile",mode,i,n),
                                message=msg)
                if works: break
            if not works:
                raise SystemExit(f"{mode} high-SNR exact-message smoke FAILED: {msg}")
            print(f"{mode}: {msg}: PASS",flush=True)


if __name__=="__main__":
    main()
