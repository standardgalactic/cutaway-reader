/*
 * model.js: the canonical model shared by every Cutaway Reader interface.
 *
 * The cockpit (WebGL), the in-page text navigator and the terminal client all call these
 * functions. None of them keeps its own history: each produces the same events, appends them
 * to one reader log, and derives state from that log.
 *
 *   graph   (meaning)            -> topology: chambers, tunnels, citations, exits
 *   ledger  (remembered place)   -> positions and radii, never recomputed
 *   log     (one reader's acts)  -> append-only events with identity, merged by set union
 *
 * No rendering and no dependencies. Works as a browser global (CutawayModel) and in Node.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CutawayModel = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Vocabulary shared with Haplopraxis:
  //   scan   = temporary glimpse (this file)
  //   beacon = persistent personal mark (this file)
  //   flare  = persistent shared inscription (reserved; never produced or read as a scan here)
  const SCAN_MS = 20000;       // a scan is a glimpse, not a discovery
  const SCAN_RADIUS = 70;
  const ROLE_TEXT = { main: "main passage", foundation: "foundation, below", consequence: "consequence, above",
    comparison: "comparison, alongside", appendix: "appendix shaft", alcove: "alcove" };
  const THREAD_TEXT = { missing: "missing work", extension: "optional extension",
    evidence: "unresolved evidence", open: "principled openness" };
  const THREAD_CODE = { missing: "M", extension: "X", evidence: "E", open: "O" };

  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  const pairKey = (a, b) => (a < b ? a + "|" + b : b + "|" + a);
  const other = (t, id) => (t.a === id ? t.b : t.a);

  /* ---------------- topology ---------------- */
  function build(data) {
    const G = data.graph, L = data.ledger, gById = new Map(G.nodes.map((n) => [n.id, n]));
    const nodes = new Map();
    for (const [id, l] of Object.entries(L.nodes)) {
      const g = gById.get(id) || {};
      nodes.set(id, { id, title: l.title, role: l.role, level: l.level, parent: l.parent || null,
        pos: l.pos.slice(), r: l.radius, status: l.status, thesis: !!g.thesis, threads: g.threads || [],
        text: g.text || [], image: g.image || null, order: g.order ?? 999, part: g.part || null });
    }
    const tunnels = new Map();
    for (const e of G.edges) {
      if (e.kind === "exit") continue;
      const A = nodes.get(e.from), B = nodes.get(e.to);
      if (!A || !B || A.status !== "active" || B.status !== "active") continue;
      const key = pairKey(e.from, e.to);
      if (!tunnels.has(key)) {
        const [a, b] = e.from < e.to ? [e.from, e.to] : [e.to, e.from];
        // physical traversal is two-way for every internal edge; direction lives in `cites`
        tunnels.set(key, { key, a, b, kinds: [], cites: [] });
      }
      const t = tunnels.get(key);
      if (!t.kinds.includes(e.kind)) t.kinds.push(e.kind);
      if (e.kind === "reference" || e.kind === "prerequisite") t.cites.push({ from: e.from, to: e.to, door: !!e.door });
    }
    const adj = new Map([...nodes.keys()].map((k) => [k, []]));
    for (const t of tunnels.values()) { adj.get(t.a).push(t); adj.get(t.b).push(t); }
    const exits = G.edges.filter((e) => e.kind === "exit" && nodes.get(e.from)?.status === "active")
      .map((e) => ({ from: e.from, to: e.to.replace(/^work:/, ""), oneway: e.traversal === "one-way" }));
    return { work: G.work, nodes, tunnels, adj, exits, history: L.history || [] };
  }

  const live = (m) => [...m.nodes.values()].filter((n) => n.status === "active");
  const sections = (m) => live(m).filter((n) => n.level === "section");

  function readingOrder(m) {
    const s = sections(m), by = (a, b) => a.order - b.order;
    return s.filter((n) => n.role !== "appendix").sort(by).concat(s.filter((n) => n.role === "appendix").sort(by)).map((n) => n.id);
  }
  function startChamber(m) { return readingOrder(m)[0]; }

  function pathBetween(m, a, b) {
    if (a === b) return [];
    const prev = new Map([[a, null]]), q = [a];
    while (q.length) {
      const x = q.shift(); if (x === b) break;
      for (const t of m.adj.get(x) || []) { const y = other(t, x); if (!prev.has(y)) { prev.set(y, { from: x, to: y, t }); q.push(y); } }
    }
    if (!prev.has(b)) return null;
    const hops = []; let x = b;
    while (prev.get(x)) { const s = prev.get(x); hops.unshift(s); x = s.from; }
    return hops;
  }

  function relations(m, id) {
    const outs = [], ins = [];
    for (const t of m.adj.get(id) || []) for (const c of t.cites) {
      if (c.from === id) outs.push(c.to); if (c.to === id) ins.push(c.from);
    }
    return { outs, ins };
  }

  /* ---------------- reader log: identity, ordering, union ---------------- */
  function uuid() {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0; return (c === "x" ? r : (r & 3) | 8).toString(16); });
  }
  function fnv(str) { // two 32-bit FNV-1a passes -> 16 hex chars
    let h1 = 0x811c9dc5, h2 = 0x01000193 ^ 0x5bd1e995;
    for (let i = 0; i < str.length; i++) { const c = str.charCodeAt(i); h1 = Math.imul(h1 ^ c, 16777619); h2 = Math.imul(h2 ^ c, 2246822519); }
    return (h1 >>> 0).toString(16).padStart(8, "0") + (h2 >>> 0).toString(16).padStart(8, "0");
  }
  const newActor = () => "a-" + uuid().slice(0, 8);
  const cmp = (x, y) => x.seq - y.seq || (x.actor < y.actor ? -1 : x.actor > y.actor ? 1 : 0) || (x.id < y.id ? -1 : x.id > y.id ? 1 : 0);

  /** Give an event its identity. seq is a Lamport clock: one more than anything this actor has seen. */
  function stamp(events, actor, body, at) {
    for (const k of ["id", "actor", "seq", "at"]) if (k in body) throw new Error("event body may not set '" + k + "': identity belongs to the log");
    const seq = events.reduce((m, e) => Math.max(m, e.seq || 0), 0) + 1;
    return Object.assign({ id: uuid(), actor, seq, at: at || new Date().toISOString() }, body);
  }
  /** Set union by event id, in causal order. Nothing is ever replaced or dropped. */
  function merge(a, b) {
    const byId = new Map();
    for (const e of a) if (e && e.id) byId.set(e.id, e);
    for (const e of b) if (e && e.id && !byId.has(e.id)) byId.set(e.id, e);
    return [...byId.values()].sort(cmp);
  }
  /** Old logs (before identity existed) get ids once, deterministically ordered as they were. */
  function upgrade(events, actor) {
    let seq = 0; const beaconByN = new Map(), out = [];
    const isEarlyScan = (e) => e.t === "flare" && Array.isArray(e.pos) && !("text" in e) && !("inscription" in e);
    for (const e0 of events) {
      // Cutaway briefly called its 20-second glimpse a "flare". Same event, same id, correct name.
      const e = isEarlyScan(e0) ? Object.assign({}, e0, { t: "scan", renamedFrom: "flare" }) : e0;
      if (e.id && e.seq && e.actor) { out.push(e); if (e.t === "beacon") beaconByN.set(e.n, e.id); continue; }
      // first-version events used `id` for the chamber; move it, then give the event its own identity
      const x = Object.assign({}, e); delete x.id;
      if (["enter", "bind", "unbind", "read"].includes(e.t) && e.id && !e.chamber) x.chamber = e.id;
      // deterministic: upgrading the same legacy log twice yields the same ids, so merges stay idempotent
      Object.assign(x, { id: "legacy-" + fnv(JSON.stringify(e) + "|" + seq), actor: "legacy", seq: ++seq });
      if (x.t === "beacon") beaconByN.set(x.n, x.id);
      if (x.t === "retire" && !x.ref && beaconByN.has(x.n)) x.ref = beaconByN.get(x.n);
      out.push(x);
    }
    return out;
  }

  /* ---------------- derived reader state ---------------- */
  function derive(m, events, nowMs) {
    const now = nowMs ?? Date.now();
    const S = { visited: new Set(), traversed: new Set(), revealed: new Set(), revealedT: new Set(),
      glimpse: new Set(), glimpseT: new Set(), scansActive: 0, scanExpires: 0,
      beacons: new Map(), route: [], policy: "reading", trail: [], here: null, prevSession: null, reads: [] };
    const sessions = events.filter((e) => e.t === "session");
    S.prevSession = sessions.length > 1 ? sessions[sessions.length - 2] : null;
    for (const e of events) {
      switch (e.t) {
        case "enter": if (m.nodes.get(e.chamber)?.status === "active") { S.visited.add(e.chamber); S.here = e.chamber; } break;
        case "traverse": if (m.tunnels.has(e.key)) { S.traversed.add(e.key); S.trail.push(e); } break;
        case "scan": {
          const age = now - Date.parse(e.at);
          if (age >= 0 && age < SCAN_MS) {
            S.scansActive++; S.scanExpires = Math.max(S.scanExpires, Date.parse(e.at) + SCAN_MS);
            for (const n of m.nodes.values()) if (dist(n.pos, e.pos) < SCAN_RADIUS) S.glimpse.add(n.id);
            for (const t of m.tunnels.values()) {
              const A = m.nodes.get(t.a).pos, B = m.nodes.get(t.b).pos;
              const mid = [(A[0] + B[0]) / 2, (A[1] + B[1]) / 2, (A[2] + B[2]) / 2];
              if (dist(A, e.pos) < SCAN_RADIUS || dist(B, e.pos) < SCAN_RADIUS || dist(mid, e.pos) < SCAN_RADIUS) S.glimpseT.add(t.key);
            }
          }
          break;
        }
        case "beacon": S.beacons.set(e.id, e); break;
        case "retire": S.beacons.delete(e.ref); break;
        case "bind": if (!S.route.includes(e.chamber)) S.route.push(e.chamber); break;
        case "unbind": S.route = S.route.filter((x) => x !== e.chamber); break;
        case "policy": S.policy = e.name; break;
        case "read": S.reads.push(e.chamber); break;
      }
    }
    // Permanent knowledge comes only from being there: a visited chamber shows its own doorways.
    for (const id of S.visited) {
      S.revealed.add(id);
      for (const t of m.adj.get(id) || []) { S.revealedT.add(t.key); S.revealed.add(other(t, id)); }
    }
    for (const k of S.traversed) S.revealedT.add(k);
    for (const k of S.glimpseT) if (S.revealedT.has(k)) S.glimpseT.delete(k);
    for (const k of S.glimpse) if (S.revealed.has(k)) S.glimpse.delete(k);
    return S;
  }

  function stateOf(S, id) { return S.visited.has(id) ? "visited" : S.revealed.has(id) ? "revealed" : S.glimpse.has(id) ? "glimpsed" : "unexplored"; }
  function tunnelState(S, key) { return S.traversed.has(key) ? "traversed" : S.revealedT.has(key) ? "revealed" : S.glimpseT.has(key) ? "glimpsed" : "unexplored"; }

  /* ---------------- routes (scripts and policies) ---------------- */
  const POLICIES = [["reading", "Reading order"], ["prereq", "Prerequisites first"], ["threads", "Open threads"], ["bound", "Bound chambers"]];
  function routeTargets(m, S) {
    if (S.policy === "bound") return S.route.filter((id) => m.nodes.get(id)?.status === "active");
    const order = readingOrder(m);
    if (S.policy === "threads") return order.filter((id) => m.nodes.get(id).threads.length);
    if (S.policy === "prereq") {
      const out = [];
      for (const id of order) {
        for (const t of m.adj.get(id)) for (const c of t.cites)
          if (c.from === id && c.door && !S.visited.has(c.to) && !out.includes(c.to)) out.push(c.to);
        if (!out.includes(id)) out.push(id);
      }
      return out;
    }
    return order;
  }
  /** Remaining stops from where the reader is now. */
  function remainingStops(m, S, here) {
    const at = here || S.here, targets = routeTargets(m, S), i = targets.indexOf(at);
    return i >= 0 ? targets.slice(i + 1) : targets.filter((id) => id !== at);
  }

  /* ---------------- operations: every interface produces exactly these events ---------------- */
  const ops = {
    session: () => [{ t: "session" }],
    /** One crossing from a chamber into another: what the cockpit logs when the ship passes a wall. */
    cross(m, from, to) {
      const t = from && from !== to ? m.tunnels.get(pairKey(from, to)) : null;
      return t ? [{ t: "traverse", key: t.key, from, to }, { t: "enter", chamber: to }] : [{ t: "enter", chamber: to }];
    },
    /** Move along a real path: a sequence of crossings, identical to flying it hop by hop. */
    travel(m, from, to) {
      const hops = pathBetween(m, from, to);
      if (!hops) return null;
      return hops.flatMap((h) => ops.cross(m, h.from, h.to));
    },
    enter: (chamber) => [{ t: "enter", chamber }],
    scan: (pos, chamber) => [{ t: "scan", pos: pos.map((v) => +(+v).toFixed(2)), chamber: chamber || null }],
    beacon(m, S, { chamber, pos, quat, facing, note }) {
      const n = Math.max(0, ...[...S.beacons.values()].map((b) => b.n || 0)) + 1;
      return [{ t: "beacon", n, chamber, pos: (pos || m.nodes.get(chamber).pos).map((v) => +(+v).toFixed(2)),
        quat: quat || null, facing: facing || null, via: S.trail.slice(-3).map((x) => x.key), note: note || "" }];
    },
    retire: (beaconEventId) => [{ t: "retire", ref: beaconEventId }],
    bind: (chamber) => [{ t: "bind", chamber }],
    unbind: (chamber) => [{ t: "unbind", chamber }],
    policy: (name) => [{ t: "policy", name }],
    read: (id) => [{ t: "read", chamber: id }],
    cruise: (policy, stops) => [{ t: "cruise", policy, stops }],
    cruiseStop: (why) => [{ t: "cruise-stop", why }],
  };

  /* ---------------- passages, described by the fixed axes ---------------- */
  function describe(m, fromId, t) {
    const toId = other(t, fromId), A = m.nodes.get(fromId), B = m.nodes.get(toId), d = sub(B.pos, A.pos);
    const ax = [0, 1, 2].reduce((best, i) => (Math.abs(d[i]) > Math.abs(d[best]) ? i : best), 2);
    const k = t.kinds;
    let dir, rank;
    if (k.includes("alcove")) { dir = B.parent === A.id ? "into alcove" : "out to the parent chamber"; rank = 6; }
    else if (k.includes("sequence") || k.includes("shaft") || k.includes("branch")) {
      // axis words name where you arrive: foundation, consequence and comparison only when you are entering one
      const vert = d[1] < 0 ? "down" : "up";
      if (B.role === "main" && A.role !== "main" && A.role !== "appendix") { dir = (ax === 1 ? "back " + vert : "back across") + " to the main passage"; rank = 2; }
      else if (A.role === "appendix" && B.role === "appendix") { dir = vert === "down" ? "down the appendix shaft" : "up the shaft to the previous appendix"; rank = vert === "down" ? 4 : 3; }
      else if (B.role === "appendix") { dir = "down the appendix shaft"; rank = 4; }
      else if (A.role === "appendix") { dir = "up the shaft to the main passage"; rank = 3; }
      else if (B.role === "foundation") { dir = "down to foundation"; rank = 4; }
      else if (B.role === "consequence") { dir = "up to consequence"; rank = 3; }
      else if (B.role === "comparison") { dir = "side passage to comparison"; rank = 5; }
      else { dir = d[2] >= 0 ? "forward in reading order" : "back in reading order"; rank = d[2] >= 0 ? 1 : 2; }
    } else {
      const c = t.cites.find((x) => x.from === fromId) || t.cites[0];
      dir = c && c.from === fromId ? "reference tunnel to a section cited here" : "reference tunnel back to a section that cites this one";
      rank = 7;
    }
    const pre = t.cites.find((c) => c.door && c.to === toId && c.from === fromId);
    return { to: toId, key: t.key, dir, rank, prereq: !!pre, cites: t.cites };
  }
  function passages(m, S, id) {
    return (m.adj.get(id) || []).map((t) => describe(m, id, t)).sort((a, b) => a.rank - b.rank || m.nodes.get(a.to).order - m.nodes.get(b.to).order);
  }

  /** The textual projection of the world at one chamber. Rendered as HTML in the page and ANSI in a terminal. */
  function textView(m, S, id, portalsHere) {
    const n = m.nodes.get(id), last = S.trail[S.trail.length - 1];
    const ps = passages(m, S, id).map((p, i) => Object.assign(p, { n: i + 1, title: m.nodes.get(p.to).title,
      state: stateOf(S, p.to), tunnel: tunnelState(S, p.key), doorOpen: p.prereq && S.visited.has(p.to) }));
    const ex = (portalsHere || m.exits.filter((x) => x.from === id).map((x) => ({ to_work: x.to, dir: "exit to " + x.to, oneway: x.oneway, uncharted: true, chamber: x.from })))
      .filter((x) => x.chamber === id).map((x, i) => Object.assign({ n: ps.length + i + 1 }, x));
    const glimpsed = [...S.glimpseT].map((k) => m.tunnels.get(k)).filter((t) => t.a !== id && t.b !== id)
      .map((t) => ({ a: m.nodes.get(t.a).title, b: m.nodes.get(t.b).title, dir: describe(m, t.a, t).dir }));
    const counts = {};
    const threads = n.threads.map((t) => { const c = THREAD_CODE[t.kind] || "O"; counts[c] = (counts[c] || 0) + 1;
      return { code: c + counts[c], kind: t.kind, kindText: THREAD_TEXT[t.kind], text: t.text }; });
    const rel = relations(m, id);
    return {
      work: m.work, id, title: n.title, role: n.role, roleText: n.thesis ? "central thesis" : ROLE_TEXT[n.role],
      pos: n.pos, state: stateOf(S, id), arrivedFrom: last && last.to === id ? m.nodes.get(last.from).title : null,
      passages: ps, exits: ex, glimpsed, scanSeconds: S.scansActive ? Math.max(0, Math.round((S.scanExpires - Date.now()) / 1000)) : 0,
      threads, beacons: [...S.beacons.values()].filter((b) => b.chamber === id),
      cites: rel.outs.map((x) => m.nodes.get(x).title), citedBy: rel.ins.map((x) => m.nodes.get(x).title),
      alcoves: live(m).filter((x) => x.parent === id).map((x) => ({ id: x.id, title: x.title })),
      image: n.image, text: n.text,
    };
  }

  /** Search titles and prose within the work. */
  function search(m, q) {
    const s = q.trim().toLowerCase(); if (!s) return [];
    const hits = [];
    for (const n of live(m)) {
      const inTitle = n.title.toLowerCase().includes(s);
      const para = n.text.find((p) => p.toLowerCase().includes(s));
      if (inTitle || para) {
        let snip = "";
        if (para) { const i = para.toLowerCase().indexOf(s); snip = (i > 40 ? "…" : "") + para.slice(Math.max(0, i - 40), i + s.length + 60) + "…"; }
        hits.push({ id: n.id, title: n.title, snip, inTitle });
      }
    }
    return hits.sort((a, b) => b.inTitle - a.inTitle);
  }

  /** Oracle: which chambers can be reached from the start by the graph alone. */
  function reachability(m) {
    const start = startChamber(m), seen = new Set([start]), q = [start];
    while (q.length) { const x = q.shift(); for (const t of m.adj.get(x)) { const y = other(t, x); if (!seen.has(y)) { seen.add(y); q.push(y); } } }
    return { start, reachable: seen, unreachable: live(m).filter((n) => !seen.has(n.id)).map((n) => n.id) };
  }

  /* ================= corpus: many works, one reader log ================= */
  /** bundle = { corpus: {graph, ledger}, works: { id: {graph, ledger} } } (corpus.py export).
   *  A split bundle (corpus.py export DIR folder/) carries every work's record but no work bodies; then
   *  opts.load(id) -> {graph, ledger} | null reads one synchronously (terminal), or opts.fetch(id) -> Promise
   *  does it asynchronously (browser), and C.ensure(id) must settle before C.model(id) is used. */
  function buildCorpus(bundle, opts) {
    opts = opts || {};
    const g = bundle.corpus.graph, l = bundle.corpus.ledger, works = new Map(), cache = new Map(), pending = new Map();
    for (const w of g.works) {
      const p = l.works[w.id] || {};
      works.set(w.id, Object.assign({}, w, { pos: p.pos || [0, 0, 0], status: p.status || "active", conflicts: p.conflicts || [] }));
    }
    for (const [id, p] of Object.entries(l.works)) if (!works.has(id)) // withdrawn works stay as sealed systems
      works.set(id, { id, title: id, abstract: "", series: null, counts: { sections: 0, words: 0, threads: {} }, pos: p.pos, status: p.status, conflicts: p.conflicts || [] });
    const lanes = g.lanes.map((x, i) => Object.assign({ key: laneKey(x) }, x));
    return { id: g.corpus, title: g.title, works, lanes, series: g.series || {}, views: g.views || [{ id: "galaxy", title: "Galaxy" }],
      split: !!bundle.split,
      has(id) { const w = works.get(id); return !!w && w.status === "active" && (!!bundle.works[id] || !!bundle.split); },
      loaded(id) { return cache.has(id) || !!bundle.works[id]; },
      model(id) {
        if (!cache.has(id) && !bundle.works[id] && bundle.split && opts.load && works.has(id)) { const d = opts.load(id); if (d) bundle.works[id] = d; }
        if (!cache.has(id) && bundle.works[id]) cache.set(id, build(bundle.works[id]));
        return cache.get(id) || null; },
      ensure(id) { // resolves to the model, fetching the work the first time it is needed; one request per work
        if (this.loaded(id)) return Promise.resolve(this.model(id));
        if (!bundle.split || !opts.fetch || !works.has(id)) return Promise.resolve(this.model(id));
        if (!pending.has(id)) pending.set(id, opts.fetch(id).then((d) => { bundle.works[id] = d; pending.delete(id); return this.model(id); },
          (err) => { pending.delete(id); throw err; }));
        return pending.get(id); } };
  }
  /** A single work ({graph, ledger}) is a one-work corpus, so every interface has one code path. */
  function asBundle(data) {
    if (data.corpus && data.works) return data;
    const g = data.graph, secs = g.nodes.filter((n) => n.level === "section");
    const threads = {}; for (const n of g.nodes) for (const t of n.threads) threads[t.kind] = (threads[t.kind] || 0) + 1;
    return { corpus: { graph: { corpus: g.work, title: g.work, series: {}, lanes: g.edges.filter((e) => e.kind === "exit").map((e) =>
          ({ kind: "exit", from: g.work, from_chamber: e.from, to: e.to.replace(/^work:/, "").split("#")[0], to_label: null, traversal: e.traversal, uncharted: true })),
        works: [{ id: g.work, title: g.work, abstract: "", series: null, counts: { sections: secs.length, words: g.nodes.reduce((a, n) => a + n.words, 0), threads } }],
        views: [{ id: "galaxy", title: "Galaxy" }] },
      ledger: { works: { [g.work]: { pos: [0, 0, 0], status: "active" } } } }, works: { [g.work]: data } };
  }
  function laneKey(x) { return x.kind + ":" + x.from + (x.from_chamber ? "@" + x.from_chamber : "") + ">" + x.to + (x.to_label ? "#" + x.to_label : ""); }
  /** Where a lane lands. With the work loaded, from its live chambers; otherwise from the build's own answer
   *  (the lane's to_chamber), which was computed the same way. */
  function landing(C, wid, label, hint) {
    const w = C.works.get(wid), m = C.loaded ? (C.loaded(wid) ? C.model(wid) : null) : C.model(wid);
    if (!m) return hint || w?.start || null;
    if (label && m.nodes.get("L:" + label)?.status === "active") return "L:" + label;
    return startChamber(m) || w?.start || null;
  }
  /** Every way out of a work into another, with the chamber it opens from and where it lands.
   *  Declared exits open where they were written; a two-way exit also opens a way back at its landing;
   *  series lanes open from the work's first chamber. Uncharted exits are listed but lead nowhere yet. */
  function portals(C, wid) {
    const out = [], m = C.model(wid), start = m ? startChamber(m) : C.works.get(wid)?.start || null;
    for (const x of C.lanes) {
      const back = x.to === wid && x.from !== wid;
      if (x.from !== wid && !back) continue;
      const cites = x.kind === "cites-work", named = (id, t) => C.works.get(id)?.title || t || id;
      if ((x.kind === "exit" || cites) && !back) out.push({ lane: x.key, chamber: x.from_chamber, to_work: x.to, to_chamber: x.uncharted ? null : landing(C, x.to, x.to_label, x.to_chamber),
        to_title: named(x.to, x.to_title), dir: (cites ? "cites " : "exit to ") + named(x.to, x.to_title), oneway: x.traversal === "one-way",
        uncharted: !!x.uncharted, inferred: !!x.inferred, kind: cites ? "cites-work" : "exit" });
      else if ((x.kind === "exit" || cites) && back && x.traversal !== "one-way" && !x.uncharted) out.push({ lane: x.key, chamber: landing(C, wid, x.to_label, x.to_chamber), to_work: x.from, to_chamber: x.from_chamber,
        to_title: named(x.from), dir: (cites ? "cited by " : "exit back to ") + named(x.from) + sectionOf(C, x.from, x.from_chamber, x.from_chamber_title), oneway: false, uncharted: false, inferred: !!x.inferred, kind: cites ? "cited-by" : "exit-back" });
      else if (x.kind === "series") { const other = back ? x.from : x.to;
        out.push({ lane: x.key, chamber: start, to_work: other, to_chamber: landing(C, other, null, back ? null : x.to_chamber), kind: "series",
          dir: (back ? "previous" : "next") + " in series: " + (C.works.get(other)?.title || other), oneway: false, uncharted: false }); }
    }
    return out.filter((p) => p.chamber && C.works.get(p.to_work)?.status !== "withdrawn");
  }
  /** " (§ Section title)" for the chamber a way back leads to, so two ways back to one work stay distinguishable. */
  function sectionOf(C, wid, chamber, known) {
    const t = (C.loaded && !C.loaded(wid) ? null : C.model(wid)?.nodes.get(chamber)?.title) || known; return t ? " (§ " + t + ")" : ""; }
  /** Crossing into another work: a jump, then an enter that belongs to the destination. */
  ops.jump = (fromWork, fromChamber, portal) => [
    { t: "jump", work: fromWork, from_work: fromWork, from_chamber: fromChamber, to_work: portal.to_work, to_chamber: portal.to_chamber, lane: portal.lane || null },
    { t: "enter", work: portal.to_work, chamber: portal.to_chamber },
  ];
  /** Arriving in a work from outside any lane (a chosen system in the galaxy, a search). Recorded as a warp, honestly. */
  ops.warp = (fromWork, fromChamber, toWork, toChamber) => ops.jump(fromWork, fromChamber, { to_work: toWork, to_chamber: toChamber, lane: null });

  const workEvents = (events, wid) => events.filter((e) => !e.work || e.work === wid);
  function deriveCorpus(C, events) {
    const CS = { visited: new Set(), revealed: new Set(), lanesUsed: new Set(), here: null, hereChamber: null, jumps: [], warps: 0 };
    for (const e of events) {
      if (e.t === "enter" && e.work && C.works.has(e.work)) { CS.visited.add(e.work); CS.here = e.work; CS.hereChamber = e.chamber; }
      else if (e.t === "jump") { CS.jumps.push(e); if (e.lane) CS.lanesUsed.add(e.lane); else CS.warps++; }
    }
    for (const w of CS.visited) { CS.revealed.add(w); for (const x of C.lanes) { if (x.from === w && !x.uncharted) CS.revealed.add(x.to); if (x.to === w) CS.revealed.add(x.from); } }
    return CS;
  }
  const workState = (CS, id) => (CS.visited.has(id) ? "visited" : CS.revealed.has(id) ? "revealed" : "unexplored");

  /** Declared views: sorts and filters over the same work records (Notes views, Stars! reports). */
  function view(C, CS, id) {
    const v = C.views.find((x) => x.id === id) || C.views[0];
    const works = [...C.works.values()].filter((w) => w.status !== "withdrawn");
    const here = C.works.get(CS.here);
    const row = (w, extra) => Object.assign({ work: w.id, title: w.title, state: workState(CS, w.id),
      sub: `${w.counts.sections} sections · ${w.counts.words} words` + (w.conflicts.length ? " · placement conflict" : "") }, extra || {});
    let rows;
    if (v.select === "threads") {
      rows = [];
      for (const w of works) { // from the record, so the view needs no work loaded; a loaded work speaks for itself
        const m = C.loaded && !C.loaded(w.id) ? null : C.model(w.id);
        const list = m ? live(m).flatMap((n) => n.threads.map((t) => ({ chamber: n.id, chamber_title: n.title, kind: t.kind, text: t.text })))
                       : (w.open_threads || []);
        for (const t of list) rows.push({ work: w.id, chamber: t.chamber, title: w.title, state: workState(CS, w.id),
          group: THREAD_TEXT[t.kind], sub: t.text + " · " + t.chamber_title }); }
      rows.sort((a, b) => a.group.localeCompare(b.group));
    } else if (v.select === "unvisited") rows = works.filter((w) => !CS.visited.has(w.id)).map((w) => row(w));
    else if (v.group === "series") {
      rows = [];
      for (const [sid, s] of Object.entries(C.series)) for (const id of s.order) { const w = C.works.get(id); if (w && w.status !== "withdrawn") rows.push(row(w, { group: s.title })); }
      for (const w of works) if (!w.series) rows.push(row(w, { group: "Not in a series" }));
    } else if (v.sort === "-words") rows = works.slice().sort((a, b) => b.counts.words - a.counts.words).map((w) => row(w));
    else rows = works.slice().sort((a, b) => (here ? dist(a.pos, here.pos) - dist(b.pos, here.pos) : a.title.localeCompare(b.title)))
      .map((w) => row(w, { sub: (here && w.id !== here.id ? Math.round(dist(w.pos, here.pos)) + " away · " : "") + `${w.counts.sections} sections` + (w.conflicts.length ? " · placement conflict" : "") }));
    return { id: v.id, title: v.title, rows, views: C.views.map((x) => ({ id: x.id, title: x.title })) };
  }
  function corpusReachability(C) {
    const ids = [...C.works.values()].filter((w) => w.status !== "withdrawn").map((w) => w.id);
    const start = ids[0], seen = new Set([start]), q = [start];
    while (q.length) { const x = q.shift();
      for (const l of C.lanes) { if (l.uncharted) continue; const y = l.from === x ? l.to : (l.to === x && l.traversal !== "one-way" ? l.from : null);
        if (y && !seen.has(y) && ids.includes(y)) { seen.add(y); q.push(y); } } }
    return { start, unreachable: ids.filter((i) => !seen.has(i)), uncharted: C.lanes.filter((l) => l.uncharted).map((l) => l.from + " -> " + (l.to_title || l.to)) };
  }

  return { asBundle, buildCorpus, portals, deriveCorpus, workState, view, workEvents, corpusReachability, laneKey,
    SCAN_MS, SCAN_RADIUS, ROLE_TEXT, THREAD_TEXT, POLICIES, build, live, sections, readingOrder, startChamber,
    pathBetween, relations, pairKey, other, newActor, stamp, merge, upgrade, derive, stateOf, tunnelState,
    routeTargets, remainingStops, ops, passages, describe, textView, search, reachability, dist };
});
