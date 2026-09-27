# Changelog

Newest first. Dates are when the change was made; there are no release numbers yet.

## 2026-09-27: project files, schemas, and a bibliography fix

- `docs/SPEC.md`: the design reference (axes, lanes, log, vocabulary, every control).
- `docs/FORMATS.md` and `schema/*.schema.json`: every file format, with `test_schema.py` checking
  every generated file and every event type against them (with `jsonschema` as a second opinion when
  installed). Writing them showed that events upgraded from the earliest logs carry no timestamp; the
  event schema now says so.
- `Makefile`, `requirements-dev.txt`, `.github/workflows/test.yml`.
- Bibliographies: a quoted title (`“Title,” in \emph{Venue}`) is now read as the title, not the venue.

## 2026-09-27: backend for a larger corpus

- `corpus.py add` (`ingest.py`): import `.tex`, `.tex.txt`, folders and zips; content-addressed
  editions; same main title means another edition; `imports.jsonl` log.
- Lanes and series declared in the manifest (`link`, `unlink`, `links`, `series`), and suggestions
  promoted with `link --suggestion N`.
- Incremental builds: a work is mined again only when its source or the miner changes.
- Parse notes kept on each work with a severity (problem or advice) instead of being discarded.
- `corpus.py report`: what needs a person, most urgent first, including how each draft differs.
- Split export and on-demand loading: the page carries only the index and fetches works as needed.
  Fixed a retry storm when a fetch failed inside a portal.
- `README.md`, `test_all.py`.

## 2026-09-27: touch flight

- Joystick, drag to look, UP/DOWN (OUT/IN on the map), READ, LOOK, MAP, GO.
- A galaxy system is selected by a tap, not by the start of a drag or pinch.
- Galaxy labels show main titles; the selected system shows its full title.

## 2026-09-27: second trial batch (ten works)

- Multi-file sources (`\input`, `\include`, `.bib`); titles split at top-level line breaks; accents,
  escapes and page furniture handled.
- Placement anchored on real resemblance (a clearly closer work is nearer).
- Prose mentions of another work's title become suggestions, never lanes.

## 2026-09-27: first real trial (MEM|8)

- Books: chapters as chambers, sections as alcoves; macros, math, theorem names; bibliography parsing
  and inferred `cites-work` lanes; uncharted lanes for cited works not in the corpus.

## Before

Single-work levels, the append-only ledger, the automap, the reader log with event identity and union
merge, the text navigator and terminal client, the corpus layer with its placement ledger, merge and
conflicts, the standalone build under a strict CSP, and the browser camera tests.
