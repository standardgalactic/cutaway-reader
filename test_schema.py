#!/usr/bin/env python3
"""Every file the tools write matches its schema in schema/. Run: python3 test_schema.py

The schemas are the written contract for anyone reading these files with other tools. The validator
below is a small stdlib-only subset of JSON Schema (the keywords the schemas use), so the check runs
anywhere; when the jsonschema package is installed it is used as a second, independent opinion."""
import json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = HERE / "schema"
passed = 0


def check(name, cond, detail=""):
    global passed
    assert cond, f"{name} {detail}"
    passed += 1
    print("ok  " + name + (f"  ({detail})" if detail else ""))


TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def is_type(v, t):
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, TYPES[t])


def errors(v, s, path="$"):
    """Yield (path, message) for every way v fails schema s."""
    if "oneOf" in s:
        ok = [sub for sub in s["oneOf"] if not any(True for _ in errors(v, sub, path))]
        if len(ok) != 1:
            yield path, f"matches {len(ok)} of the oneOf alternatives, not exactly one"
        return
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(is_type(v, t) for t in ts):
            yield path, f"is {type(v).__name__}, expected {s['type']}"
            return
    if "const" in s and v != s["const"]:
        yield path, f"is {v!r}, expected {s['const']!r}"
    if "enum" in s and v not in s["enum"]:
        yield path, f"is {v!r}, not one of {s['enum']}"
    if isinstance(v, str) and "pattern" in s and not re.search(s["pattern"], v):
        yield path, f"{v!r} does not match {s['pattern']}"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            yield path, f"{v} < {s['minimum']}"
        if "exclusiveMinimum" in s and v <= s["exclusiveMinimum"]:
            yield path, f"{v} <= {s['exclusiveMinimum']}"
    if isinstance(v, list):
        if "minItems" in s and len(v) < s["minItems"]:
            yield path, f"has {len(v)} items, fewer than {s['minItems']}"
        if "maxItems" in s and len(v) > s["maxItems"]:
            yield path, f"has {len(v)} items, more than {s['maxItems']}"
        if "items" in s:
            for i, x in enumerate(v):
                yield from errors(x, s["items"], f"{path}[{i}]")
    if isinstance(v, dict):
        for k in s.get("required", []):
            if k not in v:
                yield path, f"lacks required '{k}'"
        props = s.get("properties", {})
        for k, x in v.items():
            if "propertyNames" in s:
                yield from ((p, "key " + m) for p, m in errors(k, s["propertyNames"], f"{path}.{k}"))
            if k in props:
                yield from errors(x, props[k], f"{path}.{k}")
            elif s.get("additionalProperties") is False:
                yield f"{path}.{k}", "is not allowed here"
            elif isinstance(s.get("additionalProperties"), dict):
                yield from errors(x, s["additionalProperties"], f"{path}.{k}")


def load(name):
    return json.loads((SCHEMA / name).read_text())


def valid(doc, schema):
    errs = list(errors(doc, schema))
    return not errs, "; ".join(f"{p} {m}" for p, m in errs[:3])


try:
    import jsonschema
    def second_opinion(doc, schema):
        return jsonschema.Draft202012Validator(schema).is_valid(doc)
except ImportError:
    second_opinion = None

S = {n: load(n) for n in ["work.graph.schema.json", "work.ledger.schema.json", "corpus.manifest.schema.json",
                          "corpus.graph.schema.json", "corpus.ledger.schema.json", "event.schema.json"]}
if second_opinion:
    import jsonschema as js
    for n, s in S.items():
        js.Draft202012Validator.check_schema(s)
    check("every schema is itself valid JSON Schema (draft 2020-12)", True)

corpora = [d for d in (HERE / "corpus", HERE / "trial") if (d / "data" / "corpus.graph.json").exists()]
for d in corpora:
    files = [(d / "corpus.json", "corpus.manifest.schema.json"),
             (d / "data" / "corpus.graph.json", "corpus.graph.schema.json"),
             (d / "data" / "corpus.ledger.json", "corpus.ledger.schema.json")]
    files += [(p, "work.graph.schema.json") for p in sorted((d / "data" / "works").glob("*.graph.json"))]
    files += [(p, "work.ledger.schema.json") for p in sorted((d / "data" / "works").glob("*.ledger.json"))]
    bad = []
    for p, n in files:
        doc = json.loads(p.read_text())
        ok, why = valid(doc, S[n])
        if not ok:
            bad.append(f"{p.relative_to(HERE)}: {why}")
        if second_opinion and second_opinion(doc, S[n]) != ok:
            bad.append(f"{p.relative_to(HERE)}: the two validators disagree")
    check(f"{d.name}: every file the build wrote matches its schema", not bad, "; ".join(bad[:3]) or f"{len(files)} files")

# reader events: produce a real log through the model's own operations, then validate every line
script = r"""
const CM = require(process.argv[1] + "/model.js"), fs = require("fs");
const B = JSON.parse(fs.readFileSync(process.argv[1] + "/corpus/data/bundle.json", "utf8")), C = CM.buildCorpus(B);
const W = [...C.works.keys()], m = C.model(W[0]), order = CM.readingOrder(m), log = [];
const put = (bodies, work) => { for (const b of bodies) log.push(CM.stamp(log, "a-test", Object.assign({ work }, b))); };
put(CM.ops.session(), null);
put(CM.ops.enter(order[0]), W[0]); put(CM.ops.travel(m, order[0], order[2]), W[0]);
put(CM.ops.scan([1, 2, 3], order[2]), W[0]);
let S = CM.derive(m, log); put(CM.ops.beacon(m, S, { chamber: order[2], note: "come back" }), W[0]);
put(CM.ops.retire(log[log.length - 1].id), W[0]);
put(CM.ops.bind(order[1]), W[0]); put(CM.ops.unbind(order[1]), W[0]); put(CM.ops.policy("threads"), W[0]);
put(CM.ops.read(order[2]), W[0]); put(CM.ops.cruise("reading", order.slice(0, 3)), W[0]); put(CM.ops.cruiseStop("arrived"), W[0]);
const p = CM.portals(C, W[0]).find((x) => !x.uncharted); put(CM.ops.jump(W[0], p.chamber, p), W[0]);
put(CM.ops.warp(p.to_work, p.to_chamber, W[2], CM.startChamber(C.model(W[2]))), p.to_work);
const legacy = CM.upgrade([{ t: "enter", id: order[0] }, { t: "flare", pos: [0, 0, 0] }], "a-old");
process.stdout.write(JSON.stringify({ log, legacy }));
"""
out = json.loads(subprocess.run(["node", "-e", script, str(HERE)], capture_output=True, text=True, check=True).stdout)
types = sorted({e["t"] for e in out["log"]})
bad = [f"{e['t']}: {valid(e, S['event.schema.json'])[1]}" for e in out["log"] + out["legacy"] if not valid(e, S["event.schema.json"])[0]]
check("every event the model produces matches the event schema", not bad, "; ".join(bad[:3]) or ", ".join(types))
if second_opinion:
    check("the jsonschema package agrees on every event", all(second_opinion(e, S["event.schema.json"]) for e in out["log"] + out["legacy"]))

# the schemas must refuse, too
g = json.loads((corpora[0] / "data" / "works" / next(iter(sorted(p.name for p in (corpora[0] / "data" / "works").glob("*.graph.json"))))).read_text())
broken = [("a chamber role outside the fixed axes", lambda x: x["nodes"][0].__setitem__("role", "sideways")),
          ("an edge with no traversal", lambda x: x["edges"][0].pop("traversal")),
          ("a chamber id that is neither a label nor a heading", lambda x: x["nodes"][0].__setitem__("id", "chamber-1"))]
for name, spoil in broken:
    x = json.loads(json.dumps(g)); spoil(x)
    check(f"the work graph schema refuses {name}", not valid(x, S["work.graph.schema.json"])[0])
e = dict(out["log"][1]); del e["chamber"]
check("the event schema refuses an enter without a chamber", not valid(e, S["event.schema.json"])[0])
e = dict(out["log"][1]); e["t"] = "flare"
check("the event schema refuses 'flare', which is reserved and never produced", not valid(e, S["event.schema.json"])[0])
man = json.loads((corpora[0] / "corpus.json").read_text()); man["lanes"] = [{"from": "x", "to": "y", "colour": "red"}]
check("the manifest schema refuses a lane field it does not know", not valid(man, S["corpus.manifest.schema.json"])[0])

print(f"\n{passed} schema invariants hold")
