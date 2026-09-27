#!/usr/bin/env python3
"""
Browser-level checks for what the shared model cannot see: the rendered camera.
Builds the standalone reader for the example corpus, opens it headless with the #debug hook, and measures
the camera's forward vector during cruise and after crossing a portal.

  python3 test_viewer.py            (needs: pip install playwright && python3 -m playwright install chromium)
"""
import asyncio, functools, http.server, json, math, subprocess, sys, tempfile, threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:
    from playwright.async_api import async_playwright
except ImportError:
    print("skipped: playwright is not installed"); sys.exit(0)

passed = 0
def check(name, cond, detail=""):
    global passed
    assert cond, f"{name} {detail}"
    passed += 1; print("ok  " + name + (f"  ({detail})" if detail else ""))
unit = lambda v: [x / (math.sqrt(sum(y * y for y in v)) or 1) for x in v]
dot = lambda a, b: sum(x * y for x, y in zip(a, b))

async def split_checks(b, port):
    """The same reader over a split export: the index is in the page, each work is fetched when first needed."""
    pg = await b.new_page(viewport={"width": 1100, "height": 700}); errors, fetched = [], []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("request", lambda r: fetched.append(r.url.split("/works/")[1]) if "/works/" in r.url else None)
    await pg.goto(f"http://127.0.0.1:{port}/index.html#debug"); await pg.wait_for_timeout(1200)
    H = "window.__cutaway."
    st = await pg.evaluate(H + "state()")
    check("a split corpus opens having fetched only the work it starts in", fetched == [st["work"] + ".json"], str(fetched))
    i = next(k for k, d in enumerate(st["portals"]) if d.startswith("next in series"))
    blocked = []
    async def fail(route):
        blocked.append(route.request.url); await route.abort()
    await pg.route("**/works/*.json", fail)
    await pg.evaluate(f"{H}approach({i})"); await pg.wait_for_timeout(900)
    mid = await pg.evaluate(H + "state()")
    toast = await pg.inner_text("#toast")
    check("when a work cannot be fetched the reader stays where it was and says so",
          blocked and mid["work"] == st["work"] and mid["jumps"] == st["jumps"] and "Could not load" in toast, toast)
    await pg.unroute("**/works/*.json")
    await pg.evaluate(f"{H}approach({i})"); await pg.wait_for_timeout(1200)
    after = await pg.evaluate(H + "state()")
    check("flying the same portal again fetches the work and crosses once",
          after["work"] != st["work"] and after["jumps"] == st["jumps"] + 1 and fetched.count(after["work"] + ".json") >= 1)
    n = len(fetched)
    await pg.evaluate(f"{H}approach(" + str(next(k for k, d in enumerate(after["portals"]) if "series" in d)) + ")"); await pg.wait_for_timeout(900)
    check("going back to a work already fetched fetches nothing", len(fetched) == n and (await pg.evaluate(H + "state()"))["work"] == st["work"])
    check("no page errors over a split corpus", not errors, "; ".join(errors[:3]))
    await pg.close()


async def main(site, split_site):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    handler = functools.partial(Quiet, directory=str(site))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
        pg = await b.new_page(viewport={"width": 1100, "height": 700})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        await pg.goto(f"http://127.0.0.1:{srv.server_port}/index.html#debug"); await pg.wait_for_timeout(1200)
        await pg.click("#stage", position={"x": 300, "y": 300})
        H = "window.__cutaway."

        await pg.evaluate(H + "cruise()"); await pg.wait_for_timeout(1600)
        p1 = await pg.evaluate(H + "pos()"); await pg.wait_for_timeout(350)
        p2 = await pg.evaluate(H + "pos()"); f = await pg.evaluate(H + "forward()")
        travel = unit([b_ - a_ for a_, b_ in zip(p1, p2)])
        check("cruise looks where it is going", dot(unit(f), travel) > 0.8, f"cos = {dot(unit(f), travel):.2f}")
        await pg.keyboard.press("KeyX"); await pg.wait_for_timeout(200)

        await pg.reload(); await pg.wait_for_timeout(1200)
        st = await pg.evaluate(H + "state()")
        i = next(k for k, d in enumerate(st["portals"]) if d.startswith("next in series"))
        await pg.evaluate(f"{H}approach({i})"); await pg.wait_for_timeout(900)
        after = await pg.evaluate(H + "state()")
        check("flying through a portal crosses into the other work", after["work"] != st["work"] and after["jumps"] == st["jumps"] + 1)
        pos, f = await pg.evaluate(H + "pos()"), await pg.evaluate(H + "forward()")
        inward = unit([c - x for c, x in zip(await pg.evaluate(H + "centre()"), pos)])
        check("after a portal crossing the camera faces into the arrival chamber", dot(unit(f), inward) > 0.5, f"cos = {dot(unit(f), inward):.2f}")
        check("no page errors", not errors, "; ".join(errors[:3]))
        await touch_checks(b, srv.server_port)
        handler2 = functools.partial(Quiet, directory=str(split_site))
        srv2 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler2)
        threading.Thread(target=srv2.serve_forever, daemon=True).start()
        await split_checks(b, srv2.server_port)
        srv2.shutdown()
        await b.close()
    srv.shutdown()

async def touch_checks(b, port):
    """A phone: coarse pointer, touch events. Drags are sent as real touch sequences through the protocol."""
    ctx = await b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, device_scale_factor=2)
    pg = await ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    cdp = await ctx.new_cdp_session(pg)
    async def touch(kind, pts):
        await cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(pts)]})
    async def drag(a, z, steps=8, hold=0):
        await touch("touchStart", [a])
        for k in range(1, steps + 1):
            await touch("touchMove", [(a[0] + (z[0] - a[0]) * k / steps, a[1] + (z[1] - a[1]) * k / steps)]); await pg.wait_for_timeout(16)
        if hold: await pg.wait_for_timeout(hold)
        await touch("touchEnd", [])
    await pg.goto(f"http://127.0.0.1:{port}/index.html#debug"); await pg.wait_for_timeout(1200)
    H = "window.__cutaway."
    check("a phone opens in flight with touch controls showing",
          await pg.evaluate("matchMedia('(pointer:coarse)').matches && !document.getElementById('mobileControls').hidden")
          and (await pg.evaluate(H + "state()"))["mode"] == "flight")

    box = await pg.evaluate("(()=>{const r=document.getElementById('mobileStick').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()")
    f0, p0 = unit(await pg.evaluate(H + "forward()")), await pg.evaluate(H + "pos()")
    await drag(box, (box[0], box[1] - 60), hold=700)
    moved = [b_ - a_ for a_, b_ in zip(p0, await pg.evaluate(H + "pos()"))]
    check("pushing the stick up flies forward", dot(unit(moved), f0) > 0.8 and math.dist(p0, [a + d for a, d in zip(p0, moved)]) > 2,
          f"cos = {dot(unit(moved), f0):.2f}")

    await pg.wait_for_timeout(600)
    f1 = unit(await pg.evaluate(H + "forward()"))
    await drag((200, 300), (80, 300))
    await pg.wait_for_timeout(100)
    f2 = unit(await pg.evaluate(H + "forward()"))
    turn = math.degrees(math.acos(max(-1, min(1, dot(f1, f2)))))
    check("a drag across the view turns it by about the drag, and it stays turned", 15 < turn < 60, f"{turn:.0f} degrees for 120 px")

    await pg.tap("#mMap"); await pg.wait_for_timeout(200)
    check("MAP opens the map and UP/DOWN become OUT/IN", (await pg.evaluate(H + "state()"))["mode"] == "map"
          and await pg.inner_text("#mUp") == "OUT")
    await pg.tap("#mUp"); await pg.tap("#mUp"); await pg.wait_for_timeout(300)
    st = await pg.evaluate(H + "state()")
    check("OUT twice reaches the galaxy", st["depth"] == 2)
    other = next(w for w in st["works"] if w != st["work"])
    x, y = await pg.evaluate(f"{H}screenOf({json.dumps(other)})")
    sel0 = st["sel"]
    await drag((x, y), (x + 80, y + 40)); await pg.wait_for_timeout(100)
    st2 = await pg.evaluate(H + "state()")
    check("a drag that starts on a star neither selects it nor travels", st2["sel"] == sel0 and st2["work"] == st["work"])
    x, y = await pg.evaluate(f"{H}screenOf({json.dumps(other)})")
    await touch("touchStart", [(x, y)]); await touch("touchEnd", []); await pg.wait_for_timeout(150)
    check("a tap on a star selects it", (await pg.evaluate(H + "state()"))["sel"] == other)
    await touch("touchStart", [(x, y)]); await touch("touchEnd", []); await pg.wait_for_timeout(900)
    check("a second tap on the selected star goes there", (await pg.evaluate(H + "state()"))["work"] == other)
    check("no page errors on the phone", not errors, "; ".join(errors[:3]))
    await ctx.close()


with tempfile.TemporaryDirectory() as t:
    site = Path(t) / "site"
    subprocess.run([sys.executable, str(HERE / "build_viewer.py"), "standalone", str(HERE / "corpus/data/bundle.json"), "-", str(site)],
                   check=True, capture_output=True)
    split = Path(t) / "export"
    subprocess.run([sys.executable, str(HERE / "corpus.py"), "export", str(HERE / "corpus/data"), str(split)], check=True, capture_output=True)
    split_site = Path(t) / "split-site"
    subprocess.run([sys.executable, str(HERE / "build_viewer.py"), "standalone", str(split), "-", str(split_site)],
                   check=True, capture_output=True)
    asyncio.run(main(site, split_site))
print(f"\n{passed} viewer checks hold")
