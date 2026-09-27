// Invariants shared by every interface. Run: node test_model.js
"use strict";
const assert = require("assert"), CM = require("./model.js");
const m = CM.build(require("./test/level.json"));
const stampAll = (log, actor, bodies, at) => { for (const b of bodies) log.push(CM.stamp(log, actor, b, at)); return log; };
let pass = 0; const ok = (name, fn) => { fn(); pass++; console.log("ok  " + name); };
const A = "L:sec:intro", B = "L:sec:cutaway", C = "L:sec:routes", D = "L:sec:thesis";

ok("flying hop by hop and travelling in text produce identical events", () => {
  const flown = [...CM.ops.cross(m, A, B), ...CM.ops.cross(m, B, C), ...CM.ops.cross(m, C, D)];
  assert.deepStrictEqual(CM.ops.travel(m, A, D), flown);
});
ok("switching modes keeps one history: fly A→B, text B→C, beacon in text", () => {
  const log = stampAll([], "dev1", [...CM.ops.session(), ...CM.ops.enter(A)]);
  stampAll(log, "dev1", CM.ops.cross(m, A, B));                    // cockpit
  stampAll(log, "dev1", CM.ops.travel(m, B, C));                   // text navigator
  let S = CM.derive(m, log);
  stampAll(log, "dev1", CM.ops.beacon(m, S, { chamber: C, facing: null, note: "compare with BYTE" }));
  S = CM.derive(m, log);
  assert.strictEqual(S.here, C);
  assert.ok(S.traversed.has(CM.pairKey(A, B)) && S.traversed.has(CM.pairKey(B, C)));
  const b = [...S.beacons.values()][0];
  assert.strictEqual(b.chamber, C); assert.deepStrictEqual(b.pos, m.nodes.get(C).pos.map(v => +v.toFixed(2)));
});
ok("a scan is a glimpse: it fades and never becomes knowledge", () => {
  const log = stampAll([], "d", [...CM.ops.enter(A)]);
  const before = CM.derive(m, log);
  stampAll(log, "d", CM.ops.scan(m.nodes.get(A).pos, A));
  const now = CM.derive(m, log), later = CM.derive(m, log, Date.now() + CM.SCAN_MS + 1000);
  assert.ok(now.glimpse.size + now.glimpseT.size > 0);
  assert.strictEqual(later.glimpse.size + later.glimpseT.size, 0);
  assert.deepStrictEqual([...later.revealed].sort(), [...before.revealed].sort());
  assert.deepStrictEqual([...now.revealed].sort(), [...before.revealed].sort());
});
ok("logs merge by set union: commutative, idempotent, nothing lost", () => {
  const base = stampAll([], "dev1", [...CM.ops.session(), ...CM.ops.enter(A)]);
  const x = stampAll(base.slice(), "dev1", CM.ops.travel(m, A, D));
  const y = stampAll(base.slice(), "dev2", [...CM.ops.bind("L:sec:obj"), ...CM.ops.policy("prereq")]);
  const xy = CM.merge(x, y), yx = CM.merge(y, x);
  assert.deepStrictEqual(xy.map(e => e.id), yx.map(e => e.id));
  assert.deepStrictEqual(CM.merge(xy, xy).map(e => e.id), xy.map(e => e.id));
  assert.strictEqual(xy.length, base.length + (x.length - base.length) + (y.length - base.length));
  const S = CM.derive(m, xy); assert.strictEqual(S.here, D); assert.deepStrictEqual(S.route, ["L:sec:obj"]); assert.strictEqual(S.policy, "prereq");
});
ok("Lamport order: an event appended after a merge sorts after everything it saw", () => {
  const a = stampAll([], "zz", CM.ops.enter(A)), b = stampAll([], "aa", [...CM.ops.enter(B), ...CM.ops.enter(C), ...CM.ops.enter(D)]);
  const merged = CM.merge(a, b); stampAll(merged, "zz", CM.ops.enter(B));
  assert.strictEqual(CM.merge([], merged).pop().actor, "zz"); assert.strictEqual(CM.derive(m, merged).here, B);
});
ok("first-version logs (no ids) are upgraded once, order preserved", () => {
  const legacy = [{ t: "session", at: "2026-09-27T09:00:00Z" }, { t: "enter", id: A, at: "2026-09-27T09:00:01Z" }, { t: "enter", id: B, at: "2026-09-27T09:00:02Z" }];
  const up = CM.upgrade(legacy, "dev"); assert.ok(up.every(e => e.id && e.seq)); assert.strictEqual(CM.derive(m, CM.merge([], up)).here, B);
  const again = CM.upgrade(legacy, "dev"); assert.deepStrictEqual(again.map(e => e.id), up.map(e => e.id));
  assert.strictEqual(CM.merge(up, again).length, up.length); // loading a legacy log twice never doubles it
});
ok("every tunnel is listed from both ends; citation direction survives", () => {
  const S = CM.derive(m, []);
  for (const t of m.tunnels.values()) {
    assert.ok(CM.passages(m, S, t.a).some(p => p.key === t.key), "missing from " + t.a);
    assert.ok(CM.passages(m, S, t.b).some(p => p.key === t.key), "missing from " + t.b);
    for (const c of t.cites) {
      const fromCiting = CM.passages(m, S, c.from).find(p => p.key === t.key), fromCited = CM.passages(m, S, c.to).find(p => p.key === t.key);
      if (!t.kinds.some(k => ["sequence", "shaft", "branch", "alcove"].includes(k))) {
        assert.match(fromCiting.dir, /cited here/); assert.match(fromCited.dir, /back to a section that cites/);
      }
    }
  }
});
ok("graph oracle: every live chamber reachable from the start", () => { assert.deepStrictEqual(CM.reachability(m).unreachable, []); });
ok("the reading passage runs straight: consecutive main chambers are adjacent", () => {
  const mains = CM.readingOrder(m).filter(id => m.nodes.get(id).role === "main");
  for (let i = 1; i < mains.length; i++) assert.ok(m.tunnels.has(CM.pairKey(mains[i - 1], mains[i])), mains[i - 1] + " -> " + mains[i]);
});
ok("re-entering a chamber is a new event, never a duplicate (regression)", () => {
  const log = stampAll([], "d", [...CM.ops.enter(A), ...CM.ops.cross(m, A, B), ...CM.ops.cross(m, B, A), ...CM.ops.cross(m, A, B)]);
  assert.strictEqual(CM.merge([], log).length, log.length);
  assert.strictEqual(new Set(log.map(e => e.id)).size, log.length);
});
ok("identity cannot be forged by an event body", () => {
  assert.throws(() => CM.stamp([], "d", { t: "enter", id: A }), /identity belongs to the log/);
});
ok("early 'flare' events load as scans; a flare carrying an inscription is not a scan", () => {
  const early = { id: "e1", actor: "d", seq: 1, at: new Date().toISOString(), t: "flare", pos: m.nodes.get(A).pos, chamber: A };
  const shared = { id: "e2", actor: "d", seq: 2, at: new Date().toISOString(), t: "flare", pos: m.nodes.get(A).pos, inscription: "left for the next reader" };
  const up = CM.upgrade([early, shared], "d");
  assert.strictEqual(up[0].t, "scan"); assert.strictEqual(up[0].id, "e1"); assert.strictEqual(up[0].renamedFrom, "flare");
  assert.strictEqual(up[1].t, "flare");
  const S = CM.derive(m, up); assert.strictEqual(S.scansActive, 1);
});
ok("the model never produces a flare", () => { assert.ok(!("flare" in CM.ops)); });
console.log(`\n${pass} invariants hold`);
