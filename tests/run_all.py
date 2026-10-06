#!/usr/bin/env python3
"""Run every test file and summarize.

    python tests/run_all.py            all tests
    python tests/run_all.py edit help  only the files whose names contain these words

Needs Playwright with Chromium and Pillow (see requirements-dev.txt).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / ".out"


def main() -> None:
    want = [a.lower() for a in sys.argv[1:]]
    files = sorted(f for f in HERE.glob("test_*.py") if not want or any(w in f.stem for w in want))
    if not files:
        print("no test files match")
        sys.exit(2)
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    failed, start = [], time.time()
    for f in files:
        proc = subprocess.run([sys.executable, str(f)], cwd=str(HERE))
        if proc.returncode != 0:
            failed.append(f.name)
    print(f"\n{len(files) - len(failed)} of {len(files)} test files passed in {time.time() - start:.0f}s")
    if failed:
        print("failed: " + ", ".join(failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
