#!/usr/bin/env python3
"""
build_viewer.py: assemble the Cutaway Reader for one work.

  python3 build_viewer.py artifact   <data_dir> <work-id> <out.html>
  python3 build_viewer.py artifact   <bundle.json> - <out.html>        a whole corpus (corpus.py export DIR x.json)
  python3 build_viewer.py artifact   <export_dir> - <out.html>         a split corpus (corpus.py export DIR folder/):
      the index is inlined and works/<id>.json is written beside out.html, fetched when a reader goes there
      One HTML file for claude.ai artifacts: model inlined, Three.js from cdnjs,
      fonts from Google Fonts (the only hosts that sandbox allows).

  python3 build_viewer.py standalone <data_dir> <work-id> <out_dir> [--vendor DIR]
      Third-party files come from vendor/ (Three.js r128 and five font files), which ships
      with the source and is pinned by SHA-256 in vendor/lock.json. The build refuses to run
      if any file differs; python3 fetch_vendor.py regenerates them from npm.
      A directory for your own hosting with nothing fetched from anywhere else:
      index.html, viewer.css, viewer.js, model.js, three.min.js, fonts/*.woff2.
      No inline script, no inline style, no eval, so it runs under
      Content-Security-Policy: default-src 'self'.
      Level data rides in a <script type="application/json"> block, which is data,
      never executed. Persistence falls back to browser storage when window.claude
      is absent.

The page reads two artifacts written by mine.py: <work>.graph.json and <work>.ledger.json.
"""
import json, re, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "viewer_template.html"
MODEL = HERE / "model.js"
THREE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
FONTS_LINK = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
              '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
              '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=VT323&family=IBM+Plex+Mono:wght@400;500'
              '&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">')
FONT_FILES = [  # (family, weight, file in vendor/, pinned in vendor/lock.json)
    ("VT323", 400, "fonts/vt323-latin-400-normal.woff2"),
    ("IBM Plex Mono", 400, "fonts/ibm-plex-mono-latin-400-normal.woff2"),
    ("IBM Plex Mono", 500, "fonts/ibm-plex-mono-latin-500-normal.woff2"),
    ("Source Serif 4", 400, "fonts/source-serif-4-latin-400-normal.woff2"),
    ("Source Serif 4", 600, "fonts/source-serif-4-latin-600-normal.woff2"),
]


def verify_vendor(vendor):
    """Every third-party byte in a standalone build must match vendor/lock.json."""
    import hashlib
    lock = json.loads((vendor / "lock.json").read_text())
    for p in lock["packages"]:
        for f in p["files"].values():
            path = vendor / f["dest"]
            if not path.exists():
                sys.exit(f"missing {path}: run python3 fetch_vendor.py")
            if hashlib.sha256(path.read_bytes()).hexdigest() != f["sha256"]:
                sys.exit(f"{path} does not match vendor/lock.json: run python3 fetch_vendor.py")


def split_dir(data_dir):
    d = Path(data_dir)
    return d if d.is_dir() and (d / "index.json").exists() else None


def copy_works(data_dir, dest):
    """A split export's work files go beside the page, at the path the index names (works/)."""
    d = split_dir(data_dir)
    if not d:
        return []
    target = Path(dest) / "works"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(d / "works", target)
    return sorted(target.glob("*.json"))


def level_json(data_dir, work):
    """A corpus bundle (corpus.py export DIR x.json) is embedded whole; a split export (corpus.py export DIR folder/)
    embeds only its index and the page fetches works/<id>.json as needed; otherwise one work's graph + ledger."""
    if split_dir(data_dir):
        return json.dumps(json.loads((Path(data_dir) / "index.json").read_text()), separators=(",", ":")).replace("</", "<\\/")
    if str(data_dir).endswith(".json"):
        return json.dumps(json.loads(Path(data_dir).read_text()), separators=(",", ":")).replace("</", "<\\/")
    d = Path(data_dir)
    data = {"graph": json.loads((d / f"{work}.graph.json").read_text()),
            "ledger": json.loads((d / f"{work}.ledger.json").read_text())}
    return json.dumps(data, separators=(",", ":")).replace("</", "<\\/")


def artifact(data_dir, work, out):
    t = TEMPLATE.read_text()
    t = t.replace("<!--FONTS-->", FONTS_LINK)
    t = t.replace("<!--THREE-->", f'<script src="{THREE_CDN}"></script>')
    t = t.replace("<!--MODEL-->", "<script>\n" + MODEL.read_text() + "\n</script>")
    t = t.replace("__LEVEL__", level_json(data_dir, work))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(t)
    works = copy_works(data_dir, Path(out).parent)
    print(out, Path(out).stat().st_size, "bytes" + (f"; {len(works)} work files in {Path(out).parent / 'works'} "
          "(publish them beside the page)" if works else ""))


def standalone(data_dir, work, out_dir, vendor):
    out, vendor = Path(out_dir), Path(vendor)
    verify_vendor(vendor)
    (out / "fonts").mkdir(parents=True, exist_ok=True)
    t = TEMPLATE.read_text()
    css = re.search(r"<style>(.*?)</style>", t, re.S)
    faces = []
    for fam, w, rel in FONT_FILES:
        src = vendor / rel
        shutil.copy(src, out / "fonts" / src.name)
        faces.append(f'@font-face{{font-family:"{fam}";font-style:normal;font-weight:{w};font-display:swap;'
                     f'src:url("fonts/{src.name}") format("woff2")}}')
    (out / "viewer.css").write_text("\n".join(faces) + "\n" + css.group(1).strip() + "\n")
    t = t[:css.start()] + '<link rel="stylesheet" href="viewer.css">' + t[css.end():]
    main = re.search(r"<script>\n\(\(\) => \{.*?\}\)\(\);\n</script>", t, re.S)
    (out / "viewer.js").write_text(main.group(0)[len("<script>\n"):-len("</script>")])
    t = t[:main.start()] + '<script src="viewer.js"></script>' + t[main.end():]
    t = t.replace("<!--FONTS-->", "")
    t = t.replace("<!--THREE-->", '<script src="three.min.js"></script>')
    t = t.replace("<!--MODEL-->", '<script src="model.js"></script>')
    t = t.replace("__LEVEL__", level_json(data_dir, work))
    head = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'self\'; img-src \'self\' data:">')
    title = re.search(r"<title>.*?</title>", t).group(0)
    t = t.replace(title, "", 1)
    (out / "index.html").write_text(head + title + "</head><body>\n" + t + "\n</body></html>\n")
    copy_works(data_dir, out)
    shutil.copy(MODEL, out / "model.js")
    shutil.copy(vendor / "three.min.js", out / "three.min.js")
    leftovers = [x for x in ("<script>", 'style="') if x in (out / "index.html").read_text()]
    if leftovers:
        sys.exit(f"standalone build still contains inline {leftovers}")
    print(out, "standalone:", ", ".join(sorted(p.name for p in out.iterdir())))


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 4 and a[0] == "artifact":
        artifact(a[1], a[2], a[3])
    elif len(a) >= 4 and a[0] == "standalone":
        v = a[a.index("--vendor") + 1] if "--vendor" in a else str(HERE / "vendor")
        standalone(a[1], a[2], a[3], v)
    else:
        sys.exit(__doc__)
