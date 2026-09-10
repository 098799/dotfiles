# webkit — how Tomek's small web apps are built (2026-09-10)

Rewritten on 2026-09-10 from a review of every app in the fleet. The July
version was written from museum alone and had drifted: it taught Python 3.12,
nginx serving images off `$HOME`, `fe-shot`, timers instead of workers, and had
no section on auth, units, backups or deploying. This one describes what the
**living** apps do — and for each piece it names the app to steal from.

**Read `~/apps/REGISTRY.md` first.** It is *what exists* (hosts, ports, names,
backups, rules 1–9). This file is *how to build*. If this file is wrong, fix
it here in the same change that proved it wrong, with the date.

---

## 0. The loop, start to finish

1. Pick a name that is free as a directory, unit, vhost and repo (rule 3, 5b).
2. Build it (§1–§6). Tests green.
3. Wire it (§7): units, vhost, backup manifest, tile, registry row.
4. `ship <app>` (§8). It refuses a dirty tree, runs the tests, smoke-boots,
   pushes, restarts, and checks the public name.
5. `fleet-check --quiet` shows nothing about your app.
6. Look at it on a phone-sized screenshot (§10) and send it to Tomek.

"Done" means a working tile on `p340.grining.eu`, not a process on a port.

## 1. Shape of an app

The default, and what xarchive, pod, igarchive, jobs, pokedex and sandbox all
are:

```
app/config.py   env-driven settings, paths under data/
app/db.py       SCHEMA string + idempotent migrations, stdlib sqlite3, WAL
app/web.py      FastAPI + Jinja2, server-rendered
app/worker.py   the long-running poller/renderer, if the app has one
app/sources/    one module per upstream, behind a seam (xarchive, igarchive)
app/templates/  base.html carries the CSS, the theme bootstrap, soft-nav, SW
tools/          rebuilders and probes (probe-mirrors.sh, build.py, probe.py)
tests/          pytest; tmp-path databases only
deploy/         the unit files and the nginx server block, as installed
data/           the DB and media — gitignored
```

- **Python 3.14** is the system Python; `uv` manages the venv (`uv add`,
  `uv run --no-sync` in units). `requires-python = ">=3.12"` is fine.
- **Server-rendered, no build step.** No SPA unless the app is a tool with
  heavy client state (genesis is React on vite, deliberately).
- **Self-contained**: system fonts, no CDN, nothing fetched from a third party
  at runtime. Tailnet apps must work with the internet down.
- **Worker, not timer**, for anything that polls: a `Restart=always` service
  with its own schedule and its own backoff (igarchive: 12 h cadence, 20 min →
  2 h retries on failure; xarchive: hourly, 15 min when a feed may have
  overflowed). A timer is right only for a daily batch (jobs-collect).
- **`templates.env.auto_reload = False`.** Units run out of the working tree,
  and Jinja re-reads templates per render by default — so an edited template
  goes live before the code it calls, and every page 500s (xarchive, twice).
  Templates now change only on restart, i.e. on `ship`.
- Other shapes exist and are fine when the reason is written down: health and
  fidelive are stdlib `http.server` on system Python; the kid toys are static
  folders behind a tiny server.

## 2. Correctness rules for anything that fetches

From xarchive's and igarchive's READMEs, which are the best in the fleet:

- **Empty versus broken.** A block page, a rate limit, an empty 200 and "posted
  nothing this week" all look like *no items*. Believe a response only after it
  proves it is the thing you asked for (xarchive: parses as RSS, has a channel,
  names `@user` in the title). Then zero items is an answer; record it.
- **Do not count scaffolding as content.** igarchive harvested the profile
  avatar as a story, so a page with no stories still returned one item and the
  empty-vs-broken guard never fired.
- **A failed download must be retried when the item is seen again.**
  `INSERT OR IGNORE` + "already archived" turned igarchive's one failed video
  into a permanent hole, for content that expires in 24 h.
- **Be a good guest.** Identifying User-Agent, one request at a time with a
  stagger, and size the interval by *requests per day* (list size ÷ interval),
  not by taste. Volunteer servers (Nitter) are what keep the app alive.
- **Keep the seam.** When an upstream dies the fix is a new module in
  `app/sources/`, not a rewrite.

## 3. Auth — rules 5d and 5e, as code

- **Personal data gets an inner token.** The tailnet is the outer gate only.
  Steal **`~/jobs/app/auth.py`** (208 lines, self-contained; rcmon's
  `AuthMiddleware` is the original): cookie *or* `Authorization: Bearer`,
  `hmac.compare_digest`, an **exact-match** allowlist (manifest, sw.js, icons,
  `/login`, `/healthz`), `sys.exit` at startup on an empty token, a login page
  for navigations and JSON 401 for `fetch()`. Token in `<app>/.env` (600,
  gitignored), loaded with `EnvironmentFile=`.
- **Never a token in a URL.** `<img>` and downloads get an HttpOnly cookie
  (genesis upgrades the header to a cookie). A query-string token is written to
  the nginx log — genesis leaked its token 1180 times that way.
- **Token-less is a decision, not a default.** pod, xarchive, igarchive and
  sandbox hold public content and have none, on purpose, so `/feed.xml` works in
  any reader. Say so in the registry row.
- **Every state-changing route checks the origin**, token or not. Allow a
  write only when `Sec-Fetch-Site` is `same-origin` or `none`, or — header
  absent, i.e. not a browser — when there is no `Origin` or it is the app's
  own. **Refuse `same-site` too, not only `cross-site`**: every app lives
  under `*.grining.eu`, so to a browser sandbox's agent-written exhibits,
  pod, xarchive and the public museum are all the *same site* as rcmon, and
  a `SameSite=Lax` cookie is attached to their requests. On 2026-09-10 that
  was shown live against rcmon (a page read the transcript stream and typed
  into an agent), and health and genesis were open the same way. Reference:
  `foreign_origin()` in `~/rcmon/rcmon/server.py`, `~/jobs/app/auth.py`.
  Since 2026-09-10 nginx enforces the same rule for every p340 vhost (a map
  in `00-http.conf` + the per-server include) — keep the app-level check
  anyway; the front door is one layer, and bae has no such rule.
- **Probe every verb.** health's PATCH and DELETE had no token check at all
  until 2026-09-10, because the auth audit only tried GET and POST.
- **Nothing an unauthenticated client can reach may start an agent** with
  `--dangerously-skip-permissions`. Give it an allow-list instead (chess tutor).
- Turn off `/docs` and `/openapi.json` (`FastAPI(docs_url=None, redoc_url=None,
  openapi_url=None)`) unless you use them.

## 4. Phone-first UI

Still true from the July version, all proven on a Poco F7 Ultra:

- One CSS block in `base.html` with custom properties; dark default, a
  light/auto toggle in settings; system fonts. Accent colour for chrome only;
  green/red one meaning each; never colour alone (pair it with shape or text).
- On dark panels `#74869f`-class greys pass AA, `#4d5d77` fails. Check before
  inventing a grey.
- `viewport-fit=cover`, bottom nav padded with `env(safe-area-inset-bottom)` —
  and a left gutter on its first item (weekends clipped it at 390 px).
- A shrinking header: `h1{flex:1;min-width:0;overflow:hidden}` plus
  `html,body{overflow-x:clip}`. Strips (`.chips`) scroll inside themselves.
  Long names get `text-overflow:ellipsis`.
- Test at 360–412 px **and** 1440 px; cap prose at ~74ch on desktop.
- Device wording via `.t-touch` / `.t-desk` (`(hover:hover) and
  (pointer:fine)`), so "tap" never appears on a desktop.
- **Page weight.** nginx gzips everything now (§7), but every soft navigation
  still refetches the whole HTML, and a page with 30 KB of inline CSS and 40 KB
  of inline JS pays that each time. Keep inline code small; when it grows past
  ~20 KB, move it to `/static/<name>.<version>.css|js` served with
  `Cache-Control: public, max-age=31536000, immutable`. Still no build step.

## 5. The things that always break

1. **Soft navigation** — intercept same-host clicks, fetch, swap `#content`,
   `pushState`. Solved in `~/museum/museum/templates/base.html`: skip modified
   clicks and `target=_blank`; **re-create inline `<script>`s after the swap**;
   update nav state, title and header widgets; restore both scroll axes (lazy
   images re-layout — nudge until stable, stop when the user scrolls); keep a
   small page cache so Back is instant.
2. **Overlay layering** — Escape and Back close exactly one layer, topmost
   first. Keep a z-index table in the app's docs (museum: lightbox 70 › popin
   menu 65 › popin 60 › review sheet 58 › header menu 45 › fab menu 31) and
   order the handler by it; overlays own the keyboard while they are up.
3. **Stale phones** —
   - `Cache-Control: no-cache` on every HTML response, from middleware.
   - Service worker: network-first HTML with a cached fallback and `/offline`;
     **never intercept JSON or API routes** (a worker claiming mid-flight kills
     routed fetches, and an offline fallback hands HTML to a JSON caller —
     museum `web.py`); never cache media (HTTP caching does that).
   - New deploy → waiting worker → "refresh" toast → `SKIP_WAITING` + reload.
     A separately installed PWA on the same server (health's Pac) needs its own
     toast. Guard the reload (`if (!reloading) { reloading = true; … }`) and do
     not reload on the *first* install — pod reloaded every cold visit.
   - A service worker is not compulsory. For an app that is useless offline,
     xarchive's **build-id banner** is simpler: the page carries the build id,
     polls `/version`, and shows "out of date — reload" when it changes.
   - **Icons: committed, byte-stable PNGs** — 192, 512 and a 512 maskable —
     plus `"id": "/"` in the manifest. SVG-only icons make Android re-mint the
     WebAPK; a single 64 px icon makes the app uninstallable (pokedex).
   - Serve `sw.js` as JavaScript. An nginx `types { … }` block replaces the
     whole MIME table — sudoku's dropped `js`, so the browser silently refused
     its service worker.

## 6. Keyboard layer (`snippets/keys.html`)

A Vimium-style layer inside the app — scrolling, link hints, history, a command
palette over the app's own data. xarchive and pod carry the current copy as
`_keys.html`. The rules that made it work:

- **Tomek's own bindings** (`~/dotfiles/vimium-options.json`): `i o k l u p`
  scroll, `s`/`S` back/forward, `d` palette, `f`/`e` hints, `gg`/`G`, `yy`, `?`.
- **`m` is the leader** — his Vimium config unmaps it, so app commands hang off
  `m` and never collide. Modes `full` / `leader` / `off` in localStorage, `m m`
  cycles; do not try to detect Vimium.
- **The layer is uniform; pages give way** (`window.__keysBusy()`).
- **Hints:** alphabet `sadfjklewcmpgh`, mixed length, built so no hint is a
  prefix of another. Navigate through `window.__go`, never `location.href`.
- Django (pypen) uses these snippets too: its template comments are
  single-line, so the snippet header is `{% comment %}`, never a multi-line
  `{# #}`.

## 7. Wiring it into p340

**Units** — `deploy/<app>.service` (+ `<app>-worker.service`), installed by
copying into `/home/tgrining/.config/systemd/user/` and kept identical to the
installed copy (jobs and fidelive drifted: a reinstall would have reopened
`0.0.0.0`). The template:

```ini
[Unit]
Description=<app> — <what it is>
After=network-online.target
# p340 only. ~/.config/systemd/user is not synced any more, but p14s still
# holds old copies of p340 units, and without this they ran there.
ConditionHost=p340

[Service]
WorkingDirectory=%h/<app>
EnvironmentFile=-%h/<app>/.env
ExecStart=/usr/bin/uv run --no-sync uvicorn app.web:app --host 127.0.0.1 --port <port>
# always, never on-failure: uvicorn exits 0 on SIGTERM, so one stray pkill -f
# left chess down 14 days and jobs 11 (2026-08-27).
Restart=always
RestartSec=3
# workers also: Nice=10, MemoryMax=…, and CPUAffinity=0-7 for CPU-heavy ones.
# Not AllowedCPUs=: user units have no cpuset delegation, so it does nothing
# (pod's TTS worker was unconfined), and OMP_NUM_THREADS does not bind onnxruntime.

[Install]
WantedBy=default.target
```

Bind **127.0.0.1**, always (rule 5c). Check `is-enabled` **and** `is-active`.

**nginx prefix locations redirect.** `location /audio/ { proxy_pass …; }`
makes nginx answer `/audio` with a 301 to `/audio/`; if the app also owns
`/audio` and redirects `/audio/` back, the page loops (pod's Audio tab, 09-10).
Add `location = /audio` for the page. And run uvicorn with
`--proxy-headers --forwarded-allow-ips 127.0.0.1`, or its redirects say
`http://`.

**Vhost** — a server block in `/etc/nginx/conf.d/p340-grining.conf` (copy an
existing one; keep `~/apps/ops/p340-grining.nginx.conf` identical), or its own
file in `conf.d/` for a self-contained app (games, insphero). Every block must
`include /etc/nginx/p340-deny-dotfiles.conf;` right after `server_name`.
gzip and HTTP/2 are box-wide in `00-http.conf`; do not add them per block.
The wildcard certificate and DNS need no work. `sudo nginx -t` before reload.

- **`$HOME` is 0700** and nginx runs as `http`, so nginx cannot `alias` or
  `try_files` anything under it. Serve media through the app (`/m/…` with
  `FileResponse`, range requests, a long private cache header) — igarchive,
  xarchive, pod's `/audio/` all do. On bae (`/opt/<app>`) nginx *can* serve
  files off disk directly, and museum does.
- **Never `tailscale serve`**, never a second way in.
- `ops/newapp-public.sh` is for **public** apps on bae — it publishes to the
  internet. Not for a tailnet app.

**Backups** — a DB goes into `~/apps/ops/db-backup.sh`'s MANIFEST (the nightly
job fails on an unregistered app DB). A non-DB tree that cannot be regenerated
goes into the off-site section of `ops/vps-db-backup.sh` (igarchive media,
health GPS logs). A tree that *can* be regenerated is declared disposable in
the registry row, with how to regenerate it. Decide which one it is on day one.

**Tile** — on both `~/apps/ops/p340-index.html` and `/srv/p340/index.html`
(`data-hidden` for private tools). **Registry row** — same commit.

## 8. Deploying: `ship <app>`

```
ship <app> [--dry-run] [--no-tests] [--no-smoke]
```

Refuses a dirty tree → `uv run --no-sync pytest -q -x` → boots the web unit's
exact command on port 38950 with the unit's environment and requires an answer
→ pushes to `~/git` → restarts every unit that runs out of the tree → checks
each unit is active and each public name answers → logs to
`~/.local/state/ship/<app>.log`. Per-app knobs in `deploy/ship.env`
(`SMOKE_PATH=/healthz`, `SMOKE=0`, `TESTS="…"`).

Why: units run the working tree, so without a gate "deploy" was "restart
whatever is on disk". On 2026-09-10 five apps were serving uncommitted code —
dinosaurs for two months, health three weeks — none of it in any backup.

- **Commit before you restart.** Never leave a served tree dirty at the end of
  a session; `fleet-check` warns after 2 days.
- Apps with a stronger deploy of their own keep it: rcmon (`rcmon/deploy.sh`,
  federation peers + rollback), health (`scripts/deploy.sh`), pens. Model new
  ones on `ship`, not on an rsync.
- **Public apps on bae** deploy `git archive HEAD`, never the working tree
  (museum's script shipped a gitignored `scratch/` folder to the internet).
  See `~/kids-sudoku/deploy.sh` (small) and `~/museum/deploy/bin/` (the full
  code + data sync).
- **Never rsync a live SQLite file** — `.backup` first. For a read-only mirror,
  ship it as `journal_mode=DELETE`, rsync to `.new`, `mv` into place.

## 9. Watching: `fleet-check`

`fleet-check --quiet` (runs every 15 min from `fleet-check.timer`) — units,
vhosts, `.git` exposure, tiles, loopback binds, committed/pushed trees,
backups, certificate. New failures reach the phone through rcmon; the index
LEDs read its verdict. If your app needs an exception, add it to the
allowlists at the top of `~/apps/ops/fleet-check.py` **with a reason**.

## 10. Verifying without a phone in your hand

- **Python `playwright`** (system `python3`, bundled Chromium) is the working
  browser on p340; the chrome-devtools and playwright MCP servers are not.
  Phone: `viewport 390x844, device_scale_factor=3, is_mobile=True,
  has_touch=True`. Save the PNG, then **look at it**.
- Installability: CDP `Page.getInstallabilityErrors` in a persistent context
  (`launch_persistent_context(tempdir)`) must return `[]`.
- Offline: load, reload once so the worker controls the page,
  `context.set_offline(True)`, reload — it must still render.
- Trap: `page.mouse.wheel()` in a touch-emulated page flips `(hover:hover)` to
  true, and the page starts showing desktop wording. Scroll with
  `evaluate("scrollTo(…)")` in phone probes.
- Interaction/keyboard testing over CDP: `snippets/cdp_probe.py`. `char` key
  events bypass `preventDefault`; typing into an unfocused headless page needs
  `Input.insertText`.
- Show Tomek: copy the PNG to `~/.rcmon/images/drop/<stem>.png` and embed
  `![stem](/api/images/by-caption/<stem>)`.

## 11. Going public (bae, `*.grining.eu`)

A public app gets everything above plus: security headers (HSTS, CSP,
`X-Content-Type-Options: nosniff`, `Referrer-Policy`) with `add_header …
always`; `Secure; HttpOnly; SameSite=Lax` on every cookie; `/docs` off;
`limit_req` on anything that fetches upstream or writes; HTML 404 pages for
humans (JSON only under `/api/`); `HEAD` answered; `robots.txt` and a
user-agent map for AI crawlers (GPTBot was a third of museum's traffic);
restarts that do not drop requests. Museum's review (2026-09-10) found it
missing most of these — it is the reference for the *shape* of a public app,
not yet for its hardening. `sandbox.grining.eu` is the reference for a CSP.

## 12. Small rules with sharp edges

- **Never `pkill -f` a pattern that other apps share.** `pkill -f "uvicorn
  app.web:app"` killed chess, jobs, pod and pokedex at once. Stop a unit with
  `systemctl --user stop`, a dev server by its PID. And `pkill -f`/`pgrep -f`
  from an agent shell match the shell itself — use `[b]racket` patterns.
- **Agent shells have `HOME=/home/tgrining/claude-prim`.** Git then has no
  identity (`Author identity unknown`) and `~` points elsewhere: use absolute
  paths, and `HOME=/home/tgrining git commit …`.
- **Tests never touch the live DB** (chess's `test_web.py` did; pod's suite
  had one test reading it, and monkeypatching `get_db` alone leaks), and never
  pin absolute dates against `now()` (weekends' test failed from 2 Aug on).
- **Probes and QA run against a copy**, never the live app: pod's
  `tools/probe.py` defaulted to the live library and left its test notes in
  the real DB. Copy the DB, start the app on a spare port, point the probe there.
- SQLite timestamps as `YYYY-MM-DD HH:MM:SS` UTC (a space, not `T`), or string
  comparison breaks.
- Never copy a scratch folder into `/srv` whole: relevancy-map shipped an
  unlinked `evidence/` folder of customer data to the tailnet.
- Wikidata's label service sometimes returns the bare QID. Keep a fallback and
  a repair pass — and make the repair stick (museum repaired the same 12 names
  every hour).
- Inline `<script>` in a Jinja block runs before anything included at the end
  of `<body>`; wire page code on `DOMContentLoaded`, and call it directly after
  a soft nav.

## 13. Writing it down

The READMEs that work (xarchive, igarchive, jobs, health's `STATE.md`) record
**measured numbers, the alternative that was rejected and why, and the
decisions not to re-litigate**. A future session reads those before it
"improves" something back into a bug. Put the incident in the comment next to
the line it explains (jobs.service's `ConditionHost` comment is the model).
