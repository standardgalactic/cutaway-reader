#!/usr/bin/env python3
"""Invariants of lanes and series declared in the manifest (corpus.py link/unlink/links/series).
Run: python3 test_manifest.py"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
passed = 0


def check(name, cond):
    global passed
    assert cond, name
    passed += 1
    print("ok  " + name)


def run(*args, ok=True):
    r = subprocess.run([sys.executable, str(HERE / "corpus.py"), *map(str, args)], capture_output=True, text=True)
    if ok and r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return r


with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    shutil.copytree(HERE / "corpus" / "works", t / "works")
    shutil.copy(HERE / "corpus" / "corpus.json", t / "corpus.json")
    man = t / "corpus.json"
    M = lambda: json.loads(man.read_text())
    G = lambda: json.loads((t / "data" / "corpus.graph.json").read_text())
    run("build", man)
    ledger0 = json.loads((t / "data" / "corpus.ledger.json").read_text())

    # a lane by heading: resolved to the chamber's stable id at build time
    wg = json.loads((t / "data" / "works" / "two-games.graph.json").read_text())
    sec = next(n for n in wg["nodes"] if n["level"] == "section" and n["role"] != "appendix" and n["order"] > 0)
    run("link", man, f"two-games@{sec['title']}", "document-repositories", "--note", "the same ledger idea")
    check("link writes the lane into the manifest, not into a source",
          M()["lanes"] == [{"from": "two-games", "from_chamber": sec["title"], "to": "document-repositories",
                            "note": "the same ledger idea"}])
    run("build", man)
    lane = next(l for l in G()["lanes"] if l.get("declared_in") == "manifest")
    check("the build resolves the heading to the chamber's id and draws a declared exit",
          lane["from_chamber"] == sec["id"] and lane["kind"] == "exit" and lane["traversal"] == "two-way"
          and lane["note"] == "the same ledger idea")
    check("declaring a lane never moves a placed work",
          {w: p["pos"] for w, p in json.loads((t / "data" / "corpus.ledger.json").read_text())["works"].items()}
          == {w: p["pos"] for w, p in ledger0["works"].items()})

    r = run("link", man, "two-games@No Such Heading", "automap-spec", ok=False)
    check("a chamber that does not exist is refused before it reaches the manifest",
          r.returncode != 0 and len(M()["lanes"]) == 1)
    run("link", man, f"two-games@{sec['title']}", "document-repositories")
    check("the same lane is not declared twice", len(M()["lanes"]) == 1)

    # a manifest lane answering a source exit coalesces with it, as two source exits do
    src = json.loads((t / "data" / "works" / "two-games.graph.json").read_text())
    ex = next(e for e in src["edges"] if e["kind"] == "exit" and e["to"].startswith("work:memorable-interfaces#"))
    arrive, opens = ex["to"].split("#")[1], ex["from"]          # two-games opens at `opens`, lands at `arrive`
    run("link", man, f"memorable-interfaces@{arrive}", "two-games#" + opens[2:])
    run("build", man)
    between = [l for l in G()["lanes"] if l["kind"] == "exit" and {l["from"], l["to"]} == {"two-games", "memorable-interfaces"}]
    check("a manifest lane that answers a source exit between the same chambers is one passage",
          len(between) == 2 and sum(l.get("declared") == "both ends" for l in between) == 1)

    run("link", man, "document-repositories", "a-work-not-yet-here", "--oneway")
    run("build", man)
    far = next(l for l in G()["lanes"] if l["to"] == "a-work-not-yet-here")
    check("a lane to a work not in the corpus is kept as uncharted, and one-way when declared so",
          far.get("uncharted") and far["traversal"] == "one-way")

    listing = run("links", man).stdout
    check("links numbers what is declared", "1. two-games" in listing and "3. document-repositories" in listing)
    run("unlink", man, 3)
    check("unlink removes exactly the numbered lane", [d["to"] for d in M()["lanes"]] == ["document-repositories", "two-games"])

    # promoting a suggestion
    g = G(); g["suggestions"] = [{"from": "automap-spec", "chamber": "x", "chamber_title": sec["title"], "to": "two-games", "count": 2}]
    (t / "data" / "corpus.graph.json").write_text(json.dumps(g))
    r = run("link", man, "--suggestion", 1, ok=False)
    check("a suggestion whose chamber is gone is refused rather than guessed", r.returncode != 0)

    # series
    run("series", man, "notes", "Notes", "document-repositories", "two-games", ok=False)
    r = run("series", man, "notes", "Notes", "document-repositories", "two-games", ok=False)
    check("a work already in one series cannot join another", r.returncode != 0 and "cutaway" in (r.stdout + r.stderr))
    run("series", man, "cutaway", "The Cutaway Reader", "two-games", "memorable-interfaces", "automap-spec")
    run("build", man)
    s = [(l["from"], l["to"]) for l in G()["lanes"] if l["kind"] == "series"]
    check("series sets the reading order the build draws",
          s == [("two-games", "memorable-interfaces"), ("memorable-interfaces", "automap-spec")])
    run("series", man, "cutaway", "--remove")
    run("build", man)
    check("a removed series leaves no lanes and no member marks",
          not [l for l in G()["lanes"] if l["kind"] == "series"] and not any(w.get("series") for w in M()["works"]))

    # the report: built on the same corpus
    run("report", t / "data")
    rep = json.loads((t / "data" / "report.json").read_text())
    md = (t / "data" / "report.md").read_text()
    check("the report puts undecided editions first, with how each differs from the proposed one",
          md.index("Waiting for a decision") < md.index("How the corpus connects")
          and [u["work"] for u in rep["undecided_editions"]] == ["automap-spec"]
          and any(e["proposed"] for e in rep["undecided_editions"][0]["editions"]))
    check("the report's groups cover every work exactly once",
          sorted(w for c in rep["groups"] for w in c) == sorted(w["id"] for w in M()["works"]))

print(f"\n{passed} manifest invariants hold")
