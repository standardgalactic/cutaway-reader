// Corpus invariants shared by every interface. Run: node test_corpus.js [bundle.json]
"use strict";
const assert = require("assert"), CM = require("./model.js");
const fs = require("fs"), path = require("path");
const BUNDLE_PATH = path.resolve(process.argv[2] || path.join(__dirname, "corpus/data/bundle.json"));
const BUNDLE = require(BUNDLE_PATH);
const C = CM.buildCorpus(BUNDLE);
const stampAll = (log, actor, bodies) => { for (const b of bodies) log.push(CM.stamp(log, actor, b)); return log; };
const tag = (work, bodies) => bodies.map((b) => Object.assign({ work }, b));
let pass = 0; const ok = (name, fn) => { fn(); pass++; console.log("ok  " + name); };
const MI = "memorable-interfaces", DR = "document-repositories", TG = "two-games", AM = "automap-spec";

ok("a jump's arrival belongs to the destination work; the source keeps its own state", () => {
  const log = stampAll([], "d", tag(MI, [...CM.ops.session(), ...CM.ops.enter("L:sec:intro")]));
  const mi = C.model(MI), p = CM.portals(C, MI).find((x) => x.to_work === DR);
  stampAll(log, "d", tag(MI, CM.ops.travel(mi, "L:sec:intro", p.chamber)));
  stampAll(log, "d", CM.ops.jump(MI, p.chamber, p));
  const Sdr = CM.derive(C.model(DR), CM.workEvents(log, DR)), Smi = CM.derive(mi, CM.workEvents(log, MI));
  assert.strictEqual(Sdr.here, p.to_chamber); assert.strictEqual(Smi.here, p.chamber);
  const CS = CM.deriveCorpus(C, log);
  assert.strictEqual(CS.here, DR); assert.ok(CS.lanesUsed.has(p.lane)); assert.strictEqual(CS.warps, 0);
});
ok("fly in one work, jump, travel by text in the next: one history, both works visited", () => {
  const log = stampAll([], "d", tag(MI, CM.ops.enter("L:sec:intro")));
  stampAll(log, "d", tag(MI, CM.ops.cross(C.model(MI), "L:sec:intro", "L:sec:cutaway")));      // cockpit
  const p = CM.portals(C, MI).find((x) => x.kind === "series");
  stampAll(log, "d", tag(MI, CM.ops.travel(C.model(MI), "L:sec:cutaway", p.chamber)));
  stampAll(log, "d", CM.ops.jump(MI, p.chamber, p));
  stampAll(log, "d", tag(AM, CM.ops.travel(C.model(AM), p.to_chamber, "L:sec:map-ego")));        // text navigator
  const CS = CM.deriveCorpus(C, log), S = CM.derive(C.model(AM), CM.workEvents(log, AM));
  assert.deepStrictEqual([...CS.visited].sort(), [AM, MI].sort()); assert.strictEqual(S.here, "L:sec:map-ego");
  assert.strictEqual(new Set(log.map((e) => e.id)).size, log.length);
});
ok("a two-way exit opens a way back at its landing; a one-way exit does not", () => {
  const fwd = CM.portals(C, DR).find((p) => p.kind === "exit" && p.to_work === MI);
  const back = CM.portals(C, MI).find((p) => p.kind === "exit-back" && p.to_work === DR && p.lane === fwd.lane);
  assert.ok(back); assert.strictEqual(back.chamber, fwd.to_chamber); assert.strictEqual(back.to_chamber, fwd.chamber);
  const oneway = JSON.parse(JSON.stringify(BUNDLE));
  oneway.corpus.graph.lanes.find((l) => l.kind === "exit" && l.from === DR).traversal = "one-way";
  const C2 = CM.buildCorpus(oneway);
  assert.ok(!CM.portals(C2, MI).some((p) => p.kind === "exit-back" && p.to_work === DR));
  assert.ok(CM.portals(C2, DR).some((p) => p.kind === "exit" && p.to_work === MI && p.oneway));
});
ok("an uncharted exit is listed but leads nowhere", () => {
  const u = CM.portals(C, MI).find((p) => p.uncharted);
  assert.ok(u); assert.strictEqual(u.to_chamber, null); assert.ok(!C.works.has(u.to_work));
});
ok("arriving without a lane is recorded as a warp, never as a lane", () => {
  const log = stampAll([], "d", tag(MI, CM.ops.enter("L:sec:intro")));
  stampAll(log, "d", CM.ops.warp(MI, "L:sec:intro", TG, CM.startChamber(C.model(TG))));
  const CS = CM.deriveCorpus(C, log); assert.strictEqual(CS.warps, 1); assert.strictEqual(CS.lanesUsed.size, 0); assert.strictEqual(CS.here, TG);
});
ok("views are projections of the same records", () => {
  const CS = CM.deriveCorpus(C, [{ t: "enter", work: MI, chamber: "L:sec:intro" }]);
  const series = CM.view(C, CS, "series").rows.filter((r) => r.group !== "Not in a series").map((r) => r.work);
  assert.deepStrictEqual(series, C.series.cutaway.order);
  assert.ok(!CM.view(C, CS, "unexplored").rows.some((r) => r.work === MI));
  const threads = CM.view(C, CS, "threads").rows, total = [...C.works.values()].reduce((a, w) => a + Object.values(w.counts.threads || {}).reduce((x, y) => x + y, 0), 0);
  assert.strictEqual(threads.length, total);
  const all = new Set(CM.view(C, CS, "galaxy").rows.map((r) => r.work)); assert.strictEqual(all.size, C.works.size);
});
ok("every work is reachable by lanes; uncharted exits are reported", () => {
  const r = CM.corpusReachability(C); assert.deepStrictEqual(r.unreachable, []); assert.ok(r.uncharted.length >= 1);
});
ok("a withdrawn work stays as a sealed system and opens no portals", () => {
  const b = JSON.parse(JSON.stringify(BUNDLE));
  b.corpus.graph.works = b.corpus.graph.works.filter((w) => w.id !== DR);
  b.corpus.graph.lanes = b.corpus.graph.lanes.filter((l) => l.from !== DR && l.to !== DR);
  b.corpus.ledger.works[DR].status = "withdrawn";
  const C3 = CM.buildCorpus(b);
  assert.strictEqual(C3.works.get(DR).status, "withdrawn"); assert.deepStrictEqual(C3.works.get(DR).pos, BUNDLE.corpus.ledger.works[DR].pos);
  assert.ok(!CM.portals(C3, MI).some((p) => p.to_work === DR));
});
ok("no two systems share a place", () => {
  const ws = [...C.works.values()];
  for (let i = 0; i < ws.length; i++) for (let j = i + 1; j < ws.length; j++) assert.ok(CM.dist(ws[i].pos, ws[j].pos) >= 45, ws[i].id + " / " + ws[j].id);
});
/* split exports: works arrive on demand, and nothing a reader sees may depend on what happens to be loaded */
const splitOf = (b) => { const s = JSON.parse(JSON.stringify(b)); const bodies = s.works; s.works = {}; s.split = "works/"; return [s, bodies]; };
for (const [name, file] of [["example", BUNDLE_PATH], ["trial", path.join(__dirname, "trial/data/bundle.json")]]) {
  if (!fs.existsSync(file)) continue;
  const full = JSON.parse(fs.readFileSync(file, "utf8")), CF = CM.buildCorpus(full);
  ok(`${name}: every work's ways out read the same with only that work loaded`, () => {
    for (const w of CF.works.values()) {
      if (w.status !== "active") continue;
      const [s, bodies] = splitOf(full), loads = [];
      const CL = CM.buildCorpus(s, { load: (id) => { loads.push(id); return bodies[id]; } });
      assert.deepStrictEqual(CM.portals(CL, w.id), CM.portals(CF, w.id), w.id);
      assert.deepStrictEqual(loads, [w.id], `${w.id} loaded ${loads}`);
    }
  });
  ok(`${name}: views and corpus reachability load no work at all`, () => {
    const [s, bodies] = splitOf(full), loads = [];
    const CL = CM.buildCorpus(s, { load: (id) => { loads.push(id); return bodies[id]; } }), CS = CM.deriveCorpus(CL, []);
    for (const v of CL.views) assert.deepStrictEqual(CM.view(CL, CS, v.id), CM.view(CF, CM.deriveCorpus(CF, []), v.id), v.id);
    assert.deepStrictEqual(CM.corpusReachability(CL), CM.corpusReachability(CF));
    assert.deepStrictEqual(loads, []);
  });
}
(async () => {
  const [s, bodies] = splitOf(JSON.parse(fs.readFileSync(BUNDLE_PATH, "utf8"))); let fetches = 0;
  const CL = CM.buildCorpus(s, { fetch: (id) => { fetches++; return new Promise((r) => setTimeout(() => r(bodies[id]), 5)); } });
  const id = [...CL.works.keys()][0];
  assert.strictEqual(CL.model(id), null);
  const [a, b] = await Promise.all([CL.ensure(id), CL.ensure(id)]);
  assert.ok(a && a === b && CL.model(id) === a && fetches === 1);
  const bad = CM.buildCorpus(splitOf(JSON.parse(fs.readFileSync(BUNDLE_PATH, "utf8")))[0], { fetch: () => Promise.reject(new Error("offline")) });
  await assert.rejects(bad.ensure(id)); await assert.rejects(bad.ensure(id)); // a failure is not remembered as success
  pass++; console.log("ok  in the browser a work is fetched once, however many ask for it, and a failed fetch can be retried");
  console.log(`\n${pass} corpus invariants hold`);
})();
