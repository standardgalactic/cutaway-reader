#!/usr/bin/env python3
"""Invariants of corpus.py (placement ledger). Run: python3 test_corpus_build.py"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "corpus"
passed = 0


def run(*args, ok=True):
    r = subprocess.run([sys.executable, str(HERE / "corpus.py"), *map(str, args)], capture_output=True, text=True)
    if ok and r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return r


def check(name, cond):
    global passed
    assert cond, name
    passed += 1
    print("ok  " + name)


with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    a, b = t / "a", t / "b"
    shutil.copytree(SRC / "works", a / "works"); shutil.copytree(SRC / "works", b / "works")
    man = json.loads((SRC / "corpus.json").read_text())
    (a / "corpus.json").write_text(json.dumps(man))
    run("build", a / "corpus.json")
    L = lambda d: json.loads((d / "data" / "corpus.ledger.json").read_text())
    first = {w: p["pos"] for w, p in L(a)["works"].items()}

    r2 = run("build", a / "corpus.json")
    check("rebuilding never moves a placed work", {w: p["pos"] for w, p in L(a)["works"].items()} == first)
    check("an unchanged corpus is not mined again", "mined 0, unchanged 4" in r2.stdout)
    src = a / "works" / "two-games.tex"
    src.write_text(src.read_text().replace("\\end{document}", "One more sentence.\n\\end{document}"))
    r3 = run("build", a / "corpus.json")
    check("an edited source re-mines that work alone", "mined 1, unchanged 3" in r3.stdout)
    gp = a / "data" / "works" / "two-games.graph.json"
    g = json.loads(gp.read_text()); g["miner"] = "older-miner"; gp.write_text(json.dumps(g))
    check("a work mined by another version of the miner is mined again",
          "mined 1, unchanged 3" in run("build", a / "corpus.json").stdout)
    recs = json.loads((a / "data" / "corpus.graph.json").read_text())["works"]
    check("parse notes are kept on each work, each with a kind and a severity",
          all(isinstance(x, dict) and x["severity"] in ("problem", "advice") and x["kind"] for r in recs for x in r["warnings"]))

    import math
    led = L(a)["works"]
    anchored = [(w, p) for w, p in led.items() if p["placed_near"]]
    check("a clearly closer resemblance (twice as similar) is also nearer in the galaxy",
          all(math.dist(p["pos"], led[x["work"]]["pos"]) < math.dist(p["pos"], led[y["work"]]["pos"])
              for w, p in anchored for x in p["placed_near"] for y in p["placed_near"]
              if x["similarity"] >= 2 * max(y["similarity"], 0.05)))
    ws = list(L(a)["works"].values())
    check("no two systems closer than the minimum gap",
          all(((p["pos"][0] - q["pos"][0]) ** 2 + (p["pos"][1] - q["pos"][1]) ** 2 + (p["pos"][2] - q["pos"][2]) ** 2) ** 0.5 >= 45
              for i, p in enumerate(ws) for q in ws[i + 1:]))

    check("a multi-edition work without a declared choice is proposed, not decided",
          L(a)["editions"]["automap-spec"]["how"] == "proposed")
    run("choose", a / "data", "automap-spec", "works/automap-spec.tex")
    run("build", a / "corpus.json")
    check("an edition decision survives rebuilds", L(a)["editions"]["automap-spec"]["how"] == "decided")

    # Galaxy B agrees with ours on the first works and disagrees later; galaxy C omits a work and disagrees
    # everywhere else. After both merges "alternative 1" means B for some works and C for others.
    order = [w["id"] for w in man["works"]]
    byid = {w["id"]: w for w in man["works"]}
    (b / "corpus.json").write_text(json.dumps(dict(man, works=[byid[i] for i in order[:2] + order[:1:-1]])))
    run("build", b / "corpus.json")
    c = t / "c"; shutil.copytree(SRC / "works", c / "works")
    (c / "corpus.json").write_text(json.dumps(dict(man, works=[byid[i] for i in reversed(order) if i != "document-repositories"],
                                                    series={})))
    run("build", c / "corpus.json")
    gB, gC = L(b)["galaxy_id"], L(c)["galaxy_id"]
    check("every galaxy has its own permanent identity", len({L(a)["galaxy_id"], gB, gC}) == 3)
    run("merge", a / "data", b / "data" / "corpus.ledger.json")
    run("merge", a / "data", c / "data" / "corpus.ledger.json")
    first_alt = {w: p["conflicts"][0]["galaxy"] for w, p in L(a)["works"].items() if p.get("conflicts")}
    check("after two merges, ordinal 1 points at different galaxies for different works",
          len(set(first_alt.values())) == 2 and {w: p["pos"] for w, p in L(a)["works"].items()} == first)
    raw = (a / "data" / "corpus.ledger.json").read_text()
    check("merge provenance names galaxies and ledger hashes, never file paths",
          str(t) not in raw and "ledger_sha256" in raw and gC in raw)

    # a single resolution, tried on a copy so the two-merge state stays intact for adoption
    snapshot = (a / "data" / "corpus.ledger.json").read_text()
    target = sorted(first_alt)[0]
    r = run("resolve", a / "data", target, 1, ok=False)
    check("a single resolution is applied or refused as a whole, never stacking systems",
          (r.returncode != 0 and "refused" in r.stdout + r.stderr and (a / "data" / "corpus.ledger.json").read_text() == snapshot)
          or (r.returncode == 0 and not L(a)["works"][target].get("conflicts")))
    (a / "data" / "corpus.ledger.json").write_text(snapshot)

    cpos = {w: p["pos"] for w, p in L(c)["works"].items()}
    b_first = [w for w, g in first_alt.items() if g == gB and any(x.get("galaxy") == gC for x in L(a)["works"][w]["conflicts"])]
    run("adopt", a / "data", gC)
    after = L(a)["works"]
    c_disagreed = [w for w in cpos if w in first and cpos[w] != first[w]]
    check("adopting galaxy C takes C's placement wherever C disagreed, chosen by identity not by position in the list",
          c_disagreed and all(after[w]["pos"] == cpos[w] for w in c_disagreed) and b_first
          and all(after[w]["pos"] == cpos[w] for w in b_first))
    check("works galaxy C never placed keep their place", after["document-repositories"]["pos"] == first["document-repositories"])

    before = L(a)["works"]["document-repositories"]["pos"]
    (a / "wd.json").write_text(json.dumps(dict(man, works=[w for w in man["works"] if w["id"] != "document-repositories"])))
    run("build", a / "wd.json", "--out", a / "data")
    check("a work removed from the manifest is withdrawn, keeping its place",
          L(a)["works"]["document-repositories"]["status"] == "withdrawn" and L(a)["works"]["document-repositories"]["pos"] == before)
    run("build", a / "corpus.json")
    check("restoring it brings the same system back", L(a)["works"]["document-repositories"]["status"] == "active"
          and L(a)["works"]["document-repositories"]["pos"] == before)

# reciprocal exits: one relationship when each lands where the other opens, two passages otherwise
with tempfile.TemporaryDirectory() as t:
    t = Path(t); (t / "works").mkdir()
    doc = lambda title, secs: "\\documentclass{article}\n\\title{%s}\n\\begin{document}\n%s\\end{document}\n" % (title, secs)
    (t / "works/x.tex").write_text(doc("X", "\\section{One}\\label{sec:x1}\n% mine: exit=y#sec:y1\nText of one.\n\\section{Two}\\label{sec:x2}\n% mine: exit=y#sec:y2\nText of two.\n"))
    (t / "works/y.tex").write_text(doc("Y", "\\section{Uno}\\label{sec:y1}\n% mine: exit=x#sec:x1\nTexto uno.\n\\section{Dos}\\label{sec:y2}\n% mine: exit=x#sec:x1\nTexto dos.\n"))
    (t / "corpus.json").write_text(json.dumps({"corpus": "pair", "works": [{"id": "x", "editions": ["works/x.tex"]}, {"id": "y", "editions": ["works/y.tex"]}]}))
    r = run("build", t / "corpus.json")
    lanes = json.loads((t / "data/corpus.graph.json").read_text())["lanes"]
    both = [l for l in lanes if l.get("declared") == "both ends"]
    check("reciprocal exits that join the same two chambers become one lane declared from both ends",
          len(both) == 1 and {both[0]["from_chamber"], "L:" + both[0]["to_label"]} == {"L:sec:x1", "L:sec:y1"})
    check("reciprocal exits from different sections stay two passages, and the build says so",
          len(lanes) == 3 and "parallel lanes" in r.stdout)

print(f"\n{passed} placement invariants hold")
