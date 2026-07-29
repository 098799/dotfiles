# webkit — how Tomek's small web apps are built

The playbook behind `weekends` (flight tracker), `museum` (virtual museum,
public at museum.grining.eu), `rcmon` and friends. Read this **before**
starting or extending any tailnet app or `*.grining.eu` app; steal from
`snippets/` rather than reinventing.

Reference implementations, in order of how much they have been polished:

| what | where |
|---|---|
| the whole pattern, end to end | `~/museum` (`docs/ARCHITECTURE.md` is the map) |
| the original of most conventions | `~/weekends` |
| this kit | `~/dotfiles/webkit/` |

---

## 1. Shape of an app

- Python 3.12 + `uv` (`uv add`, `uv run`, `.venv/` in the repo).
- **FastAPI + Jinja2, server-rendered.** No SPA, no build step, no CDN — a
  tailnet app must be self-contained (system fonts, inline CSS/JS).
- **SQLite via stdlib `sqlite3`**, WAL mode, no ORM. Schema in `db.py` as a
  `SCHEMA` string + idempotent migrations; `rebuild_fts()` for search.
- Package layout: `app/` with `config.py`, `db.py`, `web.py`, `templates/`;
  background work as `python -m app.<worker>` behind a systemd **user** timer.
- Tests: pytest, pure logic, fast. Endpoints are testable by
  monkeypatching `get_db` — see `museum/tests/test_palette.py`.

## 2. Deploying

- systemd **user** units in `deploy/*.service`, `WorkingDirectory=%h/<app>`,
  uvicorn on `127.0.0.1:<port>`. Linger is on for both p14s and p340.
- Tailnet: `tailscale serve --bg --https=<port> http://127.0.0.1:<port>`.
  Ports in use: 443 rcmon, 8443/8444 weekends, 8445, 8446 (was museum's
  private wing), 9443/6443/7443 legartis. **TLS with the bare short hostname
  fails SNI** — always hand over the full `p340.tail0c4bc8.ts.net:PORT`.
- Public mirror (`*.grining.eu`) lives on the Hetzner VPS, ssh alias
  `bae_llm`, app in `/opt/<app>`, plain venv (no uv there), `www-data`,
  uvicorn behind nginx. Two scripts, keep this split:
  `museum-deploy-code.sh` (rsync code, restart) and `museum-public-sync.sh`
  (sqlite `.backup` snapshot + image rsync + restart). See
  `snippets/deploy-code.sh` / `snippets/public-sync.sh`.
- **Never rsync a live SQLite file** — snapshot with `.backup` first, or you
  ship a torn WAL.
- nginx serves images straight off disk (`try_files … @app`), so the app only
  handles misses. Big win on the 5GB image tree.

## 3. Phone-first UI rules (all proven on a Poco F7 Ultra)

- One CSS block in `base.html` with custom properties; dark theme; system
  fonts. Give each app its own palette but keep the rules:
  accent = chrome only (nav, selection, CTA), never on every value;
  green/red one meaning each; colour never the sole carrier (pair with
  shape/text) for CVD.
- Contrast: on dark panels `#74869f`-class dim greys pass AA, `#4d5d77` fails.
  Check before inventing a new grey.
- `viewport-fit=cover`, bottom nav with `env(safe-area-inset-bottom)`.
- Header must shrink: `h1{flex:1;min-width:0;overflow:hidden}` plus
  `html,body{overflow-x:clip}` — a fixed-content flex header caused body-wide
  horizontal scroll on the phone.
- Horizontal strips (`.chips`, `.walk`) scroll inside themselves
  (`overflow-x:auto`), never the page.
- Test at 360–412px **and** 1440px. On desktop cap long prose at ~74ch —
  a 1300px-wide paragraph is a wall.
- Device-specific wording via `.t-touch` / `.t-desk` spans (a
  `(hover:hover) and (pointer:fine)` media query), so "tap" never appears on
  a desktop.

## 4. The three things that always break

1. **Soft navigation.** Intercept same-host clicks, fetch, swap `#content`,
   `pushState`. Gotchas already solved in `museum/templates/base.html`:
   skip `defaultPrevented`/meta/ctrl/shift/`target=_blank`; **re-create inline
   `<script>` tags after the swap** (they do not execute when inserted via
   DOM); update nav active state, title and path-dependent header widgets from
   the fetched document; restore vertical *and* horizontal scroll (lazy images
   keep re-laying-out — nudge back until stable, but stop the moment the user
   scrolls); keep a small page cache so Back is instant.
2. **Overlay layering.** Every overlay must close **exactly one layer** on
   Escape and on Back, topmost first (museum: lightbox 70 › popin menu 65 ›
   popin 60 › fab menu 31). Order the handler by z-index, and have overlays
   own the keyboard while they are up. Getting this wrong closes the article
   under the zoomed image.
3. **Stale phones.** Send `Cache-Control: no-cache` on HTML from middleware,
   or the PWA renders a layout from last week forever. Service worker:
   network-first HTML with cache fallback + `/offline`; never SW-cache the
   images (HTTP cache with a long max-age does that job); new deploy → waiting
   worker → "refresh" toast → `SKIP_WAITING` + reload.

## 5. Keyboard layer (`snippets/keys.html`)

A Vimium-style layer *inside* the app: scrolling, link hints, history, a
command palette over the app's own data, and app-specific commands. Drop the
snippet in, edit the CONFIG block at the top, add the palette endpoint.

What the museum build taught, all of it baked into the snippet:

- **Use the user's own bindings.** `~/dotfiles/vimium-options.json` is the
  source of truth: `i o k l u p` scroll, `s`/`S` back/forward, `d` palette,
  `f`/`e` hints, `gg`/`G`, `yy`, `?`. Do not invent a second dialect.
- **`m` is the leader.** His config does `unmap m`, so it is the one key that
  reaches the page when Vimium is running — app commands hang off it and can
  never collide with the extension.
- **Three modes** in localStorage: `full` · `leader` (only `m…`, for the
  browser where Vimium already drives) · `off`, with a chooser on a settings
  page and `m m` to cycle. Do not try to auto-detect Vimium; it is not
  reliably detectable.
- **The layer is uniform; pages give way.** When the museum quiz wanted
  A/S/D/F, the *quiz* moved (to 1–4 plus ↑↓/Enter), not the layer. Expose a
  `window.__keysBusy()` so a page's own handler can stand down while hints or
  the palette are up.
- **Hints:** Vimium's own alphabet `sadfjklewcmpgh`, and its mixed-length
  scheme — as many one-key hints as the alphabet can spare, the rest two-key,
  built most-significant-first so **no hint is a prefix of another** (build it
  the other way and `s` swallows `sh`).
- Navigate through the app's soft-nav function (`window.__go`), never
  `location.href`, or you lose the swap and the scroll restoration.

## 6. Verifying without a phone in your hand

- Screenshots: `~/bin/fe-shot <url> --out x.png --width 390 --height 844`
  (headless Chrome, works on localhost). Read the PNG back and actually look
  at it. Run them **sequentially** — parallel invocations fight over the
  profile and you get a Google new-tab page.
- Interaction / keyboard / overlay testing: `snippets/cdp_probe.py` — headless
  Chrome + CDP over websockets, dispatches real key events and reads state
  back. Copy it and edit the script body. Two traps it documents:
  `Input.dispatchKeyEvent` `char` events bypass `preventDefault` (a key that
  opens a palette leaks its letter into the input — a real keyboard does not),
  and typing into a focused field in an unfocused headless window needs
  `Input.insertText`.
- Show Tomek the result: copy the PNG to
  `~/.rcmon/images/drop/<distinctive-stem>.png` and embed
  `![stem](/api/images/by-caption/<stem>)` — he reads replies on his phone.

## 7. Small rules with sharp edges

- SQLite timestamps as `YYYY-MM-DD HH:MM:SS` UTC (space, not ISO `T`), or
  string comparisons silently break.
- `pkill -f` / `pgrep -f` from an agent shell self-match the wrapper — use
  `[b]racket` patterns.
- Wikidata's label service sometimes returns the bare QID instead of a name.
  Always have a fallback (the Wikipedia article title) *and* a repair pass —
  26 painters shipped as "Q44007 · 15" before anyone noticed.
- Inline `<script>` in a Jinja block runs **before** anything included at the
  end of `<body>`. If page code needs the shared layer, wire it on
  `DOMContentLoaded` (and call it directly after a soft nav, where the layer
  already exists).
