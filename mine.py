#!/usr/bin/env python3
"""
mine.py: LaTeX work -> semantic graph + append-only spatial ledger.

Edges: sequence links consecutive main-passage chambers; branch links each off-axis section to the
passage chamber it hangs from; shaft descends from the last passage chamber into the appendices.
Traversability: every \\ref, sequence, branch, shaft and alcove edge is a two-way tunnel. The graph keeps
citation direction (from = citing, to = cited); only continue= exits are one-way.

Two artifacts per work:
  <work>.graph.json   meaning: units, roles, references, prerequisites, threads, exits.
                      Recomputed from source on every run.
  <work>.ledger.json  remembered location: stable IDs, chamber positions, radii, status.
                      Append-only. Existing positions are never recomputed.

Fixed axes (identical in every level):
  +Z  main reading passage (forward)
  -Y  foundation (prerequisites, definitions, formal apparatus); appendices form a shaft below
  +Y  consequence (applications, extensions)
  +-X comparison (objections, parallels, contrasts)

Source directives (LaTeX comments, apply to the current section/subsection):
  % mine: thesis                 mark the reactor chamber
  % mine: role=foundation        override role (main|foundation|consequence|comparison)
  % mine: exit=<work-id>         exit door to another work (two-way)
  % mine: continue=<work-id>     authorial "continue elsewhere" exit (one-way)
  % thread[kind]: text           open thread; kind in missing|extension|evidence|open
  \\todo{...}                    counts as a 'missing' thread

Usage:
  python3 mine.py essay.tex [--work ID] [--out DIR]
"""
import argparse, datetime, hashlib, json, math, re, sys, unicodedata
from pathlib import Path

SPACING = 40.0
GAP = 6.0
MAX_CHAMBERS = 20
AXES = {
    "main": (0, 0, 1), "foundation": (0, -1, 0), "consequence": (0, 1, 0),
    "comparison": (1, 0, 0), "appendix": (0, -1, 0),
}
ROLE_HINTS = [
    ("foundation", r"prelim|definition|background|formal|setup|notation|axiom|framework"),
    ("consequence", r"application|extension|implication|consequence|outlook|future work"),
    ("comparison", r"objection|comparison|contrast|alternative|versus|\bvs\b|critique|reply"),
]
THREAD_KINDS = {"missing", "extension", "evidence", "open"}
HEADINGS = {"part", "chapter", "section", "subsection", "subsubsection"}
TOK = re.compile(r"\\(part|chapter|section|subsection|subsubsection|appendix|label|ref|cref|Cref|autoref|eqref|"
                 r"cite|citep|citet|parencite|textcite|autocite|footcite|includegraphics|todo)(?![A-Za-z])(\*?)")
DIRECTIVE = re.compile(r"^\s*%+\s*mine:\s*(.*)$")
THREAD = re.compile(r"^\s*%+\s*thread\[(\w+)\]:\s*(.*)$")
MATH_ENVS = r"equation|equation\*|align|align\*|gather|gather\*|multline|multline\*|eqnarray|eqnarray\*|displaymath|math"
THEOREM_ENVS = {"theorem", "proposition", "lemma", "corollary", "definition", "remark", "example", "conjecture",
                "claim", "proof", "axiom", "principle", "hypothesis", "observation"}
BACK_MATTER = re.compile(r"^\s*(bibliography|references|works cited|index)\b", re.I)
MATH_MARK = "@@MATH@@"


# ---------- small vector helpers ----------
def add(a, b): return [a[i] + b[i] for i in range(3)]
def scale(a, s): return [a[i] * s for i in range(3)]
def dist(a, b): return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "untitled"


def read_arg(s, i):
    """Return the balanced {...} argument after an optional [...]."""
    n = len(s)
    while i < n and s[i] == " ":
        i += 1
    if i < n and s[i] == "[":
        j = s.find("]", i)
        if j < 0:
            return None
        i = j + 1
        while i < n and s[i] == " ":
            i += 1
    if i < n and s[i] == "{":
        depth = 0
        for j in range(i, n):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    return s[i + 1:j]
    return None


def arg_span(s, i):
    """(content, end) of the balanced {...} starting at or after i, or (None, i)."""
    n = len(s)
    while i < n and s[i] in " \n\t":
        i += 1
    if i >= n or s[i] != "{":
        return None, i
    depth = 0
    for j in range(i, n):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
    return None, i


def replace_cmd(s, name, nargs, fn):
    """Replace \\name{a1}...{an} (balanced) by fn(args)."""
    out, i, pat = [], 0, re.compile(r"\\" + re.escape(name) + r"(?![A-Za-z])")
    while True:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:])
            return "".join(out)
        args, j = [], m.end()
        for _ in range(nargs):
            a, j2 = arg_span(s, j)
            if a is None:
                break
            args.append(a)
            j = j2
        if len(args) < nargs:
            out.append(s[i:m.end()])
            i = m.end()
            continue
        out.append(s[i:m.start()])
        out.append(fn(args))
        i = j


def normalise(s):
    """Typesetting that should read as text: \\texorpdfstring{tex}{text} -> text, $|$ -> |, thin spaces."""
    s = replace_cmd(s, "texorpdfstring", 2, lambda a: a[1])
    s = re.sub(r"(\\,)?\$\|\$(\\,)?", "|", s)  # MEM\,$|$\,8 -> MEM|8
    s = s.replace("$|$", "|").replace("\\,", " ").replace("\;", " ").replace("\\ ", " ").replace("\\\\", " ")
    s = re.sub(r"\\([_&#%])", r"\1", s).replace("\\!", "").replace("\\|", "\u2016")
    marks = {"'": "\u0301", '"': "\u0308", "`": "\u0300", "^": "\u0302", "~": "\u0303", "H": "\u030b", "c": "\u0327", "v": "\u030c"}
    s = re.sub(r"\\(['\"`^~]|[Hcv](?=\{|\s))\s*\{?([A-Za-z])\}?",
               lambda m: unicodedata.normalize("NFC", m.group(2) + marks[m.group(1)]), s)
    s = s.replace("---", "\u2014").replace("--", "\u2013").replace("``", "\u201c").replace("''", "\u201d")
    return s


def clean(s):
    s = normalise(s)
    s = re.sub(r"\\(?:[vh]space\*?|color|textcolor(?=\{[^}]*\}\{))\s*\{[^}]*\}", " ", s)
    s = re.sub(r"\\\\\*?(\[[^\]]*\])?", " ", s)
    s = re.sub(r"\\[A-Za-z]+\*?", "", s)
    return re.sub(r"\s+", " ", s.replace("{", "").replace("}", "").replace("$", "")).strip()


def inline_math(m):
    """$...$ read aloud-ish: keep symbols and sub/superscripts, drop the markup."""
    t = replace_cmd(m.group(1), "frac", 2, lambda a: f"({a[0]})/({a[1]})")
    t = re.sub(r"\\(mathcal|mathrm|mathbf|mathbb|operatorname|text|textrm|mathit|widehat|hat|bar|tilde|boldsymbol)\s*", "", t)
    greek = "alpha beta gamma delta epsilon varepsilon zeta eta theta lambda mu nu xi pi rho sigma tau phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Phi Psi Omega".split()
    for g in greek:
        t = re.sub(r"\\" + g + r"(?![A-Za-z])", {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
            "zeta": "ζ", "eta": "η", "theta": "θ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ",
            "tau": "τ", "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ",
            "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω"}[g], t)
    sym = {r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\to": "→", r"\rightarrow": "→", r"\infty": "∞", r"\in": "∈", r"\subseteq": "⊆",
           r"\times": "×", r"\sim": "~", r"\approx": "≈", r"\cdot": "·", r"\mid": "|", r"\propto": "∝", r"\oplus": "⊕", r"\ll": "≪", r"\gg": "≫"}
    for k, v in sorted(sym.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(re.escape(k) + r"(?![A-Za-z])", v, t)
    t = re.sub(r"\\[A-Za-z]+\*?", "", t).replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", t).strip()


def preamble_macros(pre):
    """Zero-argument macros from the preamble (\\newcommand{\\Pop}{\\textsc{Pop}} -> 'Pop')."""
    macros = {}
    for m in re.finditer(r"\\(?:re)?(?:newcommand|providecommand)\*?\s*\{?\\([A-Za-z]+)\}?\s*(\[\d+\])?", pre):
        if m.group(2) and m.group(2) != "[0]":
            continue
        body, _ = arg_span(pre, m.end())
        if body is not None:
            macros[m.group(1)] = body
    for m in re.finditer(r"\\DeclareMathOperator\*?\s*\{\\([A-Za-z]+)\}", pre):
        body, _ = arg_span(pre, m.end())
        if body is not None:
            macros[m.group(1)] = body
    return {k: clean(v) for k, v in macros.items() if "#" not in v}


def title_lines(body):
    """A \\title body -> 'Title: Subtitle'. Lines break at \\\\ outside braces; a break inside a group
    is only typography. A third line (a sub-subtitle) is dropped."""
    segs, depth, cur, i = [], 0, "", 0
    while i < len(body):
        c = body[i]
        if c == "\\" and body.startswith("\\\\", i) and depth == 0:
            segs.append(cur); cur = ""
            i += 2
            if i < len(body) and body[i] == "*": i += 1
            m = re.match(r"\s*\[[^\]]*\]", body[i:])
            if m: i += m.end()
            continue
        if c == "\\":
            cur += body[i:i + 2]; i += 2; continue
        depth += (c == "{") - (c == "}")
        cur += c; i += 1
    segs = [x for x in (clean(x) for x in segs + [cur]) if x][:2]
    out = ""
    for x in segs:
        out = x if not out else out + (" " if out.endswith(":") else ": ") + x
    return out or None


def title_of(text):
    """\\title{...}, else the largest lines of a titlepage (book-style documents)."""
    m = re.search(r"\\title\s*(?:\[[^\]]*\])?\{", text)
    if m:
        body, _ = arg_span(text, m.end() - 1)
        if body:
            return title_lines(body)
    tp = re.search(r"\\begin\{titlepage\}(.*?)\\end\{titlepage\}", text, re.S)
    if tp:
        sized = [clean(x) for x in re.findall(r"\{\\(?:Huge|huge|LARGE|Large)\b(?:\\bfseries|\\itshape|\s)*(.*?)\\par\}", tp.group(1), re.S)]
        sized = [x for x in sized if x]
        if sized:
            return ": ".join(sized[:2])
    return None


def bibliography(body):
    """Pull thebibliography out of the body; return (body without it, {key: entry})."""
    bib = {}
    def take(m):
        for item in re.split(r"\\bibitem", m.group(1))[1:]:
            km = re.match(r"\s*(?:\[[^\]]*\])?\{([^}]*)\}(.*)", item, re.S)
            if not km:
                continue
            raw = km.group(2)
            # a quoted title ("Title," in \emph{Venue}) is the title; otherwise the first emphasis is
            q = re.search(r"(?:``|\u201c)(.+?)(?:''|\u201d)", raw, re.S)
            em = re.search(r"\\(?:emph|textit)\{", raw)
            t = None
            if q:
                t = q.group(1).strip().rstrip(",.")
            elif em:
                t, _ = arg_span(raw, em.end() - 1)
            text = clean(re.sub(r"\\href\{[^}]*\}", "", raw))
            bib[km.group(1).strip()] = {"text": text[:400], "title": clean(t) if t else None,
                                        "flyxion": bool(re.match(r"\s*Flyxion\b", text))}
        return "\n"
    body = re.sub(r"\\begin\{thebibliography\}(?:\{[^}]*\})?(.*?)\\end\{thebibliography\}", take, body, flags=re.S)
    return body, bib


LAYOUT = {"addcontentsline": 3, "markboth": 2, "markright": 1, "thispagestyle": 1, "pagestyle": 1,
          "setcounter": 2, "addtocounter": 2, "setlength": 2, "addtolength": 2, "vspace": 1, "hspace": 1,
          "vspace*": 1, "hspace*": 1, "enlargethispage": 1, "pagenumbering": 1}


def bib_file(text):
    """BibTeX entries -> {key: entry}, in the same shape as thebibliography entries."""
    out = {}
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        if m.group(1).lower() in ("comment", "string", "preamble"):
            continue
        body, _ = arg_span(text, text.index("{", m.start()))
        if body is None:
            continue
        fields = {}
        for f in re.finditer(r"(\w+)\s*=\s*", body):
            j = f.end()
            if j < len(body) and body[j] == "{":
                v, _ = arg_span(body, j)
            elif j < len(body) and body[j] == '"':
                k = body.find('"', j + 1)
                v = body[j + 1:k] if k > 0 else None
            else:
                v = re.match(r"[^,\s}]*", body[j:]).group(0)
            if v is not None:
                fields.setdefault(f.group(1).lower(), clean(v))
        author, title = fields.get("author", ""), fields.get("title")
        text_ = ", ".join(x for x in (author, title, fields.get("year")) if x)
        out[m.group(2)] = {"text": text_[:400], "title": title,
                           "flyxion": bool(re.search(r"\bFlyxion\b", author))}
    return out


def load_source(tex_path):
    """The main file with \\input/\\include expanded relative to its folder, and any .bib it names.
    Returns (text, files used, bib entries from .bib files, missing names). A work spread over
    several files is still one work; its edition identity covers every file that was read."""
    tex_path = Path(tex_path)
    root, files, missing = tex_path.parent, [tex_path], []

    def resolve(name):
        for cand in (root / name, root / (name + ".tex")):
            if cand.is_file():
                return cand
        return None

    def expand(text, depth):
        lines = []
        for line in text.splitlines():
            c = re.search(r"(?<!\\)%", line)
            code, rest = (line[:c.start()], line[c.start():]) if c else (line, "")
            def sub(m):
                p = resolve(m.group(2).strip())
                if p is None or depth > 8:
                    missing.append(m.group(2).strip())
                    return ""
                if p not in files:
                    files.append(p)
                return "\n" + expand(p.read_text(encoding="utf-8"), depth + 1) + "\n"
            lines.append(re.sub(r"\\(input|include)\s*\{([^}]*)\}", sub, code) + rest)
        return "\n".join(lines)

    text = expand(tex_path.read_text(encoding="utf-8"), 0)
    bib = {}
    names = []
    for m in re.finditer(r"^[^%\n]*\\(?:bibliography|addbibresource)\s*(?:\[[^\]]*\])?\{([^}]*)\}", text, re.M):
        names += [n.strip() for n in m.group(1).split(",") if n.strip()]
    for n in names:
        p = next((c for c in (root / n, root / (n + ".bib")) if c.is_file()), None)
        if p is None:
            missing.append(n)
            continue
        files.append(p)
        bib.update(bib_file(p.read_text(encoding="utf-8")))
    return text, files, bib, missing


def source_sha256(tex_path):
    """Edition identity: the file's hash when it stands alone; otherwise a hash over every file read."""
    _, files, _, _ = load_source(tex_path)
    if len(files) == 1:
        return hashlib.sha256(files[0].read_bytes()).hexdigest()
    root = Path(tex_path).parent
    h = hashlib.sha256()
    for f in sorted(files, key=lambda p: str(p.relative_to(root))):
        h.update(str(f.relative_to(root)).encode() + b"\0" + hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def preprocess(text):
    """Turn a real LaTeX document into lines the unit parser can walk:
    comments dropped (directives kept), macros expanded, titlepage and bibliography lifted out,
    display math collapsed to a marker line that keeps its labels."""
    pre, body = (text.split("\\begin{document}", 1) + [""])[:2] if "\\begin{document}" in text else ("", text)
    body = body.split("\\end{document}", 1)[0]
    kept = []
    for line in body.splitlines():
        if DIRECTIVE.match(line) or THREAD.match(line):
            kept.append(line)
        else:
            kept.append(re.sub(r"(?<!\\)%.*$", "", line))
    body = "\n".join(kept)
    body = re.sub(r"\\begin\{titlepage\}.*?\\end\{titlepage\}", "", body, flags=re.S)
    body, bib = bibliography(body)
    for name, n in LAYOUT.items():  # page furniture that carries no reading text
        body = replace_cmd(body, name, n, lambda a: "")
    for name, val in preamble_macros(pre).items():
        body = re.sub(r"\\" + name + r"(?![A-Za-z])\s?", lambda _: val + " ", body)
    body = normalise(body)
    def math_block(m):
        labels = " ".join(f"\\label{{{x}}}" for x in re.findall(r"\\label\{([^}]*)\}", m.group(0)))
        return f"\n{MATH_MARK} {labels}\n"
    body = re.sub(r"\\begin\{(" + MATH_ENVS + r")\}.*?\\end\{\1\}", math_block, body, flags=re.S)
    body = re.sub(r"\\\[.*?\\\]", math_block, body, flags=re.S)
    body = re.sub(r"\$\$.*?\$\$", math_block, body, flags=re.S)
    return body, bib


def reading_text(code):
    """Plain prose for the reading station: headings, labels and figures dropped,
    references kept as a visible marker, math and theorem-like environments made legible."""
    if re.match(r"\s*\\(part|chapter|section|subsection|subsubsection|appendix|label|includegraphics)\b", code):
        return ""
    if code.strip().startswith(MATH_MARK):
        return "[equation]"
    code = code.replace("\\{", "\x01").replace("\\}", "\x02")  # literal braces (sets, code) survive
    t = re.sub(r"\\(label|includegraphics|todo)\*?(\[[^\]]*\])?\{[^}]*\}", "", code)
    t = re.sub(r"~?\\(ref|cref|Cref|autoref|eqref)\{([^}]*)\}", r" [\2]", t)
    t = re.sub(r"\\(?:paren|text|auto|foot)?cite[pt]?(\[[^\]]*\])*\{([^}]*)\}", r"(\2)", t)
    def env_open(m):
        name, opt = m.group(1), m.group(2)
        if name.rstrip("*") in THEOREM_ENVS:
            label = (opt[1:-1] if opt else name.rstrip("*").capitalize() if name != "proof" else "Proof")
            return (name.rstrip("*").capitalize() + " (" + opt[1:-1] + "). ") if opt and name != "proof" else label + ". "
        return ""
    t = re.sub(r"\\begin\{([A-Za-z*]+)\}(\[[^\]]*\])?(\{[^}]*\})?", env_open, t)
    t = re.sub(r"\\end\{[A-Za-z*]+\}", "", t)
    t = re.sub(r"\$([^$]+)\$", inline_math, t)
    t = re.sub(r"\\[A-Za-z]+\*?", "", t).replace("{", "").replace("}", "").replace("~", " ")
    return re.sub(r"\s+", " ", t).strip().replace("\x01", "{").replace("\x02", "}")


# ---------- parsing ----------
def parse(text):
    body, bib = preprocess(text)
    has_chapter = re.search(r"\\chapter\*?\s*\{", body) is not None
    # the document's own top level becomes a chamber, the next an alcove; deeper headings stay in the prose
    LEVEL = ({"chapter": "section", "section": "subsection"} if has_chapter else {"section": "section", "subsection": "subsection"})
    units, cur, sec, part, appendix, since, skipping = [], None, None, None, False, 99, False
    for line in body.splitlines():
        m = DIRECTIVE.match(line)
        if m:
            if cur is not None:
                for tok in m.group(1).split():
                    if tok == "thesis":
                        cur["thesis"] = True
                    elif tok.startswith("role="):
                        cur["role"] = tok[5:]
                    elif tok.startswith("exit="):
                        cur["exits"].append((tok[5:], "two-way"))
                    elif tok.startswith("continue="):
                        cur["exits"].append((tok[9:], "one-way"))
            continue
        m = THREAD.match(line)
        if m:
            if cur is not None:
                kind = m.group(1) if m.group(1) in THREAD_KINDS else "open"
                cur["threads"].append({"kind": kind, "text": m.group(2).strip()})
            continue
        code = line
        since += 1
        inline_heading = None
        for t in TOK.finditer(code):
            name, starred = t.group(1), bool(t.group(2))
            if name == "appendix":
                appendix = True
                continue
            arg = read_arg(code, t.end())
            if name in HEADINGS:
                if arg is None:
                    continue
                title = clean(arg)
                if name == "part":
                    part = title
                    continue
                level = LEVEL.get(name)
                if level is None:  # a heading deeper than an alcove: keep it as a line of prose
                    inline_heading = title
                    continue
                if starred and BACK_MATTER.match(title):  # bibliographies and indexes are not chambers
                    skipping, cur = True, None
                    continue
                skipping = False
                u = {"level": level, "heading": name, "title": title, "label": None, "labels": [],
                     "role": None, "thesis": False, "words": 0, "refs": [], "cites": [],
                     "image": None, "threads": [], "exits": [], "appendix": appendix,
                     "part": part, "parent": None, "order": len(units), "paras": [[]]}
                if level == "subsection":
                    u["parent"] = sec["order"] if sec else None
                else:
                    sec = u
                units.append(u)
                cur, since = u, 0
            elif cur is None or arg is None or skipping:
                continue
            elif name == "label":
                lab = arg.strip()
                cur["labels"].append(lab)
                if cur["label"] is None and since <= 2:
                    cur["label"] = lab
            elif name in ("ref", "cref", "Cref", "autoref", "eqref"):
                cur["refs"] += [a.strip() for a in arg.split(",") if a.strip()]
            elif "cite" in name:
                cur["cites"] += [a.strip() for a in arg.split(",") if a.strip()]
            elif name == "includegraphics":
                cur["image"] = cur["image"] or arg.strip()
            elif name == "todo":
                cur["threads"].append({"kind": "missing", "text": clean(arg)})
        if cur is not None and not skipping:
            if inline_heading:
                if cur["paras"][-1]:
                    cur["paras"].append([])
                cur["paras"][-1].append("\u00a7 " + inline_heading)
                cur["paras"].append([])
                continue
            plain = re.sub(r"\\[A-Za-z]+\*?(\[[^\]]*\])?", "", code.replace(MATH_MARK, ""))
            cur["words"] += len(re.findall(r"[A-Za-z]{2,}", plain))
            prose = reading_text(code)
            if prose == "[equation]":
                if cur["paras"][-1] and cur["paras"][-1][-1] == "[equation]":
                    continue
                cur["paras"][-1].append(prose)
            elif prose:
                cur["paras"][-1].append(prose)
            elif not code.strip() and cur["paras"][-1]:
                cur["paras"].append([])
    parse.bibliography = bib
    return units


def infer_role(u):
    if u["level"] == "subsection":
        return "alcove"
    if u["appendix"]:
        return "appendix"
    if u["role"] in AXES:
        return u["role"]
    for role, pat in ROLE_HINTS:
        if re.search(pat, u["title"], re.I):
            return role
    return "main"


def radius_for(u):
    base = 3.0 if u["level"] == "subsection" else 5.0
    return round(min(base + 2.0 * math.sqrt(u["words"] / 100.0), 14.0), 2)


# ---------- stable identity ----------
def assign_ids(units, ledger):
    labels = ledger.setdefault("labels", {})
    aliases = ledger.setdefault("aliases", {})
    seen_count, used = {}, set()
    for u in units:
        parent_id = units[u["parent"]]["id"] if u["parent"] is not None else ""
        key = f'{u["level"]}|{parent_id}|{slug(u["title"])}'
        n = seen_count.get(key, 0)
        seen_count[key] = n + 1
        uid = None
        if u["label"] and u["label"] in labels:
            uid = labels[u["label"]]                      # label wins: survives renames
        elif key in aliases and n < len(aliases[key]):
            uid = aliases[key][n]                         # same title, same occurrence
        if uid is None or uid in used:
            base = ("L:" + u["label"]) if u["label"] else ("G:" + slug(u["title"]))
            uid, k = base, 2
            while uid in used or uid in ledger["nodes"]:
                uid, k = f"{base}-{k}", k + 1
            aliases.setdefault(key, []).append(uid)
        if u["label"]:
            labels.setdefault(u["label"], uid)
        used.add(uid)
        u["id"] = uid


# ---------- append-only embedding ----------
def perpendiculars(d):
    """Fallback offsets, ordered so a displaced chamber keeps its meaning:
    sliding along the passage (Z) or sideways (X) is harmless, while drifting
    in Y would read as foundation/consequence, so Y is tried last."""
    axes = [(0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]
    if abs(d[2]) > 0.9:  # travelling along the passage: go sideways before vertical
        axes = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]
    return [a for a in axes if abs(sum(a[i] * d[i] for i in range(3))) < 1e-9]


def is_free(pos, r, nodes):
    return all(dist(pos, n["pos"]) >= r + n["radius"] + GAP for n in nodes.values())


def dig(anchor, direction, r, step, nodes):
    base = add(anchor, scale(direction, step))
    if is_free(base, r, nodes):
        return base
    # an inserted chamber first tries to sit inside the existing gap, on-axis
    for f in (0.5, 0.33, 0.67):
        c = add(anchor, scale(direction, step * f))
        if is_free(c, r, nodes):
            return c
    for ring in range(1, 16):
        for p in perpendiculars(direction):
            c = add(base, scale(p, ring * step * 0.5))
            if is_free(c, r, nodes):
                return c
        c = add(anchor, scale(direction, step * (1 + ring * 0.5)))
        if is_free(c, r, nodes):
            return c
    return base


def embed(units, ledger, now):
    nodes = ledger["nodes"]
    for n in nodes.values():
        n["status_prev"] = n.get("status")
    added, extended = [], []
    prev_sec = prev_main = prev_app = last_body = None
    for u in units:
        role, r = u["role_final"], radius_for(u)
        if u["id"] in nodes:
            n = nodes[u["id"]]
            if r > n["radius"]:
                extended.append(u["id"])
            n.update(radius=max(n["radius"], r), title=u["title"], role=role,
                     status="active", last_seen=now)
        else:
            if role == "alcove":
                parent = units[u["parent"]]["id"] if u["parent"] is not None else None
                if parent and parent in nodes:
                    # alcoves stay level (XZ plane) so they never read as foundation/consequence
                    k = sum(1 for x in nodes.values() if x.get("parent") == parent)
                    ang = [0, 180, 35, 145, -35, -145][k % 6] * math.pi / 180
                    d = (math.cos(ang), 0, math.sin(ang))
                    pos = dig(nodes[parent]["pos"], d, r, nodes[parent]["radius"] + r + 3, nodes)
                else:
                    pos = dig([0, 0, 0], (1, 0, 0), r, SPACING / 2, nodes)
            elif role == "appendix":
                anchor = nodes[prev_app]["pos"] if prev_app else \
                    (nodes[last_body]["pos"] if last_body else [0, 0, 0])
                pos = dig(anchor, AXES["appendix"], r, SPACING, nodes)
            elif role == "main":
                anchor = nodes[prev_main]["pos"] if prev_main else \
                    (nodes[prev_sec]["pos"] if prev_sec else None)
                pos = [0.0, 0.0, 0.0] if anchor is None and not nodes else \
                    dig(anchor or [0, 0, 0], AXES["main"], r, SPACING, nodes)
            else:
                # off-axis chambers hang from the main-passage chamber they belong to,
                # so the passage itself stays clear
                anchor = nodes[prev_main]["pos"] if prev_main else \
                    (nodes[prev_sec]["pos"] if prev_sec else [0, 0, 0])
                d = AXES[role]
                if role == "comparison":  # take whichever side of the passage is open
                    d = next((s for s in ((1, 0, 0), (-1, 0, 0))
                              if is_free(add(anchor, scale(s, SPACING)), r, nodes)), (1, 0, 0))
                pos = dig(anchor, d, r, SPACING, nodes)
            nodes[u["id"]] = {
                "pos": [round(c, 2) for c in pos], "radius": r, "title": u["title"],
                "role": role, "level": u["level"],
                "parent": units[u["parent"]]["id"] if u["parent"] is not None else None,
                "status": "active", "first_seen": now, "last_seen": now,
            }
            added.append(u["id"])
        if u["level"] == "section":
            if role == "appendix":
                prev_app = u["id"]
            else:
                prev_sec = last_body = u["id"]
                if role == "main":
                    prev_main = u["id"]
    live = {u["id"] for u in units}
    withdrawn = []
    for nid, n in nodes.items():
        if nid not in live and n["status"] == "active":
            n["status"] = "withdrawn"
            withdrawn.append(nid)
        n.pop("status_prev", None)
    return added, extended, withdrawn


# ---------- semantic graph ----------
def build_graph(units, work):
    label_owner = {}
    for u in units:
        for lab in u["labels"]:
            label_owner.setdefault(lab, u["id"])
    by_id = {u["id"]: u for u in units}
    edges = []
    body = [u for u in units if u["level"] == "section" and not u["appendix"]]
    apps = [u for u in units if u["level"] == "section" and u["appendix"]]
    mains = [u for u in body if u["role_final"] == "main"]
    # the reading passage runs straight through main-passage chambers only
    for a, b in zip(mains, mains[1:]):
        edges.append({"from": a["id"], "to": b["id"], "kind": "sequence", "traversal": "two-way"})
    # off-axis sections branch from the passage chamber they hang from (the one before them)
    for u in body:
        if u["role_final"] == "main":
            continue
        before = [x for x in mains if x["order"] < u["order"]]
        anchor = before[-1] if before else (mains[0] if mains else None)
        if anchor:
            edges.append({"from": anchor["id"], "to": u["id"], "kind": "branch", "traversal": "two-way"})
    if body and apps:
        last = mains[-1] if mains else body[-1]
        edges.append({"from": last["id"], "to": apps[0]["id"], "kind": "shaft",
                      "traversal": "two-way"})
    for a, b in zip(apps, apps[1:]):
        edges.append({"from": a["id"], "to": b["id"], "kind": "shaft", "traversal": "two-way"})
    for u in units:
        if u["parent"] is not None:
            edges.append({"from": units[u["parent"]]["id"], "to": u["id"], "kind": "alcove",
                          "traversal": "two-way"})
        for ref in dict.fromkeys(u["refs"]):
            tgt = label_owner.get(ref)
            if tgt and tgt != u["id"]:
                kind = "prerequisite" if by_id[tgt]["role_final"] == "foundation" else "reference"
                # direction is semantic (citing -> cited); the tunnel is physically two-way
                edges.append({"from": u["id"], "to": tgt, "kind": kind, "label": ref,
                              "door": kind == "prerequisite", "traversal": "two-way"})
        for ex, trav in u["exits"]:
            edges.append({"from": u["id"], "to": "work:" + ex, "kind": "exit", "traversal": trav})
    nodes = [{
        "id": u["id"], "title": u["title"], "level": u["level"], "heading": u.get("heading", u["level"]), "role": u["role_final"],
        "thesis": u["thesis"], "part": u["part"], "words": u["words"], "image": u["image"],
        "threads": u["threads"], "cites": sorted(set(u["cites"])), "order": u["order"],
        "text": [" ".join(p) for p in u["paras"] if p],
    } for u in units]
    return {"work": work, "nodes": nodes, "edges": edges}


def warnings_for(units):
    """Structured notes on a mined work. 'problem': something is missing or broken and the reader shows less
    than the source holds. 'advice': the work reads fine; this would make it sturdier."""
    w = []
    note = lambda kind, sev, text, **kw: w.append({"kind": kind, "severity": sev, "text": text, **kw})
    if not any(u["thesis"] for u in units):
        note("no-thesis", "advice", "no thesis chamber marked (add '% mine: thesis' under the central section)")
    per_part = {}
    for u in units:
        if u["level"] == "section":
            per_part[u["part"]] = per_part.get(u["part"], 0) + 1
    for p, c in per_part.items():
        if c > MAX_CHAMBERS:
            note("large-part", "advice", f"{c} chambers in part '{p or '(none)'}' exceeds {MAX_CHAMBERS}; split by \\part",
                 part=p, chambers=c)
    secs = [u for u in units if u["level"] == "section"]
    bare = [u["title"] for u in secs if not u["label"]]
    if bare:
        note("unlabeled", "advice", f"{len(bare)} of {len(secs)} chambers have no \\label; their identity follows their "
             f"headings, so a renamed heading is dug as a new chamber", titles=bare)
    empty = [u["title"] for u in secs if not u["words"] and not any(v["parent"] == units.index(u) for v in units)]
    if empty:
        note("empty", "problem", f"{len(empty)} chambers have no text and no alcoves: {', '.join(empty[:5])}", titles=empty)
    return w


# ---------- preview ----------
COLORS = {"main": "#3fb950", "foundation": "#58a6ff", "consequence": "#d29922",
          "comparison": "#bc8cff", "appendix": "#1f6feb", "alcove": "#7d8590"}


def preview_svg(graph, ledger):
    nodes = ledger["nodes"]
    pts = [n["pos"] for n in nodes.values()]
    if not pts:
        return "<svg xmlns='http://www.w3.org/2000/svg'/>"
    W, H, pad = 520, 420, 50

    def panel(ax_h, ax_v, flip_v, ox, title):
        hs = [p[ax_h] for p in pts]; vs = [p[ax_v] for p in pts]
        span = max(max(hs) - min(hs), max(vs) - min(vs), 1)
        s = (min(W, H) - 2 * pad) / span
        cx, cy = (max(hs) + min(hs)) / 2, (max(vs) + min(vs)) / 2

        def xy(p):
            x = ox + W / 2 + (p[ax_h] - cx) * s
            y = H / 2 + ((cy - p[ax_v]) if flip_v else (p[ax_v] - cy)) * s
            return x, y
        out = [f"<text x='{ox+12}' y='22' fill='#8b949e' font-size='13'>{title}</text>"]
        for e in graph["edges"]:
            if e["from"] in nodes and e["to"] in nodes:
                (x1, y1), (x2, y2) = xy(nodes[e["from"]]["pos"]), xy(nodes[e["to"]]["pos"])
                dash = " stroke-dasharray='4 3'" if e["kind"] in ("reference", "prerequisite") else ""
                col = "#58a6ff" if e["kind"] == "prerequisite" else "#30363d"
                out.append(f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' "
                           f"stroke='{col}' stroke-width='1.5'{dash}/>")
        thesis = {n["id"] for n in graph["nodes"] if n["thesis"]}
        for nid, n in nodes.items():
            x, y = xy(n["pos"])
            r = max(n["radius"] * s, 3)
            col = COLORS.get(n["role"], "#8b949e")
            if n["status"] == "withdrawn":
                out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r:.1f}' fill='none' "
                           f"stroke='#6e7681' stroke-dasharray='3 3'/>")
            else:
                out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r:.1f}' fill='{col}' "
                           f"fill-opacity='0.35' stroke='{col}'/>")
            if nid in thesis:
                out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r+5:.1f}' fill='none' "
                           f"stroke='#f85149' stroke-width='2'/>")
            if n["level"] == "section":
                out.append(f"<text x='{x:.1f}' y='{y - r - 4:.1f}' fill='#c9d1d9' font-size='9' "
                           f"text-anchor='middle'>{n['title'][:22]}</text>")
        return "".join(out)

    body = panel(2, 1, True, 0, "Side: Z forward, Y up") + \
        panel(2, 0, False, W, "Plan: Z forward, X across")
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{2*W}' height='{H}' "
            f"font-family='monospace'><rect width='100%' height='100%' fill='#0d1117'/>{body}</svg>")


# ---------- main ----------
MINER = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]  # a changed miner re-mines everything


def is_current(tex_path, work, out):
    """True when out/<work>.graph.json was mined from exactly this source by exactly this miner."""
    p = Path(out) / f"{work}.graph.json"
    if not p.exists() or not (Path(out) / f"{work}.ledger.json").exists():
        return False
    try:
        g = json.loads(p.read_text())
    except ValueError:
        return False
    return g.get("miner") == MINER and g.get("source_sha256") == source_sha256(tex_path)

def run(tex_path, work=None, out=None, quiet=False):
    tex_path = Path(tex_path)
    work = work or tex_path.stem
    out = Path(out or tex_path.parent)
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = out / f"{work}.ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else \
        {"work": work, "version": 1, "nodes": {}, "labels": {}, "aliases": {}, "history": []}
    now = datetime.datetime.now().isoformat(timespec="seconds")

    source, files, bibfile, missing = load_source(tex_path)
    units = parse(source)
    for u in units:
        u["role_final"] = infer_role(u)
    assign_ids(units, ledger)
    added, extended, withdrawn = embed(units, ledger, now)
    graph = build_graph(units, work)
    graph["title"] = title_of(source)
    graph["bibliography"] = {**bibfile, **parse.bibliography}
    graph["sources"] = [str(f.relative_to(tex_path.parent)) for f in files]
    warns = warnings_for(units) + [{"kind": "missing-file", "severity": "problem",
                                    "text": f"source names a file that is not here: {m}", "file": m} for m in missing]
    graph["warnings"] = warns
    graph["source_sha256"] = source_sha256(tex_path)
    graph["miner"] = MINER
    ledger["history"].append({"at": now, "added": added, "extended": extended,
                              "withdrawn": withdrawn})

    (out / f"{work}.graph.json").write_text(json.dumps(graph, indent=2))
    ledger_path.write_text(json.dumps(ledger, indent=2))
    (out / f"{work}.preview.svg").write_text(preview_svg(graph, ledger))
    if not quiet:
        print(f"{work}: {len(units)} units, +{len(added)} dug, "
              f"{len(extended)} extended, {len(withdrawn)} withdrawn")
        for w in warns:
            print(f"  {w['severity']}: {w['text']}")
    return graph, ledger


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tex")
    ap.add_argument("--work")
    ap.add_argument("--out")
    a = ap.parse_args()
    run(a.tex, a.work, a.out)
