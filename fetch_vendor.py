#!/usr/bin/env python3
"""
fetch_vendor.py: regenerate vendor/ from npm with pinned versions and verified hashes.

  python3 fetch_vendor.py            # download, verify tarball + file SHA-256, write vendor/
  python3 fetch_vendor.py --verify   # only check the files already in vendor/ against vendor/lock.json

Needs `npm` (for `npm pack`) and network access to the npm registry. Nothing is written
unless every tarball and every extracted file matches vendor/lock.json.
"""
import hashlib, json, shutil, subprocess, sys, tarfile, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor"
LOCK = json.loads((VENDOR / "lock.json").read_text())
sha = lambda b: hashlib.sha256(b).hexdigest()


def verify():
    bad = []
    for p in LOCK["packages"]:
        for f in p["files"].values():
            path = VENDOR / f["dest"]
            if not path.exists() or sha(path.read_bytes()) != f["sha256"]:
                bad.append(f["dest"])
    return bad


if "--verify" in sys.argv:
    bad = verify()
    print("vendor/ matches lock.json" if not bad else "MISMATCH: " + ", ".join(bad))
    sys.exit(1 if bad else 0)

with tempfile.TemporaryDirectory() as tmp:
    staged = Path(tmp) / "staged"
    for p in LOCK["packages"]:
        spec = f'{p["name"]}@{p["version"]}'
        subprocess.run(["npm", "pack", spec, "--silent", "--pack-destination", tmp], check=True, stdout=subprocess.DEVNULL)
        tgz = Path(tmp) / p["tarball"]
        if sha(tgz.read_bytes()) != p["tarball_sha256"]:
            sys.exit(f"{spec}: tarball hash does not match lock.json; refusing to continue")
        with tarfile.open(tgz) as t:
            for src, f in p["files"].items():
                data = t.extractfile(src).read()
                if sha(data) != f["sha256"]:
                    sys.exit(f"{spec}: {src} hash does not match lock.json")
                dest = staged / f["dest"]; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data)
        print(f"ok  {spec}")
    for p in staged.rglob("*"):
        if p.is_file():
            d = VENDOR / p.relative_to(staged); d.parent.mkdir(parents=True, exist_ok=True); shutil.copy(p, d)
print("vendor/ regenerated and verified")
