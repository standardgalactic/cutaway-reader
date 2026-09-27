#!/usr/bin/env python3
"""Run every test suite and summarise. Exit status is non-zero if any suite fails.
  python3 test_all.py            all suites
  python3 test_all.py --fast     skip the browser suite"""
import re, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = [
    ("model", ["node", "test_model.js"]),
    ("corpus model", ["node", "test_corpus.js"]),
    ("placement", [sys.executable, "test_corpus_build.py"]),
    ("manifest", [sys.executable, "test_manifest.py"]),
    ("import", [sys.executable, "test_ingest.py"]),
    ("schemas", [sys.executable, "test_schema.py"]),
    ("browser", [sys.executable, "test_viewer.py"]),
]

failed = 0
for name, cmd in SUITES:
    if name == "browser" and "--fast" in sys.argv:
        continue
    t = time.time()
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    n = re.search(r"(\d+) .*hold", last)
    ok = r.returncode == 0 and n
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name:13} {n.group(1) if n else '-':>3} checks  {time.time() - t:5.1f}s"
          + ("" if ok else "\n" + (r.stdout + r.stderr)[-1500:]))
sys.exit(1 if failed else 0)
