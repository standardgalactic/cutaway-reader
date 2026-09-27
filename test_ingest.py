#!/usr/bin/env python3
"""Invariants of corpus.py add (ingest.py). Run: python3 test_ingest.py"""
import json, subprocess, sys, tempfile, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mine  # noqa: E402

passed = 0


def check(name, cond):
    global passed
    assert cond, name
    passed += 1
    print("ok  " + name)


def add(*args):
    r = subprocess.run([sys.executable, str(HERE / "corpus.py"), "add", *map(str, args)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


DOC = "\\documentclass{article}\n\\title{%s}\n\\begin{document}\n\\maketitle\n\\section{One}\n%s\n\\end{document}\n"

with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    c = t / "c"; c.mkdir()
    man = c / "corpus.json"
    man.write_text(json.dumps({"corpus": "t", "works": []}))
    M = lambda: json.loads(man.read_text())
    src = t / "in"; src.mkdir()

    (src / "a.tex").write_text(DOC % ("Arranged Things: A Study", "First draft."))
    out = add(man, src / "a.tex")
    check("a new source becomes a new work named after its main title",
          [w["id"] for w in M()["works"]] == ["arranged-things"] and "new work" in out)
    ed = M()["works"][0]["editions"][0]
    check("editions are content-addressed by the source hash",
          ed == f"works/arranged-things/{mine.source_sha256(src / 'a.tex')[:10]}.tex" and (c / ed).exists())

    before = man.read_text()
    out = add(man, src / "a.tex")
    check("adding the same source again changes nothing", man.read_text() == before and "present" in out)

    (src / "a2.tex.txt").write_text(DOC % ("Arranged Things: A Revised Study", "Second draft, longer."))
    add(man, src / "a2.tex.txt")
    check("a source with the same main title becomes another edition of that work",
          len(M()["works"]) == 1 and len(M()["works"][0]["editions"]) == 2)

    (src / "a3.tex").write_text(DOC % ("Arranged Things", "A different essay that shares the name."))
    add(man, src / "a3.tex", "--new")
    check("--new keeps a same-titled source apart as its own work",
          [w["id"] for w in M()["works"]] == ["arranged-things", "arranged-things-2"])

    (src / "b.tex").write_text(DOC % ("Unrelated Notes", "x"))
    add(man, src / "b.tex", "--as", "arranged-things")
    check("--as files a source under the named work", len(M()["works"][0]["editions"]) == 3)

    # a multi-file source in a zip, with a PDF and stray files that must not come along
    pw = t / "pw"; (pw / "app").mkdir(parents=True)
    (pw / "main.tex").write_text(DOC % ("The Portable Thing", "Body.\n\\input{app/A}\n\\bibliography{refs}"))
    (pw / "app" / "A.tex").write_text("\\section{Appendix A}\nText.")
    (pw / "refs.bib").write_text("@article{k, author={Flyxion}, title={Other Work}, year={2026}}")
    (pw / "unused.tex").write_text("\\section{Not read}")
    z = t / "pw.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in pw.rglob("*"):
            zf.write(f, f.relative_to(pw))
        zf.writestr("main.pdf", b"%PDF-1.4")
        zf.writestr("../escape.tex", "\\documentclass{article}\\begin{document}x\\end{document}")
    out = add(man, z)
    w = next(x for x in M()["works"] if x["id"] == "the-portable-thing")
    main = c / w["editions"][0]
    stored = sorted(p.relative_to(main.parent).as_posix() for p in main.parent.rglob("*") if p.is_file())
    check("a zipped multi-file source keeps exactly the files its main file reads",
          stored == ["app/A.tex", "main.tex", "refs.bib"])
    check("the stored edition hashes the same as the source it came from",
          mine.source_sha256(main) == mine.source_sha256(pw / "main.tex"))
    check("PDFs are reported and skipped, and nothing is written outside the corpus",
          "PDF has no source" in out and not (t / "escape.tex").exists() and not (c.parent / "escape.tex").exists())

    log = [json.loads(x) for x in (c / "imports.jsonl").read_text().splitlines()]
    check("every import is logged with where it came from and where it went",
          len(log) == 5 and all(x["from"] and x["work"] and x["hash"] for x in log))

    r = subprocess.run([sys.executable, str(HERE / "corpus.py"), "build", man], capture_output=True, text=True)
    check("an imported corpus builds", r.returncode == 0 and "3 works" in r.stdout)

print(f"\n{passed} import invariants hold")
