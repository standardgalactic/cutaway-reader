# Cutaway Reader. `make` builds and checks the trial corpus; `make help` lists targets.
# CORPUS may point at any corpus.json:  make CORPUS=corpus/corpus.json
CORPUS ?= trial/corpus.json
DIR    := $(dir $(CORPUS))
DATA   := $(DIR)data
EXPORT := $(DIR)export
PY     ?= python3

.PHONY: all help build report export page standalone check test test-fast tty clean-export

all: build export page test-fast

help:
	@echo "make build        mine changed works, place new ones, draw lanes ($(CORPUS))"
	@echo "make report       what needs a decision, most urgent first ($(DATA)/report.md)"
	@echo "make export       split export for the page and the terminal ($(EXPORT)/)"
	@echo "make page         site/cutaway-reader.html plus site/works/ (publish them together)"
	@echo "make standalone   dist/cutaway/ with every file vendored, strict CSP"
	@echo "make check        the graph oracle for every work and the corpus"
	@echo "make tty          read in the terminal"
	@echo "make test         every suite, browser included;  make test-fast skips the browser"

build:
	$(PY) corpus.py build $(CORPUS)

report: build
	$(PY) corpus.py report $(DATA)

export: build
	$(PY) corpus.py export $(DATA) $(DATA)/bundle.json
	$(PY) corpus.py export $(DATA) $(EXPORT)

page: export
	rm -rf site/works
	$(PY) build_viewer.py artifact $(EXPORT) - site/cutaway-reader.html

standalone: export
	rm -rf dist/cutaway
	$(PY) build_viewer.py standalone $(EXPORT) - dist/cutaway

check: export
	@node cutaway-tty.js --check $(EXPORT) || echo "(the oracle exits non-zero when a work or chamber cannot be reached: see above; make report shows how to join them)"

tty: export
	node cutaway-tty.js $(EXPORT)

test:
	$(PY) test_all.py

test-fast:
	$(PY) test_all.py --fast

clean-export:
	rm -rf $(EXPORT) site/works dist/cutaway
