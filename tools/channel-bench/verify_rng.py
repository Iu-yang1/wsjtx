#!/usr/bin/env python3
"""Guard against the JTTY Monte Carlo failure seen in run 38575473652."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin-dir", type=Path, required=True)
    args = ap.parse_args()
    simulator = (args.bin_dir.resolve() / "sjtty")
    if not simulator.is_file():
        raise SystemExit(f"Missing {simulator}")

    def generate(seed):
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["WSJT_SIM_SEED"] = str(seed)
            cmd = [str(simulator), "CQ K1ABC CQ", "1500", "0.10", "1", "2",
                   "384", "1", "-10"]
            result = subprocess.run(cmd, env=env, cwd=td,
                                    capture_output=True, text=True, timeout=50)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            wav = Path(td) / "000000_000001.wav"
            if not wav.exists():
                raise RuntimeError("sjtty did not produce WAV")
            return hashlib.sha256(wav.read_bytes()).hexdigest()

    first = generate(314159)
    repeat = generate(314159)
    alternate = generate(271828)
    if first != repeat:
        raise SystemExit("FAILED: same seed did not reproduce identical WAV")
    if first == alternate:
        raise SystemExit("FAILED: different seeds produced identical WAV; "
                         "check sjtty.f90 call sgran() is not commented out")
    print("JTTY RNG reproducibility PASS: same seed identical, "
          "different seeds non-identical")


if __name__ == "__main__":
    main()
