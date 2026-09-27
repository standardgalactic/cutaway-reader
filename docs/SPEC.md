# Cutaway Reader: specification

This is the reference for what the reader is and how it behaves. `README.md` says how to run it;
`docs/FORMATS.md` describes the files; `schema/` holds the formal contracts the tests enforce.

## 1. The idea

A long argument has a shape: a main line, foundations it rests on, consequences it opens, comparisons
beside it, appendices below it. Flat text hides that shape. The reader turns each work into a level you
can fly through, so the shape is something you remember the way you remember a building. It borrows
from *Descent* (six degrees of freedom, a local-first automap), from *Stars!* (supervising routes and
policies instead of steering every move), from Lynx (a complete text interface over the same model),
and from Lotus Notes (replicated records, declared views, conflicts kept rather than overwritten).

## 2. A work as a level

| source | becomes |
|---|---|
| `\section` (in an article), `\chapter` (in a book) | a **chamber** |
| `\subsection` (article), `\section` (book) | an **alcove** inside its chamber |
| deeper headings | a marked line in the chamber's text |
| `\ref` to another chamber | a **tunnel**: physically two-way, semantically directed (citing → cited) |
| `\ref` to a foundation | the same tunnel, with a **door** |
| appendices | a **shaft** descending from the last main chamber |
| `\part` | a grouping on the map; parts over 20 chambers are flagged |

### Fixed axes

Directions mean the same thing in every work, so a reader's sense of place carries over:

- **forward (+Z)**: the main passage, in reading order
- **below (−Y)**: foundations, what a chamber rests on
- **above (+Y)**: consequences, what it opens
- **sideways (±X)**: comparisons
- **down a shaft**: appendices

Roles come from the source (`% mine: role=...`) or are inferred from headings and references; the
inference is shown, never hidden.

### Append-only place

The graph (what connects to what) is recomputed from the source on every run. The ledger (where each
chamber is) is append-only. A chamber, once dug, never moves. A new section is dug into free space
beside its neighbours. A removed section is withdrawn: sealed, still there, never reused. A chamber
keeps its identity through edits by its `\label` if it has one, otherwise by its heading and position
among same-titled siblings. So renaming an unlabelled heading digs a new chamber; `corpus.py report`
counts these as advice.

## 3. The corpus as a galaxy

Each work is a system in a galaxy. The corpus has the same split as a work: a graph recomputed on every
build, and a ledger that only grows.

- **Placement by accretion.** A new work settles near the placed works it most resembles (TF-IDF over
  title, abstract, headings and prose). Each resemblance asks for its own distance, closer when more
  alike, and the work settles where those requests are best met together. It is never nearer than 45
  units to another system. Placed works never move, so the galaxy records the order it grew in.
- **Editions.** A work may have several source files. The edition read is, in order: declared
  (`canonical` in the manifest), decided (`corpus.py choose`), or proposed (the longest, flagged until a
  person decides).
- **Withdrawn works** stay in the galaxy as sealed systems.
- **Replication.** Two copies of a galaxy merge by keeping both placements where they disagree
  (`corpus.py merge`), until a person resolves each (`resolve`) or adopts another galaxy's placements
  wholesale (`adopt <galaxy-id>`). Every ledger has a `galaxy_id`, minted once.

### Lanes

| lane | from | drawn |
|---|---|---|
| exit | `% mine: exit=work#label` in a source, or `corpus.py link` in the manifest | always; two-way unless `continue=` / `--oneway` |
| cites-work | a chamber citing one of the author's own works in its bibliography | always, marked *inferred* |
| series | the manifest's series order | always, two-way |
| suggestion | a chamber whose prose names another work's main title | **never**; listed until the author declares it |

Two exits declared from each end between the same two chambers are one lane (*declared from both
ends*). From different chambers they are two passages, and the build says so. A lane to a work not
in the corpus is kept and marked *uncharted*, so the corpus shows its own gaps.

## 4. The reader's log

Everything a reader does is an event in an append-only log: a set of events, each with an identity
(`id`, `actor`, a Lamport `seq`, `at`). Logs from different devices merge by set union and order by
(`seq`, `actor`, `id`). Nothing is ever edited or removed: retiring a beacon or unbinding a chamber is
itself an event. All state (visited, revealed, glimpsed, beacons, bound route, policy) is derived by
replaying the log. The same log drives the cockpit, the text navigator and the terminal client.

Events: `session`, `enter`, `traverse`, `scan`, `beacon`, `retire`, `bind`, `unbind`, `policy`,
`read`, `cruise`, `cruise-stop`, `jump`. A `jump` with no lane is a **warp**, recorded as such.

## 5. Vocabulary

| word | means | lasts |
|---|---|---|
| **scan** | a glimpse of the layout within 70 units | 20 seconds; reveals shape, never contents |
| **beacon** | a numbered personal mark with a note | until retired |
| **flare** | a shared inscription (Haplopraxis) | reserved; never produced here |
| **inspect** | read what a passage leads to before taking it | an action, not an event |
| **bind** | add a chamber to the route the cruise will follow | until unbound |
| **jump** | crossing into another work along a lane | an event |
| **warp** | arriving in another work without a lane (galaxy, search) | an event, counted separately |

Chamber states: *unexplored* → *glimpsed* (by a scan, temporarily) → *revealed* (seen from a visited
neighbour) → *visited*. Works: *unexplored* → *revealed* (a lane from a visited work) → *visited*.

## 6. Controls

### Cockpit (keyboard)

| keys | action |
|---|---|
| W S A D, R F | move forward, back, left, right, up, down |
| H J K L, arrows | orient (yaw, pitch) |
| Q E | roll |
| Tab or ; | automap: tap to latch, hold to peek |
| T | text navigator |
| Enter | read this chamber |
| Y or Space | inspect the passage ahead |
| U | bind the inspected chamber to the route |
| B | beacon, with a note |
| G | scan |
| O (hold) | optical: rear view |
| P (hold) | path replay |
| C | cruise the route, or speed up; Z slows; X stops |

### Automap

| keys | action |
|---|---|
| + / − | closer / wider: chamber, whole work, galaxy |
| 1–9 | find beacon N; Ctrl+D retires the selected beacon |
| [ ] | galaxy: select the previous / next system |
| Enter or a second click | galaxy: go to the selected system |

Map colours: traversed white, revealed blue, you and your trail green, route amber, prerequisite door
orange, exit magenta, open thread red.

### Touch (phones and tablets)

Left stick moves; dragging the view turns it; UP/DOWN change level. On the map, UP/DOWN become
OUT/IN (chamber, work, galaxy), drag turns, pinch zooms, a tap selects a system and a second tap goes
there. READ, LOOK (inspect), MAP and GO (cruise) are buttons.

### Text navigator and terminal

| keys | action |
|---|---|
| j k | select; Enter or 1–9 follows |
| h l | back / forward in this session |
| i, u, b, s | inspect, bind, beacon, scan |
| c / C | one cruise stop / cruise continuously |
| p | your path |
| w | corpus views (galaxy, series, length, open threads, not yet visited) |
| / | search this work |
| gg G | top / end |
| r | read |
| T or Esc | back to the cockpit |

### Cruise policies

`reading` (reading order), `prereq` (foundations before what rests on them), `threads` (chambers with
open threads), `bound` (only chambers you bound).

## 7. Open threads

`% thread[kind]: text` in a source, or `\todo{...}` (kind *missing*). Kinds: **missing** (missing
work), **extension** (optional extension), **evidence** (unresolved evidence), **open** (principled
openness: left open on purpose). There is no score for rescuing threads; they are marked, not graded.

## 8. Loading and hosting

A small corpus can ship as one bundle. A large one ships as an index (every work's record and every
lane, annotated with both ends' headings and landing chambers) plus one file per work, fetched the
first time a reader goes there. Nothing a reader sees depends on which works happen to be loaded; the
tests check that the two forms read identically.

The page builds two ways: as a claude.ai artifact (Three.js from cdnjs, fonts from Google Fonts), or
standalone (every third-party file vendored and pinned by SHA-256, no inline script or style, runs
under `Content-Security-Policy: default-src 'self'`).
