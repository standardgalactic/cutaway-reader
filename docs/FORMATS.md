# File formats

Every file the tools write is JSON (or JSON Lines), described by a schema in `schema/`
(JSON Schema, draft 2020-12). `python3 test_schema.py` checks every generated file against them.

| file | written by | changes | schema |
|---|---|---|---|
| `corpus.json` | you, `corpus.py add / link / series` | when you decide something | `corpus.manifest.schema.json` |
| `imports.jsonl` | `corpus.py add` | appended | one object per line: `at, what, work, how, title, from, hash, files, path` |
| `data/works/<id>.graph.json` | `mine.py` (via `corpus.py build`) | recomputed when the source or the miner changes | `work.graph.schema.json` |
| `data/works/<id>.ledger.json` | `mine.py` | append-only | `work.ledger.schema.json` |
| `data/corpus.graph.json` | `corpus.py build` | recomputed every build | `corpus.graph.schema.json` |
| `data/corpus.ledger.json` | `corpus.py build / merge / resolve / adopt / choose` | append-only | `corpus.ledger.schema.json` |
| `data/report.md`, `report.json` | `corpus.py report` | rewritten | human-readable; JSON mirrors its sections |
| `<corpus>.reader.jsonl` | the terminal client, the page's store | appended, merged by union | `event.schema.json`, one event per line |
| `bundle.json` | `corpus.py export DIR x.json` | rewritten | `{corpus: {graph, ledger}, works: {id: {graph, ledger}}}` |
| `export/index.json` + `export/works/<id>.json` | `corpus.py export DIR folder/` | rewritten | index: a bundle with `works: {}` and `split: "works/"` |

## Identity

- **Work ids** are lowercase slugs (`[a-z0-9-]`), taken from the main title on import and never
  changed after; the reader log refers to works by id.
- **Chamber ids** are `L:<label>` for a labelled heading and `G:<heading-slug>` otherwise, with `-2`,
  `-3` for repeats. The ledger's `labels` and `aliases` keep them stable across edits.
- **Edition ids** are the first ten hex digits of the source hash. For a source spread over several
  files, the hash covers every file it reads, by relative path.
- **Event ids** are random UUIDs; events upgraded from logs that predate identity get
  `legacy-<fnv hash>`, deterministic so that upgrading twice gives the same ids.
- **Galaxy ids** are `g-<12 hex>`, minted once per ledger.

## What never happens

- A ledger entry is never deleted or moved. Withdrawal is a status; history is appended.
- An event is never edited or removed. Retire and unbind are events.
- A proposed edition, an inferred lane or a suggestion is never presented as a decision. Each carries
  its own marker (`edition_how: "proposed"`, `inferred: true`, the separate `suggestions` list).
- A placement conflict is never resolved automatically. Both placements are kept until a person picks.

## Lane fields (corpus graph)

| field | meaning |
|---|---|
| `from`, `to` | work ids (`to` may be `title:<slug>` for a cited work not in the corpus) |
| `kind` | `exit`, `cites-work`, `series` |
| `traversal` | `two-way` or `one-way` |
| `from_chamber`, `from_chamber_title` | where it opens |
| `to_label`, `to_chamber` | where it lands (the label asked for, and the chamber it resolves to) |
| `uncharted` | the destination is not in the corpus yet |
| `inferred` | drawn from a citation, not declared |
| `declared` | `both ends` when two reciprocal exits were coalesced |
| `declared_in` | `manifest` when declared with `corpus.py link` rather than in a source |
| `via`, `to_title` | for citation lanes: the bibliography key and the cited title |
