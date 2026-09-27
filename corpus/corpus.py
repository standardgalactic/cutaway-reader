#!/usr/bin/env python3
"""
corpus.py: many works -> one corpus, with the same two-artifact split as a single work.

  corpus.graph.json   meaning, recomputed every run:
                      work records (title, abstract, provenance, editions, counts, series),
                      lanes between works (declared exits, series order), declared views
  corpus.ledger.json  remembered place, append-only:
                      one fixed galaxy position per work (placed once, by accretion),
                      edition decisions, withdrawn works kept as sealed systems,
                      placement conflicts kept side by side until a person resolves them

Each work is also mined into works/<id>.graph.json and works/<id>.ledger.json (mine.py).

Usage
  python3 corpus.py build     corpus.json [--out DIR]
  python3 corpus.py merge     DIR other.corpus.ledger.json     keep both placements on disagreement
  python3 corpus.py conflicts DIR
  python3 corpus.py resolve   DIR <work> <choice>              choice: 0 = current, n = n-th alternative
  python3 corpus.py choose    DIR <work> <edition-path>        record an edition decision
  python3 corpus.py export    DIR out.json                     one JSON bundle for the viewer and terminal

The manifest (corpus.json) lists works, their editions (source files), optional series,
optional provenance text and declared views. See the example beside this file.

Placement by accretion: a new work is placed near the already placed works it most resembles
(TF-IDF over title, abstract, headings and prose), at a distance that grows as the resemblance
weakens, and never on top of another system. Placed works never move again unless a person
resolves a conflict. The galaxy's shape therefore records the order in which it grew.
"""
import datetime, hashlib, json, math, re, sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mine  # noqa: E402

MIN_GAP = 45.0      # no two systems closer than this
NEAR = 70.0         # distance to a near-identical neighbour
FAR = 210.0         # distance to an unrelated neighbour
STOP = set("""a an and are as at be been but by can for from has have if in into is it its of on or
that the their them then there these they this to was were what when which while with without not
no so than too very will would its it's may might also more most such only one two our we you your""".split())

now = lambda: datetime.datetime.now().isoformat(timespec="seconds")
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def tex_field(text, cmd):
    m = re.search(r"\\" + cmd + r"\{((?:[^{}]|\{[^{}]*\})*)\}", text)
    return mine.clean(m.group(1)) if m else None


def tex_abstract(text):
    m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, re.S)
    return re.sub(r"\s+", " ", mine.reading_text(m.group(1).replace("\n", " "))).strip() if m else None


def tokens(s):
    return [w for w in re.findall(r"[a-z][a-z'\-]{2,}", s.lower()) if w not in STOP]


def hash_dir(key):
    """A deterministic unit vector per work, biased toward the galactic plane (y shallow)."""
    h = hashlib.sha256(key.encode()).digest()
    a = int.from_bytes(h[:4], "big") / 2**32 * 2 * math.pi
    e = (int.from_bytes(h[4:8], "big") / 2**32 - 0.5) * 0.6
    return [math.cos(a) * math.cos(e), math.sin(e), math.sin(a) * math.cos(e)]


def vec_add(a, b, s=1.0): return [a[i] + b[i] * s for i in range(3)]
def dist(a, b): return math.dist(a, b)


def cosine(a, b):
    num = sum(v * b.get(k, 0.0) for k, v in a.items())
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


# ---------------- build ----------------
def load_ledger(path):
    if path.exists():
        return json.loads(path.read_text())
    return {"version": 1, "works": {}, "editions": {}, "history": []}


def choose_edition(w, ledger, base):
    """Declared > previously decided > proposed (flagged). Never silent."""
    eds = [str(e) for e in w["editions"]]
    prev = ledger["editions"].get(w["id"])
    if w.get("canonical"):
        return w["canonical"], "declared"
    if len(eds) == 1:
        return eds[0], "only"
    if prev and prev.get("how") == "decided" and prev["chosen"] in eds:
        return prev["chosen"], "decided"
    # proposal: the longest edition, a stand-in for "most complete"; flagged for review
    words = {e: len(re.findall(r"[A-Za-z]{2,}", (base / e).read_text(encoding="utf-8"))) for e in eds}
    return max(eds, key=lambda e: (words[e], e)), "proposed"


def build(manifest_path, out=None):
    mpath = Path(manifest_path)
    base = mpath.parent
    man = json.loads(mpath.read_text())
    out = Path(out or base / "data")
    (out / "works").mkdir(parents=True, exist_ok=True)
    lpath = out / "corpus.ledger.json"
    ledger = load_ledger(lpath)
    stamp = now()
    series = man.get("series", {})
    series_of = {}
    for sid, s in series.items():
        for i, wid in enumerate(s.get("order", [])):
            series_of[wid] = (sid, i)

    records, texts, warnings = {}, {}, []
    for w in man["works"]:
        wid = w["id"]
        chosen, how = choose_edition(w, ledger, base)
        prev = ledger["editions"].get(wid)
        if not prev or prev["chosen"] != chosen or prev["how"] != how:
            ledger["editions"][wid] = {"chosen": chosen, "how": how, "at": stamp,
                                        "alternatives": [e for e in w["editions"] if e != chosen]}
            ledger["history"].append({"at": stamp, "edition": wid, "chosen": chosen, "how": how})
        if how == "proposed":
            warnings.append(f"{wid}: edition proposed, not decided ({chosen}); record a choice with: corpus.py choose")
        src = base / chosen
        text = src.read_text(encoding="utf-8")
        graph, wl = mine.run(src, work=wid, out=out / "works", quiet=True)
        secs = [n for n in graph["nodes"] if n["level"] == "section"]
        threads = Counter(t["kind"] for n in graph["nodes"] for t in n["threads"])
        title = tex_field(text, "title") or (secs[0]["title"] if secs else wid)
        abstract = tex_abstract(text) or next((n["text"][0] for n in graph["nodes"] if n["text"]), "")
        sid = w.get("series") or (series_of.get(wid) or (None,))[0]
        records[wid] = {
            "id": wid, "title": title, "abstract": abstract,
            "series": sid, "series_order": series_of.get(wid, (None, None))[1],
            "provenance": {"source": w.get("source"), "edition": chosen, "edition_how": how,
                           "editions": [{"path": str(e), "sha256": sha(base / e)} for e in w["editions"]]},
            "counts": {"sections": len(secs), "words": sum(n["words"] for n in graph["nodes"]),
                       "threads": dict(threads), "thesis": any(n["thesis"] for n in graph["nodes"])},
            "start": next((n["id"] for n in sorted(secs, key=lambda n: n["order"]) if n["role"] != "appendix"), None),
            "labels": sorted({n["id"][2:] for n in graph["nodes"] if n["id"].startswith("L:")}),
        }
        heads = " ".join(n["title"] for n in graph["nodes"])
        prose = " ".join(p for n in graph["nodes"] for p in n["text"])
        texts[wid] = tokens(f"{title} {title} {title} {abstract} {abstract} {heads} {heads} {prose}")

    # lanes: declared exits (directed, as authored) and series order (two-way)
    lanes, uncharted = [], []
    for wid in records:
        g = json.loads((out / "works" / f"{wid}.graph.json").read_text())
        for e in g["edges"]:
            if e["kind"] != "exit":
                continue
            target = e["to"][len("work:"):]
            tw, _, label = target.partition("#")
            lane = {"from": wid, "from_chamber": e["from"], "to": tw, "to_label": label or None,
                    "kind": "exit", "traversal": e.get("traversal", "two-way")}
            if tw not in records:
                lane["uncharted"] = True
                uncharted.append(f"{wid} -> {tw}")
            elif label and label not in records[tw]["labels"]:
                warnings.append(f"{wid}: exit to {tw}#{label}, but {tw} has no such label; arriving at its start")
                lane["to_label"] = None
            lanes.append(lane)
    for sid, s in series.items():
        order = [x for x in s.get("order", []) if x in records]
        for a, b in zip(order, order[1:]):
            lanes.append({"from": a, "to": b, "kind": "series", "series": sid, "traversal": "two-way"})

    place(records, texts, ledger, stamp)
    live = set(records)
    for wid, p in ledger["works"].items():
        if wid not in live and p["status"] == "active":
            p["status"] = "withdrawn"
            ledger["history"].append({"at": stamp, "withdrawn": wid})
        elif wid in live and p["status"] == "withdrawn":
            p["status"] = "active"
            ledger["history"].append({"at": stamp, "restored": wid})

    views = man.get("views") or [{"id": "galaxy", "title": "Galaxy"}]
    graph = {"corpus": man.get("corpus", slug(base.name)), "title": man.get("title", base.name),
             "series": {k: {"title": v.get("title", k), "order": v.get("order", [])} for k, v in series.items()},
             "works": list(records.values()), "lanes": lanes, "views": views, "built": stamp}
    (out / "corpus.graph.json").write_text(json.dumps(graph, indent=2))
    lpath.write_text(json.dumps(ledger, indent=2))
    conflicts = [w for w, p in ledger["works"].items() if p.get("conflicts")]
    print(f"{graph['corpus']}: {len(records)} works, {len(lanes)} lanes, "
          f"{sum(1 for h in ledger['history'] if h.get('at') == stamp and 'placed' in h)} placed this run")
    for u in uncharted:
        print("  uncharted exit:", u)
    for w in warnings:
        print("  warn:", w)
    for c in conflicts:
        print("  placement conflict:", c, "(corpus.py conflicts)")
    return graph, ledger


def place(records, texts, ledger, stamp):
    """Accretion: new works settle near what they most resemble; placed works never move."""
    df = Counter(t for ws in texts.values() for t in set(ws))
    n = len(texts)
    tfidf = {}
    for wid, ws in texts.items():
        tf = Counter(ws)
        tfidf[wid] = {t: (c / len(ws)) * math.log((1 + n) / (1 + df[t])) + 1e-9 for t, c in tf.items()}
    placed = {w: p for w, p in ledger["works"].items()}
    for wid in records:  # manifest order is accretion order
        if wid in placed:
            continue
        others = [(o, cosine(tfidf[wid], tfidf[o])) for o in placed if o in tfidf]
        others.sort(key=lambda x: -x[1])
        near = others[:3]
        sid = records[wid]["series"]
        if sid:  # a series neighbour counts as strongly related even if the vocabulary differs
            for o in placed:
                if records.get(o, {}).get("series") == sid and o not in [x[0] for x in near]:
                    near.append((o, 0.35))
                    break
        if not near:
            pos = [0.0, 0.0, 0.0]
        else:
            wsum = sum(max(s, 0.05) for _, s in near)
            centre = [sum(placed[o]["pos"][i] * max(s, 0.05) for o, s in near) / wsum for i in range(3)]
            best = max(s for _, s in near)
            radius = NEAR + (FAR - NEAR) * (1 - min(best * 2.5, 1.0))
            d = hash_dir(wid)
            pos = vec_add(centre, d, radius)
            k = 0
            while any(dist(pos, p["pos"]) < MIN_GAP for p in placed.values()) and k < 200:
                k += 1
                ang = k * 2.399963  # golden-angle spiral around the first choice
                pos = vec_add(centre, [d[0] * math.cos(ang) - d[2] * math.sin(ang), d[1],
                                       d[0] * math.sin(ang) + d[2] * math.cos(ang)], radius + 8 * k)
        entry = {"pos": [round(x, 2) for x in pos], "status": "active", "first_seen": stamp,
                 "placed_near": [{"work": o, "similarity": round(s, 3)} for o, s in near], "conflicts": []}
        placed[wid] = ledger["works"][wid] = entry
        ledger["history"].append({"at": stamp, "placed": wid, "pos": entry["pos"]})


# ---------------- replication: keep both, let a person decide ----------------
def merge(out, other_path):
    out = Path(out)
    lpath = out / "corpus.ledger.json"
    ours, theirs = load_ledger(lpath), json.loads(Path(other_path).read_text())
    stamp, added, conflicted = now(), 0, 0
    for wid, p in theirs.get("works", {}).items():
        mine_p = ours["works"].get(wid)
        if not mine_p:
            ours["works"][wid] = dict(p, conflicts=list(p.get("conflicts", [])))
            ours["history"].append({"at": stamp, "merged": wid, "from": str(other_path)})
            added += 1
        elif mine_p["pos"] != p["pos"]:
            alt = {"pos": p["pos"], "first_seen": p.get("first_seen"), "from": str(other_path)}
            if alt["pos"] not in [c["pos"] for c in mine_p.setdefault("conflicts", [])]:
                mine_p["conflicts"].append(alt)
                ours["history"].append({"at": stamp, "conflict": wid, "alternative": alt["pos"]})
                conflicted += 1
    for wid, e in theirs.get("editions", {}).items():
        if wid not in ours["editions"]:
            ours["editions"][wid] = e
    lpath.write_text(json.dumps(ours, indent=2))
    print(f"merged {other_path}: {added} works added, {conflicted} placement conflicts kept for review")


def conflicts(out):
    ledger = load_ledger(Path(out) / "corpus.ledger.json")
    rows = [(w, p) for w, p in ledger["works"].items() if p.get("conflicts")]
    if not rows:
        print("no placement conflicts")
    for w, p in rows:
        print(f"{w}\n  [0] current {p['pos']} (first seen {p.get('first_seen')})")
        for i, c in enumerate(p["conflicts"], 1):
            print(f"  [{i}] {c['pos']} from {c.get('from')} (first seen {c.get('first_seen')})")


def resolve(out, wid, choice):
    lpath = Path(out) / "corpus.ledger.json"
    ledger = load_ledger(lpath)
    p = ledger["works"][wid]
    choice = int(choice)
    if choice:
        alt = p["conflicts"][choice - 1]
        p["conflicts"][choice - 1] = {"pos": p["pos"], "first_seen": p.get("first_seen"), "from": "previous current"}
        p["pos"] = alt["pos"]
    ledger["history"].append({"at": now(), "resolved": wid, "pos": p["pos"], "kept_alternatives": p["conflicts"]})
    p["resolved"] = {"at": now(), "alternatives": p["conflicts"]}
    p["conflicts"] = []
    lpath.write_text(json.dumps(ledger, indent=2))
    print(f"{wid}: placement fixed at {p['pos']}; alternatives kept in history")


def choose(out, wid, edition):
    lpath = Path(out) / "corpus.ledger.json"
    ledger = load_ledger(lpath)
    e = ledger["editions"].get(wid, {})
    ledger["editions"][wid] = {"chosen": edition, "how": "decided", "at": now(),
                               "alternatives": [x for x in [e.get("chosen")] + e.get("alternatives", []) if x and x != edition]}
    ledger["history"].append({"at": now(), "edition": wid, "chosen": edition, "how": "decided"})
    lpath.write_text(json.dumps(ledger, indent=2))
    print(f"{wid}: edition {edition} recorded as decided; rebuild to apply")


def export(out, dest):
    """One bundle for the viewer and the terminal: corpus graph + ledger, and every work's graph + ledger."""
    out = Path(out)
    g = json.loads((out / "corpus.graph.json").read_text())
    bundle = {"corpus": {"graph": g, "ledger": json.loads((out / "corpus.ledger.json").read_text())}, "works": {}}
    for w in g["works"]:
        bundle["works"][w["id"]] = {"graph": json.loads((out / "works" / f"{w['id']}.graph.json").read_text()),
                                    "ledger": json.loads((out / "works" / f"{w['id']}.ledger.json").read_text())}
    Path(dest).write_text(json.dumps(bundle, separators=(",", ":")))
    print(dest, Path(dest).stat().st_size, "bytes")


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "build" and len(a) >= 2:
        build(a[1], a[a.index("--out") + 1] if "--out" in a else None)
    elif cmd == "merge" and len(a) == 3:
        merge(a[1], a[2])
    elif cmd == "conflicts" and len(a) == 2:
        conflicts(a[1])
    elif cmd == "resolve" and len(a) == 4:
        resolve(a[1], a[2], a[3])
    elif cmd == "choose" and len(a) == 4:
        choose(a[1], a[2], a[3])
    elif cmd == "export" and len(a) == 3:
        export(a[1], a[2])
    else:
        sys.exit(__doc__)
