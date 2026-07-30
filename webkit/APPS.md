# App catalogue — tailnet + *.grining.eu

Surveyed 2026-07-30 (live systemd + tailscale serve + nginx state, not from
docs). This file is the **canonical port/app registry** — update it in the
same commit that adds, moves, or retires an app. The port list formerly in
README.md drifted; trust this file.

## p340 — always-on home box (tailnet name `rcmon`, 100.77.63.74)

All apps bind 127.0.0.1 and are fronted by `tailscale serve`
(`https://rcmon.tail0c4bc8.ts.net:<PORT>`).

| app | local port | tailnet port | notes |
|---|---|---|---|
| weekends (flight tracker) | 8321 | :8443 and :80 | + collector daemon, watchdog + daily backup timers |
| museum | 8322 | — (public only) | canonical DB; hourly `museum-ingest` timer; mirrors to bae |
| rcmon (phone dashboard) | 38000 | :8445 | runs from legartis utils repo |
| health tracker | 19443 | :9443 | + coverage (hourly), reminder (20:30), backup (daily) timers |
| dinozaury (kid app) | 17443 | :7443 | plain `serve.py`, repo `~/dinosaurs` |
| pixelpaint (kid app) | 16443 | :6443 | `python -m http.server` over `~/drawing` |
| haircut-studio | 8090 (LAN 0.0.0.0) | — | **crash-looping as of 2026-07-30** |
| sudoku-jednorozca | 15443 | :5443 (unmapped) | **inactive** — moved to sudoku.grining.eu |

Debris seen 2026-07-30: serve `:8444 → localhost:3001` points at nothing;
`tailgate-sni.service` (a p14s service) synced here and retry-loops because it
binds p14s's IP; `vacation-digest` timer expired (last ran Jul 20).

## p14s — dev laptop (100.98.125.20)

Dev copies of the above + legartis slots (`app{N}.local.legartis.ai:9443` via
`tailgate-sni`, which legitimately binds this host's IP; 6443/7443 legartis
too, per README history). Not reachable over ssh during this survey — re-audit
when it is.

## bae_llm — Hetzner VPS, public (`*.grining.eu`, 135.181.197.232)

nginx + certbot in front of everything; apps bind 127.0.0.1.

| domain | app | local port | notes |
|---|---|---|---|
| museum.grining.eu | museum mirror | 8322 | `/opt/museum`; nginx serves images off disk; timed access log |
| memory.grining.eu | Memorize flashcards | 8323 | `/opt/memory`; canonical DB lives HERE; **no backup timer** |
| pen.grining.eu | pypen (Django/gunicorn) | 8000 | lives in **/root/pypen** (deviation); **no backup** |
| sudoku.grining.eu | static + sudoku-time keeper | 18090 | `/var/www/sudoku` + `/opt/sudoku-time` |
| grining.eu | static landing | — | `/var/www/html`, `/sudoku/` alias |

Certs also exist for bae.grining.eu, plate.grining.eu, pdoom.me — no active
server blocks; treat as parked/retired.

---

# Commonalities — what already IS the standard (keep it)

1. **FastAPI + Jinja2, server-rendered**, no build step, self-contained
   (system fonts, inline CSS/JS). museum, weekends, memory all fit.
2. **SQLite via stdlib, WAL, no ORM**; schema string + idempotent migrations;
   timestamps `YYYY-MM-DD HH:MM:SS` UTC (space, not `T`).
3. **uv + `.venv` in repo** on dev boxes; plain venv on the VPS.
4. **Bind 127.0.0.1, front with a layer** — tailscale serve on p340, nginx on
   bae. Nothing faces a network directly (haircut-studio's LAN bind is the
   one deliberate exception).
5. **systemd user units on p340 / system units on bae**; background work as
   `python -m app.<worker>` behind a timer.
6. **DB backup = one-shot `.backup` + rotation + daily timer** (weekends,
   health have it).
7. **Public deploy = `/opt/<app>` + two scripts**: deploy-code (rsync,
   restart) vs public-sync (`.backup` snapshot + image rsync). Never rsync a
   live SQLite file.
8. **Phone-first UI**: one CSS block, dark theme, PWA + `no-cache` HTML,
   soft nav, keyboard layer with `m` leader. Rules in README.md.
9. **Verification**: `fe-shot` screenshots + `cdp_probe.py` interactions +
   rcmon image drop to show Tomek.

# Should-be commonalities — gaps this survey exposed

1. **One registry, kept current.** README's port list said 9443=legartis on
   the home box; it's actually health. Serve `:8444` points at a dead port.
   This file is now the registry — touch it with every port change.
2. **Backup timer wherever the canonical DB lives.** memory's only copy of
   632 flashcards sits on bae with no backup; pypen likewise. Reuse the
   weekends/health backup unit verbatim.
3. **One name per app, all layers.** Sudoku is `kids-sudoku` (repo),
   `sudoku-jednorozca` (unit), `sudoku-time` (VPS svc), `/var/www/sudoku`.
   Pick the short name once → repo = unit = /opt dir = subdomain.
4. **Two explicit tiers, both registered.** Full app (webkit shape) vs
   static toy (`http.server` — pixelpaint, dinozaury, sudoku). Toys are fine,
   but they still get: unit file checked into their repo, localhost bind +
   serve, and a row here.
5. **A decommission ritual.** Retiring leaves debris: dangling serve
   mappings, inactive-but-enabled units, expired timers, parked certs. On
   retirement: drop the serve mapping, `disable` the unit, strike the row
   here (don't delete — mark retired with a date).
6. **`/healthz` + a generalized watchdog.** haircut-studio has been
   crash-looping unnoticed; only weekends has a watchdog. Every full-tier
   app: a `/healthz` route; one watchdog timer pings every registry row and
   pushes failures via rcmon.
7. **Host-specific services must refuse the wrong host.** tailgate-sni
   hardcodes p14s's IP and got syncthing-synced to p340, where it retry-loops
   forever. Anything in synced `~/bin`/dotfiles that is host-bound gets
   `ConditionHost=` in the unit (or an IP check that exits 0).
8. **VPS apps live in `/opt/<app>`, never `/root`.** pypen is the outlier —
   invisible to backup sweeps and permission conventions.
9. **One nginx template.** museum's block is the good one (timed access-log
   format, images off disk via `try_files`, `client_max_body_size`, acme
   location). Turn it into `snippets/nginx-app.conf` and instantiate; stop
   hand-writing vhosts.
10. **Deploy scripts parameterized, not copied.** `snippets/deploy-code.sh`
    and `public-sync.sh` exist — new apps should consume them with an APP
    variable, not fork per-app copies that drift.
