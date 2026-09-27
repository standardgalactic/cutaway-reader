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
  python3 corpus.py resolve   DIR <work> <choice>              0 keeps this galaxy's placement, n takes alternative n
  python3 corpus.py adopt     DIR <galaxy-id>                  take that galaxy's placements wherever it disagrees
  python3 corpus.py choose    DIR <work> <edition-path>        record an edition decision
  python3 corpus.py export    DIR out.json                     one JSON bundle for the viewer and terminal
  python3 corpus.py report    DIR [--json]                     what needs a person, most urgent first (DIR/report.md)
  python3 corpus.py links     corpus.json                      declared lanes and suggestions, numbered
  python3 corpus.py link      corpus.json FROM[@CHAMBER] TO[#LABEL] [--oneway] [--note TEXT]
  python3 corpus.py link      corpus.json --suggestion N       declare a suggested lane
  python3 corpus.py unlink    corpus.json N
  python3 corpus.py series    corpus.json ID "Title" WORK...   set a series' reading order (or ID --remove)
  python3 corpus.py add       corpus.json PATH... [--as WORK] [--new] [--dry-run]
                              bring in .tex files, folders or zips as editions (see ingest.py)

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
sha = lambda p: mine.source_sha256(p)


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
def new_galaxy_id():
    import uuid
    return "g-" + uuid.uuid4().hex[:12]


def load_ledger(path):
    """A galaxy ledger. Its galaxy_id is minted once and never changes; merges refer to galaxies by it."""
    if path.exists():
        led = json.loads(path.read_text())
        if "galaxy_id" not in led:  # ledgers written before galaxies had identity
            led["galaxy_id"] = "g-" + hashlib.sha256(json.dumps(led.get("works", {}), sort_keys=True).encode()).hexdigest()[:12]
        return led
    return {"version": 2, "galaxy_id": new_galaxy_id(), "works": {}, "editions": {}, "history": []}


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
    words = {e: len(re.findall(r"[A-Za-z]{2,}", mine.load_source(base / e)[0])) for e in eds}
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

    records, texts, warnings, mined, reused = {}, {}, [], [], []
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
        text = mine.load_source(src)[0]
        if mine.is_current(src, wid, out / "works"):
            graph = json.loads((out / "works" / f"{wid}.graph.json").read_text())
            reused.append(wid)
        else:
            graph, _ = mine.run(src, work=wid, out=out / "works", quiet=True)
            mined.append(wid)
        secs = [n for n in graph["nodes"] if n["level"] == "section"]
        threads = Counter(t["kind"] for n in graph["nodes"] for t in n["threads"])
        title = w.get("title") or graph.get("title") or (secs[0]["title"] if secs else wid)
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
            "warnings": graph.get("warnings", []),
            "open_threads": [{"chamber": n["id"], "chamber_title": n["title"], "kind": t["kind"], "text": t["text"]}
                             for n in graph["nodes"] if n.get("status", "active") == "active" for t in n["threads"]],
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
    lanes += manifest_lanes(man, records, out, warnings, uncharted)
    lanes = coalesce_reciprocal(lanes, records, warnings)
    lanes += cited_works(records, out, warnings)
    suggestions = named_works(records, out, lanes)
    for sid, s in series.items():
        order = [x for x in s.get("order", []) if x in records]
        for a, b in zip(order, order[1:]):
            lanes.append({"from": a, "to": b, "kind": "series", "series": sid, "traversal": "two-way"})

    annotate_lanes(lanes, records, out)
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
             "works": list(records.values()), "lanes": lanes, "views": views, "built": stamp,
             "suggestions": suggestions}
    (out / "corpus.graph.json").write_text(json.dumps(graph, indent=2))
    lpath.write_text(json.dumps(ledger, indent=2))
    conflicts = [w for w, p in ledger["works"].items() if p.get("conflicts")]
    print(f"{graph['corpus']}: {len(records)} works, {len(lanes)} lanes, "
          f"{sum(1 for h in ledger['history'] if h.get('at') == stamp and 'placed' in h)} placed this run; "
          f"mined {len(mined)}, unchanged {len(reused)}")
    for w, r in records.items():
        for x in r["warnings"]:
            if x["severity"] == "problem":
                print(f"  problem: {w}: {x['text']}")
    advice = sum(x["severity"] == "advice" for r in records.values() for x in r["warnings"])
    if advice:
        print(f"  {advice} pieces of advice on the sources (corpus.py report)")
    for u in uncharted:
        print("  uncharted exit:", u)
    for w in warnings:
        print("  warn:", w)
    for c in conflicts:
        print("  placement conflict:", c, "(corpus.py conflicts)")
    for x in suggestions:
        print(f"  names: {x['from']} (\u00a7 {x['chamber_title']}) names {x['to']} {x['count']}x; "
              f"a lane only if the author declares one: % mine: exit={x['to']}")
    return graph, ledger


def main_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower().split(":")[0]).strip()


def cited_works(records, out, warnings):
    """Inferred lanes: a chamber that cites one of the author's own works (a bibliography entry beginning
    with the author's name, as \bibitem{..} Flyxion. (2026). \emph{Title}) opens toward that work.
    Kept distinct from declared exits: kind 'cites-work', inferred. A cited work that is not in the corpus
    becomes an uncharted lane that names it, so the gaps in the corpus are visible."""
    by_title = {main_title(r["title"]): wid for wid, r in records.items()}
    lanes, missing = [], {}
    for wid in records:
        g = json.loads((out / "works" / f"{wid}.graph.json").read_text())
        bib, seen = g.get("bibliography") or {}, set()
        for n in g["nodes"]:
            for key in n.get("cites", []):
                b = bib.get(key)
                if not b or not b.get("flyxion") or not b.get("title"):
                    continue
                target = by_title.get(main_title(b["title"]))
                if target == wid:
                    continue
                to = target or "title:" + slug(b["title"])
                if (n["id"], to) in seen:
                    continue
                seen.add((n["id"], to))
                lane = {"from": wid, "from_chamber": n["id"], "to": to, "to_label": None, "kind": "cites-work",
                        "inferred": True, "traversal": "two-way", "to_title": b["title"], "via": key}
                if not target:
                    lane["uncharted"] = True
                    missing.setdefault(b["title"], set()).add(wid)
                lanes.append(lane)
    for t, ws in sorted(missing.items()):
        warnings.append(f"cited but not in the corpus: {t} (cited by {', '.join(sorted(ws))})")
    return lanes


def resolve_chamber(out, wid, ref):
    """A chamber named in the manifest: its id (G:..., L:...), a label, or its heading. None if absent."""
    p = Path(out) / "works" / f"{wid}.graph.json"
    if not ref or not p.exists():
        return None
    nodes = json.loads(p.read_text())["nodes"]
    for n in nodes:
        if n["id"] in (ref, "L:" + ref) or n["title"].strip().lower() == ref.strip().lower():
            return n["id"]
    return None


def annotate_lanes(lanes, records, out):
    """What a reader needs about a lane's two ends without loading either work: the heading it opens from
    and the chamber it lands in. The viewer loads works on demand, so the corpus index must carry these."""
    graphs = {}
    def nodes(wid):
        if wid not in graphs:
            p = Path(out) / "works" / f"{wid}.graph.json"
            graphs[wid] = {n["id"]: n for n in json.loads(p.read_text())["nodes"]} if p.exists() else {}
        return graphs[wid]
    for l in lanes:
        n = nodes(l["from"]).get(l.get("from_chamber"))
        if n:
            l["from_chamber_title"] = n["title"]
        if l.get("uncharted") or l["to"] not in records:
            continue
        target = nodes(l["to"]).get("L:" + l["to_label"]) if l.get("to_label") else None
        l["to_chamber"] = target["id"] if target and target.get("status", "active") == "active" else records[l["to"]]["start"]


def manifest_lanes(man, records, out, warnings, uncharted):
    """Lanes the author declares in corpus.json rather than in the sources: the same standing as an
    exit= line (declared, directed as written, physically two-way unless oneway), recorded in one place
    so that linking works needs no edit to a paper."""
    lanes = []
    for i, d in enumerate(man.get("lanes", [])):
        wid, to = d["from"], d["to"]
        if wid not in records:
            warnings.append(f"manifest lane {i + 1}: from {wid}, which is not in the corpus; ignored")
            continue
        chamber = resolve_chamber(out, wid, d.get("from_chamber")) if d.get("from_chamber") else None
        if d.get("from_chamber") and not chamber:
            warnings.append(f"manifest lane {i + 1}: {wid} has no chamber '{d['from_chamber']}'; leaving from its start")
        lane = {"from": wid, "from_chamber": chamber or records[wid]["start"], "to": to, "to_label": d.get("to_label"),
                "kind": "exit", "traversal": "one-way" if d.get("oneway") else "two-way", "declared_in": "manifest"}
        if d.get("note"):
            lane["note"] = d["note"]
        if to not in records:
            lane["uncharted"] = True
            uncharted.append(f"{wid} -> {to}")
        elif lane["to_label"] and lane["to_label"] not in records[to]["labels"]:
            warnings.append(f"manifest lane {i + 1}: {to} has no label {lane['to_label']}; arriving at its start")
            lane["to_label"] = None
        lanes.append(lane)
    return lanes


# ---------------- authoring the manifest: lanes and series ----------------
def _manifest(path):
    p = Path(path)
    return p, json.loads(p.read_text())


def _save(p, man):
    p.write_text(json.dumps(man, indent=2) + "\n")


def _data_dir(p):
    return p.parent / "data"


def links(path):
    """Declared manifest lanes and the current suggestions, numbered for link/unlink."""
    p, man = _manifest(path)
    print("declared in the manifest:")
    for i, d in enumerate(man.get("lanes", []), 1):
        where = f" (§ {d['from_chamber']})" if d.get("from_chamber") else ""
        print(f"  {i}. {d['from']}{where} -> {d['to']}{'#' + d['to_label'] if d.get('to_label') else ''}"
              f"{' one-way' if d.get('oneway') else ''}{'  ' + d['note'] if d.get('note') else ''}")
    if not man.get("lanes"):
        print("  (none)")
    g = _data_dir(p) / "corpus.graph.json"
    sug = json.loads(g.read_text()).get("suggestions", []) if g.exists() else []
    print("suggestions from the last build (a chamber names another work; promote with: link --suggestion N):")
    for i, x in enumerate(sug, 1):
        print(f"  {i}. {x['from']} (§ {x['chamber_title']}) names {x['to']} {x['count']}x")
    if not sug:
        print("  (none)")


def link(path, args):
    """link corpus.json FROM[@CHAMBER] TO[#LABEL] [--oneway] [--note TEXT]   or   link corpus.json --suggestion N"""
    p, man = _manifest(path)
    ids = {w["id"] for w in man["works"]}
    note = args[args.index("--note") + 1] if "--note" in args else None
    if "--suggestion" in args:
        n = int(args[args.index("--suggestion") + 1])
        sug = json.loads((_data_dir(p) / "corpus.graph.json").read_text()).get("suggestions", [])
        if not 1 <= n <= len(sug):
            sys.exit(f"no suggestion {n}; run: corpus.py links {path}")
        x = sug[n - 1]
        d = {"from": x["from"], "from_chamber": x["chamber_title"], "to": x["to"]}
    else:
        pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--note")]
        if len(pos) != 2:
            sys.exit(link.__doc__)
        frm, to = pos
        wid, _, chamber = frm.partition("@")
        tw, _, label = to.partition("#")
        if wid not in ids:
            sys.exit(f"no work {wid} in {path}")
        d = {"from": wid, "to": tw}
        if chamber:
            d["from_chamber"] = chamber
        if label:
            d["to_label"] = label
        if tw not in ids:
            print(f"  note: {tw} is not in the corpus yet; the lane will show as uncharted until it is")
    if "--oneway" in args:
        d["oneway"] = True
    if note:
        d["note"] = note
    if d.get("from_chamber") and (_data_dir(p) / "works" / f"{d['from']}.graph.json").exists() \
            and not resolve_chamber(_data_dir(p), d["from"], d["from_chamber"]):
        sys.exit(f"{d['from']} has no chamber '{d['from_chamber']}' (use its heading, label or id)")
    lanes = man.setdefault("lanes", [])
    key = lambda x: (x["from"], x.get("from_chamber"), x["to"], x.get("to_label"))
    if any(key(x) == key(d) for x in lanes):
        print("  already declared")
        return
    lanes.append(d)
    _save(p, man)
    print(f"  declared: {d['from']}{' (§ ' + d['from_chamber'] + ')' if d.get('from_chamber') else ''} -> {d['to']}"
          f"  (takes effect at the next build)")


def unlink(path, n):
    p, man = _manifest(path)
    lanes = man.get("lanes", [])
    n = int(n)
    if not 1 <= n <= len(lanes):
        sys.exit(f"no declared lane {n}")
    d = lanes.pop(n - 1)
    _save(p, man)
    print(f"  removed: {d['from']} -> {d['to']}")


def series_cmd(path, args):
    """series corpus.json ID "Title" WORK...   (replaces that series' order)   |   series corpus.json ID --remove"""
    p, man = _manifest(path)
    ids = {w["id"] for w in man["works"]}
    if len(args) == 2 and args[1] == "--remove":
        man.get("series", {}).pop(args[0], None)
        for w in man["works"]:
            if w.get("series") == args[0]:
                del w["series"]
        _save(p, man)
        print(f"  series {args[0]} removed")
        return
    if len(args) < 3:
        sys.exit(series_cmd.__doc__)
    sid, title, order = args[0], args[1], args[2:]
    unknown = [w for w in order if w not in ids]
    if unknown:
        sys.exit(f"not in the corpus: {', '.join(unknown)}")
    elsewhere = {w: s for s, v in man.get("series", {}).items() if s != sid for w in v.get("order", []) if w in order}
    if elsewhere:
        sys.exit("a work belongs to one series; already in another: " + ", ".join(f"{w} ({s})" for w, s in elsewhere.items()))
    man.setdefault("series", {})[sid] = {"title": title, "order": order}
    for w in man["works"]:
        if w["id"] in order:
            w["series"] = sid
        elif w.get("series") == sid:
            del w["series"]
    _save(p, man)
    print(f"  series {sid} ({title}): {' -> '.join(order)}  (takes effect at the next build)")


def named_works(records, out, lanes):
    """Suggestions, never lanes: a chamber whose prose names another corpus work by its main title.
    Naming is weaker evidence than citing, so nothing is drawn; the author decides with an exit= line.
    Pairs already joined by a lane are not suggested again."""
    joined = {(l["from"], l["to"]) for l in lanes} | {(l["to"], l["from"]) for l in lanes}
    names = {wid: (r["title"] or "").split(":")[0].strip() for wid, r in records.items()}
    found = {}
    for wid in records:
        g = json.loads((out / "works" / f"{wid}.graph.json").read_text())
        for n in g["nodes"]:
            prose = " ".join(n["text"])
            for other, name in names.items():
                if other == wid or len(name) < 6 or (wid, other) in joined:
                    continue
                if names[wid].lower().startswith(name.lower()):
                    continue  # "Spherepop OS" naming Spherepop is its own title, not a reference
                k = len(re.findall(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", prose))
                if k:
                    best = found.get((wid, other))
                    if not best or k > best["count"]:
                        found[(wid, other)] = {"from": wid, "chamber": n["id"], "chamber_title": n["title"],
                                               "to": other, "count": k}
    return sorted(found.values(), key=lambda x: (x["from"], -x["count"]))


def coalesce_reciprocal(lanes, records, warnings):
    """Two two-way exits declared from each end are one relationship when each lands where the other opens.
    Then they become one lane, marked as declared from both ends. If they open from different sections they are
    different passages between the same works: both are kept, and the build says so."""
    land = lambda l: ("L:" + l["to_label"]) if l.get("to_label") else records[l["to"]]["start"]
    out, dropped = [], set()
    exits = [l for l in lanes if l["kind"] == "exit" and not l.get("uncharted") and l["traversal"] == "two-way"]
    for i, a in enumerate(exits):
        if id(a) in dropped:
            continue
        for b in exits[i + 1:]:
            if id(b) in dropped or not (a["from"] == b["to"] and a["to"] == b["from"]):
                continue
            if a["from_chamber"] == land(b) and b["from_chamber"] == land(a):
                a["declared"] = "both ends"
                dropped.add(id(b))
            else:
                warnings.append(f"parallel lanes between {a['from']} and {a['to']}: declared from different sections "
                                f"({a['from_chamber']} and {b['from_chamber']}), kept as two passages")
    for l in lanes:
        if id(l) not in dropped:
            out.append(l)
    return out


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
            # the closest resemblance sets the distance; the others only lean the direction
            anchor, best = near[0]
            a = placed[anchor]["pos"]
            radius = NEAR + (FAR - NEAR) * (1 - min(best * 2.5, 1.0))
            d = hash_dir(wid)
            rest = [(o, s) for o, s in near[1:] if dist(placed[o]["pos"], a) > 1e-6]
            if rest:
                wsum = sum(max(s, 0.05) for _, s in rest)
                toward = [sum((placed[o]["pos"][i] - a[i]) * max(s, 0.05) for o, s in rest) / wsum for i in range(3)]
                norm = math.sqrt(sum(x * x for x in toward)) or 1.0
                lean = [0.6 * toward[i] / norm + 0.4 * d[i] for i in range(3)]
                ln = math.sqrt(sum(x * x for x in lean)) or 1.0
                d = [x / ln for x in lean]
            pos = vec_add(a, d, radius)
            # every resemblance asks for its own distance (closer when more alike); settle where those
            # requests are best met together, starting from the anchor-led guess (deterministic)
            want = [(placed[o]["pos"], NEAR + (FAR - NEAR) * (1 - min(s * 2.5, 1.0)), max(s, 0.05)) for o, s in near]
            for _ in range(300):
                g = [0.0, 0.0, 0.0]
                for q, r, w in want:
                    dq = dist(pos, q) or 1e-6
                    for i in range(3):
                        g[i] += w * (dq - r) * (pos[i] - q[i]) / dq
                wt = sum(w for _, _, w in want)
                pos = [pos[i] - 0.5 * g[i] / wt for i in range(3)]
            k, settled = 0, pos
            while any(dist(pos, p["pos"]) < MIN_GAP for p in placed.values()) and k < 200:
                k += 1
                ang = k * 2.399963  # golden-angle spiral around the anchor
                pos = [settled[i] + 6 * k ** 0.5 * v for i, v in enumerate(
                    [math.cos(ang), 0.25 * math.sin(3 * ang), math.sin(ang)])]
        entry = {"pos": [round(x, 2) for x in pos], "status": "active", "first_seen": stamp,
                 "placed_near": [{"work": o, "similarity": round(s, 3)} for o, s in near], "conflicts": []}
        placed[wid] = ledger["works"][wid] = entry
        ledger["history"].append({"at": stamp, "placed": wid, "pos": entry["pos"]})


# ---------------- replication: keep both, let a person decide ----------------
def merge(out, other_path):
    out = Path(out)
    lpath = out / "corpus.ledger.json"
    ours, raw = load_ledger(lpath), Path(other_path).read_bytes()
    theirs = json.loads(raw)
    gid = theirs.get("galaxy_id") or "g-" + hashlib.sha256(json.dumps(theirs.get("works", {}), sort_keys=True).encode()).hexdigest()[:12]
    if gid == ours["galaxy_id"]:
        sys.exit(f"{other_path} is this same galaxy ({gid}); nothing to merge")
    origin = {"galaxy": gid, "ledger_sha256": hashlib.sha256(raw).hexdigest()}
    stamp, added, conflicted = now(), 0, 0
    for wid, p in theirs.get("works", {}).items():
        mine_p = ours["works"].get(wid)
        if not mine_p:
            ours["works"][wid] = dict(p, conflicts=list(p.get("conflicts", [])), origin=origin)
            ours["history"].append(dict({"at": stamp, "merged": wid}, **origin))
            added += 1
        elif mine_p["pos"] != p["pos"]:
            alt = dict({"pos": p["pos"], "first_seen": p.get("first_seen")}, **origin)
            if not any(c.get("galaxy") == gid for c in mine_p.setdefault("conflicts", [])):
                mine_p["conflicts"].append(alt)
                ours["history"].append({"at": stamp, "conflict": wid, "alternative": alt["pos"]})
                conflicted += 1
    for wid, e in theirs.get("editions", {}).items():
        if wid not in ours["editions"]:
            ours["editions"][wid] = e
    ours.setdefault("merged_galaxies", {})[gid] = dict(origin, at=stamp)
    lpath.write_text(json.dumps(ours, indent=2))
    print(f"merged galaxy {gid}: {added} works added, {conflicted} placement conflicts kept for review")


def conflicts(out):
    ledger = load_ledger(Path(out) / "corpus.ledger.json")
    rows = [(w, p) for w, p in ledger["works"].items() if p.get("conflicts")]
    if not rows:
        print("no placement conflicts")
    for w, p in rows:
        print(f"{w}\n  [0] current {p['pos']} in this galaxy {ledger['galaxy_id']}")
        for i, c in enumerate(p["conflicts"], 1):
            print(f"  [{i}] {c['pos']} in galaxy {c.get('galaxy')} (first seen {c.get('first_seen')})")
    if rows:
        print("\nresolve one work:      corpus.py resolve DIR <work> <n>")
        print("adopt a whole galaxy:  corpus.py adopt DIR <galaxy-id>")


def _apply(ledger, picks, how):
    """picks: {work: alternative index (1-based)}. Checks the whole resulting galaxy before writing anything."""
    final = {w: p["pos"] for w, p in ledger["works"].items() if p["status"] == "active"}
    for w, i in picks.items():
        final[w] = ledger["works"][w]["conflicts"][i - 1]["pos"]
    clash = [(a, b) for a in final for b in final if a < b and dist(final[a], final[b]) < MIN_GAP]
    if clash:
        a, b = clash[0]
        sys.exit(f"refused: {a} and {b} would be {dist(final[a], final[b]):.1f} apart (minimum {MIN_GAP:.0f}). "
                 f"Adopt their galaxy as a whole, or choose differently. Nothing was changed.")
    stamp = now()
    for w, i in picks.items():
        p = ledger["works"][w]
        alt = p["conflicts"].pop(i - 1)
        p["conflicts"].append({"pos": p["pos"], "first_seen": p.get("first_seen"), "galaxy": ledger["galaxy_id"], "replaced": True})
        p["pos"] = alt["pos"]
        p["resolved"] = {"at": stamp, "how": how, "from_galaxy": alt.get("galaxy"), "alternatives": p["conflicts"]}
        p["conflicts"] = []
        ledger["history"].append({"at": stamp, "resolved": w, "how": how, "pos": p["pos"], "from_galaxy": alt.get("galaxy")})
    return stamp


def resolve(out, wid, choice):
    """Settle one work: 0 keeps this galaxy's placement, n takes the n-th alternative (as listed by conflicts)."""
    lpath = Path(out) / "corpus.ledger.json"
    ledger = load_ledger(lpath)
    p, choice = ledger["works"].get(wid), int(choice)
    if not p or not p.get("conflicts"):
        sys.exit(f"{wid} has no placement conflict")
    if choice > len(p["conflicts"]):
        sys.exit(f"{wid} has no alternative {choice}")
    if choice == 0:
        stamp = now()
        p["resolved"] = {"at": stamp, "how": "kept", "alternatives": p["conflicts"]}
        ledger["history"].append({"at": stamp, "resolved": wid, "how": "kept", "pos": p["pos"]})
        p["conflicts"] = []
    else:
        _apply(ledger, {wid: choice}, "chosen")
    lpath.write_text(json.dumps(ledger, indent=2))
    print(f"{wid}: placement fixed at {p['pos']}; alternatives kept in its record")


def adopt(out, galaxy):
    """Take another galaxy's placements for every work where it disagrees with this one.
    Selected by galaxy identity, never by the order alternatives happen to be listed in, so it stays
    correct after several merges. Works that galaxy never placed, or placed the same, are untouched."""
    lpath = Path(out) / "corpus.ledger.json"
    ledger = load_ledger(lpath)
    picks = {}
    for w, p in ledger["works"].items():
        for i, c in enumerate(p.get("conflicts", []), 1):
            if c.get("galaxy") == galaxy:
                picks[w] = i
    if not picks:
        sys.exit(f"no conflicts come from galaxy {galaxy}; see corpus.py conflicts")
    _apply(ledger, picks, "adopted " + galaxy)
    lpath.write_text(json.dumps(ledger, indent=2))
    print(f"adopted galaxy {galaxy} for {len(picks)} works: " + ", ".join(sorted(picks)))


def choose(out, wid, edition):
    lpath = Path(out) / "corpus.ledger.json"
    ledger = load_ledger(lpath)
    e = ledger["editions"].get(wid, {})
    ledger["editions"][wid] = {"chosen": edition, "how": "decided", "at": now(),
                               "alternatives": [x for x in [e.get("chosen")] + e.get("alternatives", []) if x and x != edition]}
    ledger["history"].append({"at": now(), "edition": wid, "chosen": edition, "how": "decided"})
    lpath.write_text(json.dumps(ledger, indent=2))
    print(f"{wid}: edition {edition} recorded as decided; rebuild to apply")


def edition_summary(path):
    """Headings and length of one edition, without touching any ledger."""
    units = mine.parse(mine.load_source(path)[0])
    secs = [u["title"] for u in units if u["level"] == "section"]
    return {"words": sum(u["words"] for u in units), "sections": secs}


def report(out, as_json=False):
    """What in this corpus needs a person, most urgent first; written to DIR/report.md (and report.json)."""
    out = Path(out)
    g = json.loads((out / "corpus.graph.json").read_text())
    ledger = json.loads((out / "corpus.ledger.json").read_text())
    base = None
    for cand in (out.parent / "corpus.json", out / "corpus.json"):
        if cand.exists():
            base = cand.parent
    works = {w["id"]: w for w in g["works"]}
    lines, data = [f"# {g['title']}: corpus report", "", f"Built {g['built']}. {len(works)} works, "
                   f"{sum(w['counts']['words'] for w in works.values()):,} words, "
                   f"{sum(1 for l in g['lanes'] if not l.get('uncharted'))} lanes.", ""], {}

    # 1. decisions
    lines += ["## Waiting for a decision", ""]
    undecided = []
    for wid, w in works.items():
        pv = w["provenance"]
        if pv["edition_how"] != "proposed":
            continue
        eds = []
        for e in pv["editions"]:
            summ = edition_summary(base / e["path"]) if base else {"words": None, "sections": []}
            eds.append({"path": e["path"], "hash": e["sha256"][:10], **summ, "proposed": e["path"] == pv["edition"]})
        chosen = next(e for e in eds if e["proposed"])
        for e in eds:
            e["only_here"] = [t for t in e["sections"] if t not in chosen["sections"]] if not e["proposed"] else []
            e["missing_here"] = [t for t in chosen["sections"] if t not in e["sections"]] if not e["proposed"] else []
        undecided.append({"work": wid, "editions": eds})
        lines.append(f"**{w['title']}** (`{wid}`): {len(eds)} editions, the longest proposed. Record a choice with "
                     f"`corpus.py choose {out} {wid} <path>`.")
        lines.append("")
        lines.append("| edition | words | chambers | differs from the proposed one |")
        lines.append("|---|---:|---:|---|")
        for e in sorted(eds, key=lambda e: -(e["words"] or 0)):
            diff = "proposed" if e["proposed"] else "; ".join(x for x in [
                ("adds " + ", ".join(e["only_here"][:4]) + (" …" if len(e["only_here"]) > 4 else "")) if e["only_here"] else "",
                ("lacks " + ", ".join(e["missing_here"][:4]) + (" …" if len(e["missing_here"]) > 4 else "")) if e["missing_here"] else ""]
                if x) or "same chambers"
            lines.append(f"| `{e['path']}` | {e['words']:,} | {len(e['sections'])} | {diff} |")
        lines.append("")
    conflicts = {w: p["conflicts"] for w, p in ledger["works"].items() if p.get("conflicts")}
    for w, c in conflicts.items():
        lines.append(f"**Placement conflict** for `{w}`: {len(c)} other placement(s). See `corpus.py conflicts {out}`.")
    if not undecided and not conflicts:
        lines.append("Nothing.")
    lines.append("")
    data["undecided_editions"], data["placement_conflicts"] = undecided, conflicts

    # 2. connectivity
    adj = {w: set() for w in works}
    for l in g["lanes"]:
        if not l.get("uncharted") and l["to"] in adj and l["from"] in adj:
            adj[l["from"]].add(l["to"]); adj[l["to"]].add(l["from"])
    comps, seen = [], set()
    for w in works:
        if w in seen:
            continue
        stack, comp = [w], []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x); comp.append(x); stack += adj[x]
        comps.append(sorted(comp))
    comps.sort(key=lambda c: (-len(c), c))
    islands = [c[0] for c in comps if len(c) == 1]
    lines += ["## How the corpus connects", "",
              f"{len(comps)} separate groups; the largest holds {len(comps[0])} of {len(works)} works." if comps else "", ""]
    for c in comps:
        if len(c) > 1:
            lines.append(f"- joined: {', '.join(c)}")
    if islands:
        lines.append(f"- islands (no lane in or out): {', '.join(islands)}")
    lines.append("")
    sug = g.get("suggestions", [])
    if sug:
        lines += ["Suggested lanes (a chamber names another work; nothing is drawn until declared):", ""]
        for i, x in enumerate(sug, 1):
            lines.append(f"{i}. `{x['from']}` § {x['chamber_title']} names `{x['to']}` {x['count']}× "
                         f"→ `corpus.py link <corpus.json> --suggestion {i}`")
        lines.append("")
    missing = {}
    for l in g["lanes"]:
        if l.get("uncharted"):
            missing.setdefault(l.get("to_title") or l["to"], set()).add(l["from"])
    if missing:
        lines += [f"Works cited or linked but not in the corpus ({len(missing)}):", ""]
        for t, ws in sorted(missing.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            lines.append(f"- {t} (from {', '.join(sorted(ws))})")
        lines.append("")
    data["groups"], data["islands"], data["suggestions"] = comps, islands, sug
    data["missing_works"] = {t: sorted(ws) for t, ws in missing.items()}

    # 3. problems, 4. advice
    probs = {w: [x for x in r["warnings"] if x["severity"] == "problem"] for w, r in works.items()}
    probs = {w: v for w, v in probs.items() if v}
    lines += ["## Problems in the sources", ""]
    for w, v in probs.items():
        for x in v:
            lines.append(f"- `{w}`: {x['text']}")
    if not probs:
        lines.append("None: every source was read in full.")
    lines += ["", "## Advice", ""]
    kinds = Counter(x["kind"] for r in works.values() for x in r["warnings"] if x["severity"] == "advice")
    words = {"unlabeled": "have chambers without a \\label (renaming such a heading digs a new chamber)",
             "no-thesis": "mark no thesis chamber", "large-part": "have a part with more than 20 chambers"}
    for k, n in kinds.most_common():
        lines.append(f"- {n} works {words.get(k, k)}")
    if not kinds:
        lines.append("None.")
    data["problems"] = probs

    # 5. inventory
    lines += ["", "## Inventory", "", "| work | words | chambers | editions | series | lanes |", "|---|---:|---:|---:|---|---:|"]
    for wid, w in sorted(works.items(), key=lambda kv: -kv[1]["counts"]["words"]):
        n = sum(1 for l in g["lanes"] if wid in (l["from"], l["to"]) and not l.get("uncharted"))
        lines.append(f"| {w['title']} | {w['counts']['words']:,} | {w['counts']['sections']} | "
                     f"{len(w['provenance']['editions'])} | {w.get('series') or ''} | {n} |")
    text = "\n".join(lines) + "\n"
    (out / "report.md").write_text(text)
    (out / "report.json").write_text(json.dumps(data, indent=2))
    print(json.dumps(data, indent=2) if as_json else text)


def export(out, dest):
    """For the viewer and the terminal. dest ending in .json: one bundle holding everything (small corpora).
    Otherwise a folder: index.json (corpus graph + ledger, every work's record, no work bodies) and
    works/<id>.json, fetched when a reader first goes there. The split form is what scales to hundreds of works."""
    out = Path(out)
    g = json.loads((out / "corpus.graph.json").read_text())
    if not str(dest).endswith(".json"):
        d = Path(dest)
        (d / "works").mkdir(parents=True, exist_ok=True)
        index = {"corpus": {"graph": g, "ledger": json.loads((out / "corpus.ledger.json").read_text())}, "works": {}, "split": "works/"}
        (d / "index.json").write_text(json.dumps(index, separators=(",", ":")))
        keep = set()
        for w in g["works"]:
            body = {"graph": json.loads((out / "works" / f"{w['id']}.graph.json").read_text()),
                    "ledger": json.loads((out / "works" / f"{w['id']}.ledger.json").read_text())}
            (d / "works" / f"{w['id']}.json").write_text(json.dumps(body, separators=(",", ":")))
            keep.add(f"{w['id']}.json")
        for stale in (d / "works").glob("*.json"):
            if stale.name not in keep:
                stale.unlink()
        sizes = sorted(((d / "works" / k).stat().st_size, k) for k in keep)
        print(f"{d}: index {(d / 'index.json').stat().st_size:,} bytes; {len(keep)} works, "
              f"largest {sizes[-1][1]} {sizes[-1][0]:,} bytes, total {sum(x for x, _ in sizes):,}")
        return
    bundle = {"corpus": {"graph": g, "ledger": json.loads((out / "corpus.ledger.json").read_text())}, "works": {}}
    for w in g["works"]:
        bundle["works"][w["id"]] = {"graph": json.loads((out / "works" / f"{w['id']}.graph.json").read_text()),
                                    "ledger": json.loads((out / "works" / f"{w['id']}.ledger.json").read_text())}
    Path(dest).write_text(json.dumps(bundle, separators=(",", ":")))
    print(dest, Path(dest).stat().st_size, "bytes")


if __name__ == "__main__":
    import signal
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # piped into head: stop quietly, as the terminal client does
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
    elif cmd == "adopt" and len(a) == 3:
        adopt(a[1], a[2])
    elif cmd == "choose" and len(a) == 4:
        choose(a[1], a[2], a[3])
    elif cmd == "export" and len(a) == 3:
        export(a[1], a[2])
    elif cmd == "report" and len(a) >= 2:
        report(a[1], "--json" in a)
    elif cmd == "links" and len(a) == 2:
        links(a[1])
    elif cmd == "link" and len(a) >= 3:
        link(a[1], a[2:])
    elif cmd == "unlink" and len(a) == 3:
        unlink(a[1], a[2])
    elif cmd == "series" and len(a) >= 3:
        series_cmd(a[1], a[2:])
    elif cmd == "add" and len(a) >= 3:
        import ingest
        flags = {"--new", "--dry-run"}
        as_work = a[a.index("--as") + 1] if "--as" in a else None
        paths = [x for i, x in enumerate(a[2:], 2) if x not in flags and x != "--as" and a[i - 1] != "--as"]
        ingest.add(a[1], paths, as_work=as_work, force_new="--new" in a, dry="--dry-run" in a)
    else:
        sys.exit(__doc__)
