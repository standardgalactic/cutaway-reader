#!/usr/bin/env python3
"""
ingest.py: bring sources into a corpus without hand-editing the manifest.

  python3 corpus.py add corpus.json PATH... [--as WORK] [--new] [--dry-run]

PATH may be a .tex file (also .tex.txt, as chat attachments arrive), a folder, or a .zip.
Inside a folder or zip, every file that contains \\documentclass and \\begin{document} is a
main file; the edition is that main file plus exactly the files it reads (\\input, \\include,
.bib), nothing else. PDFs and other files are reported and skipped: a PDF has no source.

Where each source goes, decided in this order and always printed:
  1. already present: some work already holds an edition with the same source hash -> nothing to do
  2. --as WORK: an edition of that work (created if it does not exist)
  3. same main title as an existing work (the part before the first colon) -> a new edition of it
  4. otherwise a new work, its id the slug of the main title
--new skips step 3, for two different works that happen to share a main title.

Editions are content-addressed: works/<id>/<hash10>.tex, or works/<id>/<hash10>/<main path>
for a source spread over several files. The manifest only ever gains entries. Every import is
appended to imports.jsonl beside the manifest (what came in, under which name, where it went).
"""
import datetime, json, re, shutil, sys, tempfile, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mine  # noqa: E402

KEEP = {".tex", ".bib", ".sty", ".cls", ".bst", ".txt"}


def is_main(text):
    return "\\documentclass" in text and "\\begin{document}" in text


def main_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower().split(":")[0]).strip()


def slug(s, limit=48):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:limit].rstrip("-") or "untitled"


def candidates(path, scratch, notes):
    """(main file, root folder, original name) for every source found under path."""
    path = Path(path)
    if path.is_file() and path.suffix.lower() == ".zip":
        dest = Path(tempfile.mkdtemp(dir=scratch))
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                name = Path(info.filename)
                if info.is_dir() or name.is_absolute() or ".." in name.parts:
                    continue  # never write outside the scratch folder
                if name.suffix.lower() in KEEP:
                    target = dest / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(z.read(info))
                elif name.suffix.lower() == ".pdf":
                    notes.append(f"skipped {path.name}:{info.filename} (a PDF has no source)")
        return [(m, r, f"{path.name}:{m.relative_to(dest)}") for m, r, _ in candidates(dest, scratch, notes)]
    if path.is_dir():
        out = []
        for f in sorted(path.rglob("*")):
            if f.is_file() and f.suffix.lower() in (".tex", ".txt"):
                try:
                    if is_main(f.read_text(encoding="utf-8", errors="replace")):
                        out.append((f, f.parent, str(f)))
                except OSError:
                    pass
        if not out:
            notes.append(f"skipped {path} (no file with \\documentclass and \\begin{{document}})")
        return out
    if path.is_file():
        if path.suffix.lower() == ".pdf":
            notes.append(f"skipped {path.name} (a PDF has no source)")
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
        if not is_main(text):
            notes.append(f"skipped {path.name} (not a LaTeX document)")
            return []
        return [(path, path.parent, path.name)]
    notes.append(f"skipped {path} (not found)")
    return []


def display_name(original):
    """Chat uploads arrive as '<8 hex>-name'; keep the author's name."""
    name = Path(str(original).split(":")[-1]).name
    return re.sub(r"^[0-9a-f]{8}-", "", name)


def store(main, root, dest_dir, digest):
    """Copy one edition into the corpus. Returns its manifest path relative to the manifest folder."""
    _, files, _, _ = mine.load_source(main)
    if len(files) == 1:
        target = dest_dir / f"{digest[:10]}.tex"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(main, target)
        return target
    base = dest_dir / digest[:10]
    for f in files:
        q = base / f.relative_to(main.parent)
        q.parent.mkdir(parents=True, exist_ok=True)
        if not q.exists():
            shutil.copyfile(f, q)
    return base / main.name


def add(manifest_path, paths, as_work=None, force_new=False, dry=False):
    mpath = Path(manifest_path)
    base = mpath.parent
    man = json.loads(mpath.read_text())
    works = {w["id"]: w for w in man["works"]}
    # what is already here: source hash -> work, main title -> work
    by_hash, by_title = {}, {}
    for w in man["works"]:
        for e in w["editions"]:
            p = base / e
            if p.exists():
                by_hash[mine.source_sha256(p)] = w["id"]
                t = mine.title_of(mine.load_source(p)[0])
                if t:
                    by_title.setdefault(main_title(t), w["id"])
    notes, log, stamp = [], [], datetime.datetime.now().isoformat(timespec="seconds")
    with tempfile.TemporaryDirectory() as scratch:
        found = [c for p in paths for c in candidates(p, scratch, notes)]
        for main, root, original in found:
            digest = mine.source_sha256(main)
            text, files, _, missing = mine.load_source(main)
            title = mine.title_of(text) or display_name(original)
            if digest in by_hash:
                log.append({"what": "present", "work": by_hash[digest], "from": display_name(original), "hash": digest[:10]})
                continue
            if as_work:
                wid, how = as_work, "as requested"
            elif not force_new and main_title(title) in by_title:
                wid, how = by_title[main_title(title)], "same main title"
            else:
                wid = slug(main_title(title) or display_name(original))
                n = 2
                while wid in works:
                    wid, n = f"{slug(main_title(title))}-{n}", n + 1
                how = "new work"
            rel = None
            if not dry:
                rel = store(main, root, base / "works" / wid, digest).relative_to(base).as_posix()
                if wid not in works:
                    works[wid] = {"id": wid, "editions": []}
                    man["works"].append(works[wid])
                if rel not in works[wid]["editions"]:
                    works[wid]["editions"].append(rel)
            by_hash[digest] = wid
            by_title.setdefault(main_title(title), wid)
            entry = {"what": "edition" if how != "new work" else "work", "work": wid, "how": how, "title": title,
                     "from": display_name(original), "hash": digest[:10], "files": len(files), "path": rel}
            if missing:
                entry["missing"] = missing
            log.append(entry)
        if not dry and any(x["what"] != "present" for x in log):
            mpath.write_text(json.dumps(man, indent=2) + "\n")
            with (base / "imports.jsonl").open("a") as f:
                for x in log:
                    if x["what"] != "present":
                        f.write(json.dumps({"at": stamp, **x}) + "\n")
    for x in log:
        if x["what"] == "present":
            print(f"  present   {x['from']} is already {x['work']} ({x['hash']})")
        else:
            extra = f", {x['files']} files" if x["files"] > 1 else ""
            miss = f"; names missing files: {', '.join(x['missing'])}" if x.get("missing") else ""
            print(f"  {'new work ' if x['what'] == 'work' else 'edition  '} {x['from']} -> {x['work']} "
                  f"({x['how']}; {x['hash']}{extra}){miss}")
    for n in notes:
        print("  " + n)
    if dry:
        print("  (dry run: nothing written)")
    return log


if __name__ == "__main__":
    sys.exit(__doc__)
