"""cdp_probe — drive a real headless Chrome and assert on what happened.

Copy this next to your app and edit the SCRIPT section at the bottom of
main(). It launches headless Chrome with a debugging port, speaks CDP over a
websocket, dispatches genuine key/mouse events and reads state back with
Runtime.evaluate. This is how the museum's keyboard layer, overlay layering
and soft navigation were verified without touching a browser by hand.

    uv run --with websockets python cdp_probe.py

Two traps this file already works around:

* `Input.dispatchKeyEvent` sends a separate `char` event that is NOT
  suppressed by the page calling preventDefault() on keydown. A key that
  opens a text field therefore *leaks its own letter into it* here, while a
  real keyboard would not. Clear the field before asserting.
* Typing into a focused field of an unfocused headless window may drop the
  characters — use `Input.insertText` for text, real key events for commands.

Everything else is deliberately dependency-light: stdlib + websockets.
"""

import json, subprocess, time, urllib.request, asyncio, websockets

PROF = "/tmp/cdp-probe-profile"     # throwaway Chrome profile
URL = "http://127.0.0.1:8322/"      # the page to start on
PORT = 9334
p = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
     f"--user-data-dir={PROF}", "--no-first-run", "--disable-gpu",
     "--window-size=1440,900", URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(5)
log = []


async def main():
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
    tab = [t for t in tabs if t["type"] == "page"][0]
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=None) as ws:
        i = [0]

        async def call(method, params=None):
            i[0] += 1
            await ws.send(json.dumps({"id": i[0], "method": method, "params": params or {}}))
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if m.get("id") == i[0]:
                    return m.get("result", {})

        async def ev(expr):
            r = await call("Runtime.evaluate",
                           {"expression": expr, "returnByValue": True, "awaitPromise": True})
            if "exceptionDetails" in r:
                return "EXC:" + json.dumps(r["exceptionDetails"])[:200]
            return r.get("result", {}).get("value")

        async def key(ch, shift=False):
            vk = {"?": 191, "[": 219, "]": 221, "Escape": 27, "Enter": 13,
                  "ArrowDown": 40}.get(ch, ord(ch.upper()) if len(ch) == 1 else 0)
            base = {"key": ch, "code": ("Key" + ch.upper() if len(ch) == 1 and ch.isalpha() else ch if len(ch) > 1 else ""),
                    "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
                    "modifiers": 8 if shift else 0}
            await call("Input.dispatchKeyEvent", dict(base, type="keyDown"))
            if len(ch) == 1:
                await call("Input.dispatchKeyEvent", dict(base, type="char", text=ch))
            await call("Input.dispatchKeyEvent", dict(base, type="keyUp"))

        async def typ(text):
            # headless windows are unfocused; insertText goes straight to the
            # focused editable and still fires the input event
            await call("Input.insertText", {"text": text})
            await asyncio.sleep(0.05)

        await asyncio.sleep(1.5)
        log.append(("loaded", await ev("location.pathname"), await ev("!!window.__keysLoaded")))

        # scroll: i / k / gg
        await key("i"); await key("i"); await asyncio.sleep(0.2)
        log.append(("after ii scrollY", await ev("scrollY")))
        await key("k"); await asyncio.sleep(0.2)
        log.append(("after k scrollY", await ev("scrollY")))
        await key("g"); await key("g"); await asyncio.sleep(0.3)
        log.append(("after gg scrollY", await ev("scrollY")))
        # count prefix
        await typ("5i"); await asyncio.sleep(0.3)
        log.append(("after 5i scrollY", await ev("scrollY")))
        await key("g"); await key("g"); await asyncio.sleep(0.3)

        # help sheet
        await key("?", shift=True); await asyncio.sleep(0.4)
        log.append(("help open", await ev("document.getElementById('khelp').classList.contains('on')")))
        await key("Escape"); await asyncio.sleep(0.3)
        log.append(("help closed", await ev("!document.getElementById('khelp').classList.contains('on')")))

        # leader: m a -> /artists
        await key("m"); await asyncio.sleep(0.15)
        log.append(("hud after m", await ev("document.getElementById('khud').textContent")))
        await key("a"); await asyncio.sleep(1.2)
        log.append(("m a ->", await ev("location.pathname")))

        # back with s
        await key("s"); await asyncio.sleep(1.2)
        log.append(("s ->", await ev("location.pathname")))

        # palette: d, type, enter
        await key("d"); await asyncio.sleep(0.5)
        log.append(("palette open", await ev("document.getElementById('kpal').classList.contains('on')")))
        # CDP leaks the 'd' char into the freshly focused input (a real
        # keyboard would not) — clear it before typing the query
        await ev("var pi=document.querySelector('#kpal input');pi.value='';1")
        await typ("uffizi"); await asyncio.sleep(1.2)
        log.append(("palette rows", await ev("document.querySelectorAll('#kpal .kp-row').length"),
                    await ev("(document.querySelector('#kpal .kp-row.sel .kp-t')||{}).textContent")))
        await key("Enter"); await asyncio.sleep(1.5)
        log.append(("palette enter ->", await ev("location.pathname")))

        # link hints on the gallery page
        await ev("scrollTo(0,0)"); await asyncio.sleep(0.3)
        await key("f"); await asyncio.sleep(0.5)
        log.append(("hints", await ev("document.querySelectorAll('.khint').length"),
                    await ev("(document.querySelector('.khint')||{}).textContent")))
        first = await ev("(document.querySelector('.khint')||{}).textContent")
        await key("Escape"); await asyncio.sleep(0.3)
        log.append(("hints cleared", await ev("document.querySelectorAll('.khint').length")))

        # trail: open a painting from the grid, then ] walks
        await ev("window.__go('/gallery/alte-pinakothek', true);1")
        await asyncio.sleep(2.0)
        await ev("document.querySelector('#content a[href*=\"/painting/\"]').click()")
        await asyncio.sleep(1.5)
        p1 = await ev("location.pathname")
        await key("]"); await asyncio.sleep(1.5)
        p2 = await ev("location.pathname")
        await key("["); await asyncio.sleep(1.5)
        p3 = await ev("location.pathname")
        log.append(("trail", p1, p2, p3, p1 != p2 and p1 == p3))

        # zoom with z, Escape closes only the lightbox
        await key("z"); await asyncio.sleep(0.8)
        log.append(("z lightbox", await ev("document.getElementById('lightbox').classList.contains('open')")))
        await key("Escape"); await asyncio.sleep(0.5)
        log.append(("esc lightbox", await ev("!document.getElementById('lightbox').classList.contains('open')"),
                    await ev("location.pathname")))

        # leader-only mode leaves scrolling to Vimium
        await ev("window.__keysSetMode('leader');1")
        y0 = await ev("scrollY")
        await key("i"); await key("i"); await asyncio.sleep(0.3)
        log.append(("leader mode ignores i", y0 == await ev("scrollY")))
        await key("m"); await key("q"); await asyncio.sleep(1.5)
        log.append(("leader m q ->", await ev("location.pathname")))
        # quiz keeps its answer keys
        await asyncio.sleep(1.0)
        await ev("window.__keysSetMode('full');1")
        await asyncio.sleep(2.5)
        log.append(("quiz live", await ev("!!document.querySelectorAll('#qopts .qopt').length")))
        await key("s"); await asyncio.sleep(1.0)
        log.append(("s on live quiz stays put", await ev("location.pathname"),
                    await ev("document.querySelectorAll('#qopts .qopt.hit,#qopts .qopt.miss').length")))
        log.append(("console errors", await ev("window.__errs||0")))


try:
    asyncio.run(asyncio.wait_for(main(), 150))
except Exception as e:
    log.append(("error", repr(e)))
finally:
    p.kill()
for row in log:
    print(*row)
