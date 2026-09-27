#!/usr/bin/env node
/*
 * cutaway-tty.js: the Cutaway Reader as a terminal program.
 *
 * Same model.js, same events, same derived state as the cockpit and the in-page text navigator.
 * The reader log is an append-only JSONL file; logs from other devices merge by set union.
 *
 *   node cutaway-tty.js <bundle.json | level.json | data_dir work-id> [--log FILE] [--merge FILE ...] [--check]
 *
 *   bundle.json  a whole corpus (corpus.py export DIR bundle.json)
 *   folder/      a split corpus (corpus.py export DIR folder/): index.json plus works/<id>.json, read as needed
 *   level.json   one work, {"graph": ..., "ledger": ...}; or a data dir plus work id (mine.py output)
 *   --log FILE   reader log (default: <corpus>.reader.jsonl beside the data)
 *   --merge FILE merge another log (JSONL, or the page's "Copy log" output)
 *   --check      print the graph oracle for every work and the corpus, then exit
 *
 * Commands at the prompt:
 *   N            follow passage or exit N    h / l    back / forward in this session
 *   i N          inspect passage or exit N   u N      bind passage N's chamber to the route
 *   b NOTE       drop a beacon here          s        scan (glimpse lasts 20 s)
 *   c            cruise one stop             policy reading|prereq|threads|bound
 *   p            your path                   m        supervisory summary (Stars!-style)
 *   w [VIEW]     corpus views: galaxy, series, size, threads, unexplored
 *   / WORDS      search this work            go N     travel to search hit N, or warp to view row N
 *   v            view this chamber again     q        quit
 */
"use strict";
const fs = require("fs"), path = require("path"), readline = require("readline");
const CM = require(path.join(__dirname, "model.js"));
process.stdout.on("error", (e) => { if (e.code === "EPIPE") process.exit(0); throw e; }); // e.g. piped into head

const argv = process.argv.slice(2);
const flag = (n) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : null; };
const merges = argv.flatMap((a, i) => (a === "--merge" ? [argv[i + 1]] : []));
const positional = argv.filter((a, i) => !a.startsWith("--") && !["--log", "--merge"].includes(argv[i - 1]));
if (!positional.length) { console.error(fs.readFileSync(__filename, "utf8").split("*/")[0]); process.exit(1); }

let raw, baseDir;
if (fs.existsSync(path.join(positional[0], "index.json"))) positional[0] = path.join(positional[0], "index.json"); // a split export folder
if (positional[0].endsWith(".json")) { raw = JSON.parse(fs.readFileSync(positional[0], "utf8")); baseDir = path.dirname(positional[0]); }
else { const [dir, work] = positional; baseDir = dir;
  raw = { graph: JSON.parse(fs.readFileSync(path.join(dir, work + ".graph.json"), "utf8")),
          ledger: JSON.parse(fs.readFileSync(path.join(dir, work + ".ledger.json"), "utf8")) }; }
const C = CM.buildCorpus(CM.asBundle(raw), { // a split export: each work is read from disk the first time it is needed
  load: (id) => { const f = path.join(baseDir, raw.split || "", id + ".json"); return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : null; } });
const wtitle = (w) => C.works.get(w)?.title || w;

/* ---------- oracle ---------- */
if (argv.includes("--check")) {
  let bad = 0;
  for (const w of C.works.values()) {
    if (w.status === "withdrawn") { console.log(`${w.id}: withdrawn, sealed`); continue; }
    const m = C.model(w.id), r = CM.reachability(m), lv = CM.live(m);
    console.log(`${w.id}: ${lv.length} chambers, ${m.tunnels.size} two-way tunnels, reachable ${r.reachable.size}/${lv.length}` +
      (r.unreachable.length ? "  UNREACHABLE: " + r.unreachable.join(", ") : ""));
    bad += r.unreachable.length;
    for (const p of CM.portals(C, w.id)) console.log(`    ${m.nodes.get(p.chamber).title}: ${p.dir}${p.uncharted ? " (uncharted)" : ""}${p.oneway ? " (one-way)" : ""}`);
  }
  const cr = CM.corpusReachability(C);
  console.log(`corpus ${C.id}: ${C.works.size} works, ${C.lanes.length} lanes; unreachable works: ${cr.unreachable.join(", ") || "none"}; uncharted exits: ${cr.uncharted.join(", ") || "none"}`);
  for (const w of C.works.values()) if (w.conflicts?.length) console.log(`placement conflict: ${w.id}`);
  process.exit(bad || cr.unreachable.length ? 2 : 0);
}

/* ---------- log ---------- */
const logFile = flag("--log") || path.join(baseDir, C.id + ".reader.jsonl");
const readLog = (file) => {
  if (!fs.existsSync(file)) return [];
  const txt = fs.readFileSync(file, "utf8").trim(); if (!txt) return [];
  if (txt.startsWith("{") && txt.includes('"events"') && !txt.includes("\n{")) { try { return JSON.parse(txt).events || []; } catch (_) {} }
  return txt.split("\n").filter(Boolean).map((l) => JSON.parse(l));
};
const actor = (() => { const f = path.join(baseDir, ".cutaway-actor"); try { return fs.readFileSync(f, "utf8").trim(); } catch (_) { const a = CM.newActor(); try { fs.writeFileSync(f, a); } catch (_) {} return a; } })();
const inCorpus = (e) => !e.work || C.works.has(e.work);
let events = CM.merge([], CM.upgrade(readLog(logFile), actor).filter(inCorpus));
for (const f of merges) {
  const have = new Set(events.map((e) => e.id)), fresh = CM.upgrade(readLog(f), actor).filter((e) => inCorpus(e) && !have.has(e.id));
  fs.appendFileSync(logFile, fresh.map((e) => JSON.stringify(e) + "\n").join(""));
  events = CM.merge(events, fresh); console.log(`merged ${fresh.length} new events from ${f}`);
}

let CS = CM.deriveCorpus(C, events);
let wid = CS.here && C.works.get(CS.here)?.status === "active" ? CS.here : [...C.works.values()].find((w) => w.status === "active").id;
let m = C.model(wid), S = CM.derive(m, CM.workEvents(events, wid));
let here = S.here && m.nodes.get(S.here)?.status === "active" ? S.here : CM.startChamber(m);
let items = [], hits = [], viewRows = [], back = [], fwd = [];
const title = (id) => m.nodes.get(id)?.title || id;
function rederive() { CS = CM.deriveCorpus(C, events); S = CM.derive(m, CM.workEvents(events, wid)); }
function append(bodies) {
  const out = [];
  for (const b of bodies) { const e = CM.stamp(events, actor, Object.assign({ work: wid }, b)); events.push(e); out.push(e); }
  fs.appendFileSync(logFile, out.map((e) => JSON.stringify(e) + "\n").join(""));
  rederive(); return out;
}
function enterWork(target, chamber) { wid = target; m = C.model(wid); here = chamber || CM.startChamber(m); back = []; fwd = []; rederive(); }

/* ---------- rendering ---------- */
const color = process.stdout.isTTY && !process.env.NO_COLOR;
const A = (code) => (s) => (color ? `\x1b[${code}m${s}\x1b[0m` : String(s));
const green = A("32"), dim = A("2"), yellow = A("33"), blue = A("34"), orange = A("38;5;208"), magenta = A("35"), bold = A("1");
const W = Math.min(process.stdout.columns || 88, 96);
const wrap = (s, ind = "") => { const out = []; let line = ind;
  for (const w of s.split(/\s+/)) { if ((line + w).length > W && line.trim()) { out.push(line.trimEnd()); line = ind; } line += w + " "; }
  if (line.trim()) out.push(line.trimEnd()); return out.join("\n"); };
function view() {
  const v = CM.textView(m, S, here, CM.portals(C, wid));
  items = v.passages.map((p) => ({ kind: "passage", to: p.to, key: p.key })).concat(v.exits.map((x) => ({ kind: "exit", x })));
  const L = [], w = C.works.get(wid);
  L.push("", bold(green("CUTAWAY READER · " + v.title)));
  L.push(dim("Work     ") + w.title + (w.series ? dim("  (" + (C.series[w.series]?.title || w.series) + ")") : ""), dim("Role     ") + v.roleText,
    dim("Position ") + `X ${Math.round(v.pos[0])} · Y ${Math.round(v.pos[1])} · Z ${Math.round(v.pos[2])}`);
  if (v.arrivedFrom) L.push(dim("Arrived  ") + v.arrivedFrom);
  L.push(dim("State    ") + v.state);
  if (v.cites.length) L.push(dim("Cites    ") + v.cites.join(", "));
  if (v.citedBy.length) L.push(dim("Cited by ") + v.citedBy.join(", "));
  const next = CM.remainingStops(m, S, here).slice(0, 3).map(title);
  L.push(dim("Route    ") + CM.POLICIES.find((p) => p[0] === S.policy)[1] + " · next: " + (next.join(" → ") || "end of route"));
  L.push("", dim("PASSAGES"));
  for (const p of v.passages) L.push(`${green("[" + p.n + "]")} ${dim(p.dir + ":")} ${p.title}` +
    (p.prereq ? " " + orange(p.doorOpen ? "(prerequisite, read)" : "(prerequisite door)") : "") + dim("  " + p.state + (p.tunnel === "traversed" ? " · traversed" : "")));
  for (const x of v.exits) L.push(`${green("[" + x.n + "]")} ${magenta(x.dir + (x.oneway ? " (one-way)" : "") + (x.uncharted ? " (not in this corpus)" : ""))}` +
    (x.uncharted ? "" : dim("  " + CM.workState(CS, x.to_work))));
  if (v.glimpsed.length) { L.push("", dim(`GLIMPSED BY SCAN · fades in ${v.scanSeconds} s`)); for (const g of v.glimpsed) L.push(blue(`  · ${g.a} ⇄ ${g.b} (${g.dir})`)); }
  if (v.threads.length) { L.push("", dim("OPEN THREADS")); for (const t of v.threads) L.push(`${green("[" + t.code + "]")} ${dim(t.kindText + ":")} ${t.text}`); }
  if (v.beacons.length) { L.push("", dim("BEACONS HERE")); for (const b of v.beacons) L.push(`${green(String(b.n))} ${b.note || "(no note)"}`); }
  L.push("", dim(v.image ? "Illustration: " + v.image : "No illustration yet."));
  for (const p of v.text) L.push("", wrap(p));
  console.log(L.join("\n"));
}
function travel(to, how) {
  if (to === here) return;
  const evs = CM.ops.travel(m, here, to); if (!evs) { console.log(yellow("No passage leads to " + title(to))); return; }
  if (how === "back") fwd.push(here); else { back.push(here); if (how !== "fwd") fwd = []; }
  append(evs); here = to;
  const hops = evs.filter((e) => e.t === "traverse").length;
  console.log(yellow(how === "back" ? "Back to " + title(to) : hops > 1 ? `Travelled ${hops} passages to ${title(to)}` : "Entered " + title(to)));
  view();
}
function jump(portal) {
  if (portal.uncharted) { console.log(magenta(`${portal.to_work} is not in this corpus yet`)); return; }
  const from = wid;
  append(CM.ops.jump(wid, here, portal));
  enterWork(portal.to_work, portal.to_chamber);
  console.log(yellow(`Crossed from ${wtitle(from)} into ${wtitle(wid)}`)); view();
}
function warp(target, chamber) {
  if (target === wid) { if (chamber) travel(chamber); return; }
  const to = chamber || CM.startChamber(C.model(target));
  append(CM.ops.warp(wid, here, target, to)); enterWork(target, to);
  console.log(yellow(`Warped to ${wtitle(target)} (no lane: recorded as a warp)`)); view();
}
function showView(id) {
  const v = CM.view(C, CS, id || "galaxy"); viewRows = v.rows; hits = [];
  console.log(bold(green(`\n${C.title.toUpperCase()} · ${v.title}`)) + dim("   views: " + v.views.map((x) => x.id).join(", ")));
  let group = null;
  v.rows.forEach((r, i) => { if (r.group && r.group !== group) { group = r.group; console.log(dim(group)); }
    const mark = r.work === wid ? green("◆") : r.state === "visited" ? "●" : r.state === "revealed" ? blue("○") : dim("·");
    console.log(`${green("[" + (i + 1) + "]")} ${mark} ${r.title} ${dim(r.sub)}`); });
  console.log(dim("go N warps there"));
}
function summary() {
  const secs = CM.sections(m), vis = secs.filter((n) => S.visited.has(n.id)).length;
  const worksVisited = [...C.works.values()].filter((w) => CS.visited.has(w.id)).length;
  console.log(bold(green(`\n${C.title.toUpperCase()} · ${worksVisited}/${C.works.size} works visited · ${CS.lanesUsed.size}/${C.lanes.filter((l) => !l.uncharted).length} lanes used` + (CS.warps ? ` · ${CS.warps} warps` : ""))));
  console.log(bold(`${wtitle(wid)} · ${vis}/${secs.length} chambers visited · ${S.traversed.size}/${m.tunnels.size} passages traversed`));
  console.log(dim("route ") + CM.POLICIES.find((p) => p[0] === S.policy)[1] + ": " + CM.routeTargets(m, S).map(title).join(" → "));
  const bs = [...S.beacons.values()].map((b) => `  ${b.n} ${b.note || "(no note)"} · ${title(b.chamber)}`);
  console.log(dim("beacons\n") + (bs.join("\n") || "  none"));
  const acts = new Set(events.map((e) => e.actor)).size;
  console.log(dim(`log ${logFile} · ${events.length} events from ${acts} device${acts > 1 ? "s" : ""}`));
}

/* ---------- loop ---------- */
append(CM.ops.session().map((e) => Object.assign(e, { work: null })));
if (!S.visited.has(here)) append(CM.ops.enter(here));
view();
const rl = readline.createInterface({ input: process.stdin, output: process.stdout, prompt: green("cutaway> ") });
rl.prompt();
rl.on("line", (line) => {
  const s = line.trim(), [cmd, ...rest] = s.split(/\s+/), arg = rest.join(" "), n = parseInt(arg, 10);
  rederive(); // scans age out between commands
  if (/^\d+$/.test(s)) { const it = items[+s - 1]; if (!it) console.log(yellow("No passage " + s)); else if (it.kind === "exit") jump(it.x); else travel(it.to); }
  else if (cmd === "h") { const to = back.pop(); to ? travel(to, "back") : console.log(yellow("No earlier chamber in this session")); }
  else if (cmd === "l") { const to = fwd.pop(); to ? travel(to, "fwd") : console.log(yellow("Nothing ahead in your history")); }
  else if (cmd === "i") { const it = items[n - 1];
    if (it && it.kind === "exit") { const x = it.x, w = C.works.get(x.to_work);
      console.log(`${x.dir}${x.oneway ? " · one-way" : " · two-way"}` + (w ? `\n  ${w.title}: ${w.abstract}\n  ${w.counts.sections} sections · ${CM.workState(CS, w.id)}` : "\n  not in this corpus yet")); }
    else if (!it) console.log(yellow("i N inspects passage N"));
    else { const t = m.tunnels.get(it.key), dest = m.nodes.get(it.to);
      console.log(`${title(t.a)} ⇄ ${title(t.b)} · two-way · ${CM.tunnelState(S, t.key)}`);
      for (const c of t.cites) console.log(`  ${title(c.from)} cites ${title(c.to)}${c.door ? " (prerequisite)" : ""}`);
      console.log(`  leads to ${dest.title} · ${CM.ROLE_TEXT[dest.role]} · ${CM.stateOf(S, dest.id)}${dest.threads.length ? ` · ${dest.threads.length} open thread(s)` : ""}`); } }
  else if (cmd === "u") { const it = items[n - 1]; if (!it || !it.to) console.log(yellow("u N binds passage N's chamber"));
    else if (S.route.includes(it.to)) console.log(yellow("Already on your route")); else { append(CM.ops.bind(it.to)); console.log(yellow("Bound to route: " + title(it.to))); } }
  else if (cmd === "b") { const out = append(CM.ops.beacon(m, S, { chamber: here, note: arg })); console.log(yellow(`Beacon ${out[0].n} dropped in ${title(here)}`)); }
  else if (cmd === "s") { append(CM.ops.scan(m.nodes.get(here).pos, here)); console.log(yellow(`Scan: ${S.glimpse.size + S.glimpseT.size} structures glimpsed for ${CM.SCAN_MS / 1000} s`)); view(); }
  else if (cmd === "c") { const next = CM.remainingStops(m, S, here)[0]; next ? travel(next) : console.log(yellow("End of route")); }
  else if (cmd === "policy") { if (!CM.POLICIES.some((p) => p[0] === arg)) console.log(yellow("policy reading|prereq|threads|bound")); else { append(CM.ops.policy(arg)); console.log(yellow("Route policy: " + arg)); } }
  else if (cmd === "p") { const h = S.trail.slice(-12).reverse(); console.log(h.length ? h.map((e) => `  ${title(e.from)} → ${title(e.to)}`).join("\n") : "No passages traversed in this work yet.");
    const j = CS.jumps.slice(-5).reverse(); if (j.length) console.log(dim("crossings\n") + j.map((e) => `  ${wtitle(e.from_work)} → ${wtitle(e.to_work)}${e.lane ? "" : " (warp)"}`).join("\n")); }
  else if (cmd === "m") summary();
  else if (cmd === "w") showView(arg || "galaxy");
  else if (s.startsWith("/")) { viewRows = []; hits = CM.search(m, s.slice(1)); console.log(hits.length ? hits.map((h, i) => `${green("[" + (i + 1) + "]")} ${h.title} ${dim(h.snip)}`).join("\n") + dim("\ngo N travels there by passage") : yellow("No matches")); }
  else if (cmd === "go") { if (hits.length) { const h = hits[n - 1]; h ? travel(h.id) : console.log(yellow("go N follows search hit N")); }
    else { const r = viewRows[n - 1]; r ? warp(r.work, r.chamber) : console.log(yellow("go N: list a view with w, or search with /")); } }
  else if (cmd === "v" || cmd === "") view();
  else if (cmd === "q") { rl.close(); return; }
  else console.log(yellow("Commands: N, h, l, i N, u N, b NOTE, s, c, policy NAME, p, m, w [VIEW], / WORDS, go N, v, q"));
  rl.prompt();
});
rl.on("close", () => process.exit(0));
