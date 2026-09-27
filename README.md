# Cutaway Reader

[Cutaway Reader](https://standardgalactic.github.io/cutaway-reader/cutaway-reader.pdf)

[Tract Script](https://standardgalactic.github.io/cutaway-reader/tract-script.pdf)

[Retro Comic](https://standardgalactic.github.io/cutaway-reader/do-tech-billionaires.pdf)

[Interactive Explorer](https://standardgalactic.github.io/cutaway-reader/) — *Experimental Interface*

A spatial reader for a corpus of LaTeX essays and books. Each work is a level to fly through:
sections are chambers, subsections alcoves, `\ref`s two-way tunnels, appendices shafts. Foundations
lie below, consequences above, comparisons to the side, and the main passage runs forward. Works sit
in a galaxy, joined by lanes their author declared, by citation, and by series order.

Two rules run through everything:

- **Meaning is recomputed; place is remembered.** Every `*.graph.json` is rebuilt from the sources
  on each run. Every `*.ledger.json` is append-only: a chamber, once dug, and a work, once placed, never
  move. What a reader has learned about where things are stays true.
- **Nothing is inferred silently.** An edition chosen for you is marked *proposed*. A lane guessed
  from prose is a *suggestion* until the author declares it. A placement two copies disagree on is
  kept as a *conflict* until a person resolves it.

## Working on a corpus

```sh
# 1. bring sources in: .tex files, .tex.txt attachments, folders or zips (multi-file sources work)
python3 corpus.py add trial/corpus.json ~/Downloads/*.tex ~/Downloads/some-paper.zip

# 2. build: mines changed works only, places new ones, draws lanes
python3 corpus.py build trial/corpus.json

# 3. see what needs a decision, most urgent first (also written to trial/data/report.md)
python3 corpus.py report trial/data

# 4. decide
python3 corpus.py choose trial/data joy-of-spherepop works/joy-of-spherepop/eba530ea8b.tex
python3 corpus.py links  trial/corpus.json                  # declared lanes and suggestions, numbered
python3 corpus.py link   trial/corpus.json --suggestion 3   # declare a suggested lane
python3 corpus.py link   trial/corpus.json "mem8-monograph@Event-Log Computation and Spherepop" spherepop
python3 corpus.py series trial/corpus.json comics "Standard Galactic Comics" spherepop portable-warrant
python3 corpus.py build  trial/corpus.json                  # decisions take effect at the next build

# 5. read
python3 corpus.py export trial/data trial/export            # split: index.json + works/<id>.json
python3 build_viewer.py artifact trial/export - site/cutaway-reader.html   # page + site/works/
node cutaway-tty.js trial/export                            # the same reader in a terminal
```

`corpus.py` with no arguments prints every command.

![](astounding-infographic.png)

## Files

| file | what it does |
|---|---|
| `mine.py` | one LaTeX source (with its `\input`s and `.bib`) → `<work>.graph.json` + `<work>.ledger.json` |
| `corpus.py` | many works → `corpus.graph.json` + `corpus.ledger.json`; editions, lanes, series, placement, merge, report, export |
| `ingest.py` | `corpus.py add`: content-addressed import, edition detection by title, `imports.jsonl` log |
| `model.js` | the one model every interface shares: levels, reader log (events, union merge), corpus, portals, views |
| `viewer_template.html` | the cockpit: 6DOF flight, automap, galaxy, text navigator, reader, touch controls |
| `build_viewer.py` | assembles the page: `artifact` (CDN) or `standalone` (vendored, strict CSP) |
| `cutaway-tty.js` | terminal client and `--check` oracle over the same model and log |
| `fetch_vendor.py`, `vendor/` | Three.js r128 and fonts, pinned by SHA-256 in `vendor/lock.json` |
| `docs/SPEC.md` | the design reference: axes, lanes, the log, vocabulary, every control |
| `docs/FORMATS.md`, `schema/` | every file format, and JSON Schemas the tests enforce |
| `Makefile` | `make`, `make report`, `make page`, `make test` (`make help` lists all) |
| `CHANGELOG.md` | what changed, newest first |

## Source directives

Written as LaTeX comments, so the paper still compiles unchanged:

```latex
% mine: thesis                    this chamber carries the central claim
% mine: role=comparison           foundation | consequence | comparison | appendix
% mine: exit=other-work#sec:label a lane to another work (two-way; lands at that label)
% mine: continue=other-work       a one-way lane, for a real irreversibility
% thread[missing]: needs a proof  an open thread; \todo{...} becomes one too
```

Lanes can also be declared in `corpus.json` (`corpus.py link`), which needs no edit to a paper.

## Tests

```sh
python3 test_all.py        # every suite below, with a summary (--fast skips the browser)
pip install -r requirements-dev.txt   # only the tests need anything beyond Python and Node
```

| suite | covers |
|---|---|
| `test_model.js` | a single level: reading order, tunnels, events, merge, derived state |
| `test_corpus.js` | the corpus model; split loading reads the same as the full bundle |
| `test_corpus_build.py` | placement ledger: append-only, gaps, merge/adopt, incremental builds |
| `test_manifest.py` | declared lanes and series, suggestions, the report |
| `test_ingest.py` | imports: idempotence, editions, zips, multi-file sources, the log |
| `test_schema.py` | every generated file and every event type against `schema/` |
| `test_viewer.py` | the page in a real browser: camera, portals, touch, on-demand loading |
