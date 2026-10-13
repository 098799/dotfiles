"""Agents: Tomek's Claude agent sessions, the slot queue and his open MRs. cmon on
the bar.

The strip: a robot and the number of agents at work; an amber badge with the agents
that wait for Tomek (a permission dialog or a question on their screen); a red dot
on the robot when the head pipeline of one of his open MRs failed. All calm: a robot
and a number.

Nothing is worked out anew here. cmon and rcmon know it all already:

- rcmon (rcmon.service, http://127.0.0.1:38000, its Bearer token from
  ~/rcmon-live/.env). GET /api/state is cmon's own board (state_producer: the lock
  files, the claude processes, their tmux panes, the worktrees and their MRs) with
  rcmon's reading of each pane (rcmon/pane_status.py: a spinner = working, a
  permission dialog or a question picker = waiting, the prompt = idle), and p340's
  agents through rcmon's federation. GET /api/mrs is state_producer's cache of
  Tomek's open MRs (pipeline, approvals, threads), in rcmon's memory: ~4 ms.
- slotq's state file (~/.legartis/slotq/state.json), read in-process: the queue, as
  `slotctl list` reads it. Only while the panel is open.
- cmon's Linear cache (~/legartis/cmon/issues/DEV-N.json): the tickets' titles.
- rcmon not answering: the MRs come from `glab api` (GET only), at most every 60 s
  while the panel is open and every 5 min for the strip.

Cost. One /api/state costs rcmon ~0.18 s of CPU (it captures every pane), and it
reads GitLab when its MR cache is older than 60 s. So the bar does not poll it.
Every 4 s it reads /proc/<pid>/stat of each claude process rcmon named (a few µs
each) and the mtime of cmon's lock directory, and it asks rcmon again only on an
edge: a claude went quiet (it stopped at a prompt, a permission dialog or a
question) or busy again (Tomek answered), one ended, a new one was spawned. At most
every 30 s, at least every 5 min, and every 4 s while the panel is open. No program
runs in steady state. The last answer is kept in $XDG_RUNTIME_DIR/bardeck/agents.json,
so after a restart the bar shows it, with its age, until rcmon answers.

The panel: AGENTS (the waiting ones first; click or Enter: a terminal attached to its
tmux session, as cmon's `A` does), QUEUE (slotq's jobs; Enter: the job's MR, or its
slot's session), MRS (click or Enter: the MR in the browser). Pinned keys: `i`/`o`
select, `k`/`l` half a section, `j`/`;` previous / next section, Enter attach /
open, `r` ask rcmon now, `c` cmon.

Read only: nothing here writes to tmux, slotq, cmon or GitLab.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import socket
import subprocess
import threading
import time
import urllib.request

from . import core
from .core import REAL_HOME, Hits, button, heading, rgba, text
from .deck import Panel
from .notif import badge

RCMON = "http://127.0.0.1:38000"
RCMON_ENV = f"{REAL_HOME}/rcmon-live/.env"
LOCKS_DIR = "/tmp/linear_claude_locks"  # cmon's agent locks (agent_locks_dir.py)
SLOTQ_STATE = f"{REAL_HOME}/.legartis/slotq/state.json"
ISSUES_DIR = f"{REAL_HOME}/legartis/cmon/issues"
CACHE = f"{core.RUN_DIR}/agents.json"
GITLAB_HOST = "git.legartis.ai"
GITLAB_PROJECT = "legartis%2Flegartis"
GITLAB_USER = "tgrining"
MR_URL = f"https://{GITLAB_HOST}/legartis/legartis/-/merge_requests/"
LOCAL = socket.gethostname()

TICK_S = 4          # the edge watch, and rcmon's own snapshot TTL while the panel is open
EDGE_GAP_S = 30     # an edge asks rcmon at most this often
FLOOR_S = 300       # and it is asked at least this often
GLAB_OPEN_S, GLAB_STRIP_S = 60, 300
# A claude process that is working (streaming, running a tool, its spinner) burns
# 4-6 ticks/s; one at a prompt ~1.2 (measured 13 Oct 2026). Between: the edge.
BUSY_TICKS_PER_S = 3.0

GLYPH_ROBOT, GLYPH_ROBOT_IDLE = "\U000f06a9", "\U000f167a"
GLYPH_MR, GLYPH_QUEUE, GLYPH_HAND = "\U000f04c2", "\U000f027b", "\U000f0e46"
GLYPH_THREAD, GLYPH_CHECK = "\U000f0182", ""
GLYPH_REFRESH, GLYPH_CONSOLE = "\U000f0450", "\U000f018d"

# A pane's state (rcmon's pane_status) -> (group, words, tone). Groups order the list.
PANE = {
    "permission": ("waiting", "permission", "warn"),
    "question": ("waiting", "question", "warn"),
    "limit": ("error", "rate limit", "hit"),
    "error": ("error", "error", "hit"),
    "retrying": ("working", "retrying", "orange"),
    "working": ("working", "working", "ok"),
    "idle": ("idle", "idle", "fg"),
    "stopped": ("done", "exited", "dim"),
}
GROUP_ORDER = {"waiting": 0, "error": 1, "working": 2, "idle": 3, "done": 4}
GROUP_DOT = {"waiting": "warn", "error": "hit", "working": "ok", "idle": "bg3", "done": "bg2"}

PIPELINE = {  # GitLab's pipeline status -> (words, tone)
    "success": ("passed", "ok"), "failed": ("failed", "hit"), "running": ("running", "blue"),
    "pending": ("pending", "warn"), "created": ("pending", "warn"), "preparing": ("pending", "warn"),
    "waiting_for_resource": ("pending", "warn"), "scheduled": ("scheduled", "dim"),
    "manual": ("manual", "purple"), "canceled": ("canceled", "dim"), "skipped": ("skipped", "dim"),
}

JOB = {  # slotq's job state -> (order, words, tone)
    "running": (0, "running", "ok"), "queued": (1, "queued", "fg2"), "blocked": (2, "blocked", "warn"),
    "failed": (3, "failed", "hit"), "in_ci": (4, "in CI", "blue"), "parked": (5, "parked", "dim"),
    "done": (6, "done", "dim"),
}
DONE_SHOWN_S = 3600  # a finished job stays on the list this long

TICKET = re.compile(r"\b(DEV-\d+)\b", re.I)


def ago(sec: float) -> str:
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    if sec < 86400:
        return f"{sec // 3600}h{sec % 3600 // 60:02d}"
    return f"{sec // 86400}d"


def spinner_secs(detail: str) -> float | None:
    """Claude's spinner line says how long the turn runs: "3m 5s · ↓ 10.2k tokens"."""
    m = re.match(r"\s*(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?", detail or "")
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(g or 0) for g in m.groups())
    return h * 3600 + mi * 60 + s


class Agent:
    """One Claude session, as rcmon reads it."""

    __slots__ = ("key", "session", "target", "host", "ticket", "title", "status", "group", "words",
                 "tone", "since", "detail", "slot", "where", "pid")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}

    @property
    def remote(self) -> bool:
        return bool(self.host) and self.host != LOCAL


class MR:
    __slots__ = ("iid", "title", "url", "ticket", "pipeline", "draft", "approved", "unresolved",
                 "threads_open", "conflicts")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


class Job:
    __slots__ = ("ticket", "state", "slot", "mr", "note", "title", "at")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


class Agents:
    """What rcmon and slotq say, kept fresh on edges (see the module's docstring)."""

    def __init__(self):
        self.agents: list[Agent] = []
        self.mrs: list[MR] = []
        self.jobs: list[Job] = []
        self.queue_text = ""        # rcmon's one-line queue summary
        self.runner_on: bool | None = None
        self.slotq = os.path.exists(SLOTQ_STATE)
        self.up = False             # rcmon answered the last ask
        self.at = 0.0               # when the agents were read (wall clock)
        self.mrs_at = 0.0           # when the MRs were read from GitLab (by rcmon or glab)
        self.mrs_via = ""           # "rcmon" / "glab"
        self.error = ""
        self.open = False           # the panel is open: ask every TICK_S
        self.fetching = False
        self.watching = False
        self._asked = 0.0           # monotonic: the last ask started
        self._glab_at = 0.0
        self._pending = False       # an edge came inside EDGE_GAP_S: ask when it is over
        self._cpu: dict[int, tuple[float, int]] = {}     # pid -> (monotonic, ticks)
        self._busy: dict[int, bool] = {}                 # pid -> busy at the last sample
        self._busy_asked: dict[int, bool] = {}           # pid -> busy when rcmon was last asked
        self._locks_mtime = 0.0
        self._queue_mtime = 0.0
        self._titles: dict[str, str] = {}
        self._token: str | None = None
        self._seen: dict[str, tuple[str, float]] = {}    # agent key -> (group, since)
        self._notify: list = []
        self.load_cache()
        if not self.agents:
            self.fetch()

    # -- the cache file ------------------------------------------------------------

    def load_cache(self) -> None:
        try:
            with open(CACHE) as fh:
                d = json.load(fh)
            self.agents = [Agent(**a) for a in d.get("agents", [])]
            self.mrs = [MR(**m) for m in d.get("mrs", [])]
            self.at, self.mrs_at = float(d.get("at", 0)), float(d.get("mrs_at", 0))
            self.mrs_via, self.queue_text = d.get("mrs_via", ""), d.get("queue_text", "")
        except (OSError, ValueError, TypeError):
            pass

    def save_cache(self) -> None:
        try:
            os.makedirs(core.RUN_DIR, exist_ok=True)
            with open(f"{CACHE}.tmp", "w") as fh:
                json.dump({"at": self.at, "mrs_at": self.mrs_at, "mrs_via": self.mrs_via,
                           "queue_text": self.queue_text, "agents": [a.dict() for a in self.agents],
                           "mrs": [m.dict() for m in self.mrs]}, fh)
            os.replace(f"{CACHE}.tmp", CACHE)
        except OSError as err:
            core.log(f"agents: {err!r}")

    # -- counts for the strip ------------------------------------------------------

    @property
    def stale(self) -> bool:
        return not self.at or time.time() - self.at > 15 * 60

    def count(self, group: str) -> int:
        return sum(1 for a in self.agents if a.group == group)

    @property
    def red(self) -> int:
        return sum(1 for m in self.mrs if (m.pipeline or "").lower() == "failed")

    # -- the edge watch (main loop) ----------------------------------------------------

    def watch(self, notify) -> None:
        from gi.repository import GLib

        self._notify.append(notify)
        if not self.watching:
            self.watching = True
            GLib.timeout_add_seconds(TICK_S, self._tick)

    def changed(self) -> None:
        for cb in self._notify:
            cb()

    def _tick(self) -> bool:
        now = time.monotonic()
        edge = self._edges(now)
        since = now - self._asked
        if self.open:
            due = since >= TICK_S - 0.5
        else:
            self._pending = self._pending or edge
            due = (self._pending and since >= EDGE_GAP_S) or since >= FLOOR_S
        if due:
            self.fetch()
        if self.open and self.read_queue():
            self.changed()
        return True

    def _edges(self, now: float) -> bool:
        """Did a claude go quiet or busy, end, or start since rcmon was last asked?"""
        edge = False
        try:
            m = os.stat(LOCKS_DIR).st_mtime
            if m != self._locks_mtime:
                edge = self._locks_mtime != 0.0
                self._locks_mtime = m
        except OSError:
            pass
        for pid in [a.pid for a in self.agents if a.pid and not a.remote]:
            try:
                with open(f"/proc/{pid}/stat") as fh:
                    f = fh.read().rsplit(")", 1)[1].split()
                ticks = int(f[11]) + int(f[12])
            except (OSError, IndexError, ValueError):
                if pid in self._cpu:  # it ended
                    del self._cpu[pid]
                    edge = True
                continue
            last = self._cpu.get(pid)
            self._cpu[pid] = (now, ticks)
            if last is None or now - last[0] < 1:
                continue
            busy = (ticks - last[1]) / (now - last[0]) >= BUSY_TICKS_PER_S
            # Two samples alike before it counts: one busy second is not a turn.
            if busy == self._busy.get(pid) and busy != self._busy_asked.get(pid, busy):
                edge = True
            self._busy[pid] = busy
        return edge

    # -- asking ------------------------------------------------------------------------

    def fetch(self, wait: bool = False) -> None:
        """Ask rcmon (on a thread; wait=True: here, for `bardeck panel`)."""
        if self.fetching:
            return
        self.fetching = True
        self._asked = time.monotonic()
        self._pending = False
        self._busy_asked = dict(self._busy)
        if wait:
            self._fetch()
        else:
            threading.Thread(target=self._fetch, daemon=True).start()

    def token(self) -> str:
        if self._token is None:
            self._token = ""
            for line in core.read(RCMON_ENV).splitlines():
                if line.startswith("RCMON_TOKEN="):
                    self._token = line.split("=", 1)[1].strip().strip("'\"")
        return self._token

    def get(self, path: str):
        req = urllib.request.Request(f"{RCMON}{path}", headers={"Authorization": f"Bearer {self.token()}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.load(resp)

    def _fetch(self) -> None:
        try:
            try:
                state = self.get("/api/state")
                mrs = self.get("/api/mrs")
            except Exception as err:
                self.up = False
                reason = getattr(err, "reason", err)
                self.error = "not running" if isinstance(reason, ConnectionRefusedError) else str(reason)
                if core.TRACE:
                    core.log(f"agents: rcmon: {err!r}")
                now = time.monotonic()
                if now - self._glab_at >= (GLAB_OPEN_S if self.open else GLAB_STRIP_S):
                    self._glab_at = now
                    self.glab_mrs()
                return
            self.take(state, mrs)
            self.up, self.error = True, ""
            self.save_cache()
        finally:
            self.fetching = False
            if self.watching:
                from gi.repository import GLib

                GLib.idle_add(lambda: self.changed() or False)

    def take(self, state: dict, mrs: dict) -> None:
        now = time.time()
        merged = {w.get("name"): (w.get("lifecycle") or {}).get("state") for w in state.get("worktrees") or []}
        jobs_done = {t for t, s in ((state.get("slotq") or {}).get("live_jobs") or {}).items() if s == "done"}
        agents = []
        for inst in state.get("claude_instances") or []:
            pane = inst.get("pane_status") or {}
            status = pane.get("status") or "unknown"
            group, words, tone = PANE.get(status, ("idle", status.replace("_", " "), "dim"))
            ticket = inst.get("issue") if TICKET.fullmatch(inst.get("issue") or "") else ""
            subs = (inst.get("subagents") or {}).get("working") or 0
            if group == "idle" and subs:
                group, words, tone = "working", f"{subs} subagent{'s' * (subs > 1)}", "ok"
            elif group == "idle" and (merged.get(inst.get("workspace")) == "merged" or ticket in jobs_done):
                group, words, tone = "done", "done", "dim"
            target = inst.get("tmux_target") or ""
            session = inst.get("tmux_session") or target.split(":")[0]
            key = f"{inst.get('host') or ''}/{inst.get('workspace')}"
            # How long in this state: a turn's spinner says it; a stop is the
            # transcript's last write; else since the bar first saw it so.
            last = inst.get("last_activity_ts")
            run = spinner_secs(pane.get("spinner_detail", "")) if status == "working" else None
            seen = self._seen.get(key)
            if run is not None:
                since = now - run
            elif group in ("waiting", "idle", "done", "error") and last:
                since = float(last)
            elif seen and seen[0] == group:
                since = seen[1]
            else:
                since = now
            self._seen[key] = (group, since)
            if pane.get("question_prompt") and pane.get("question_text"):
                detail = pane["question_text"]
            elif pane.get("error_text"):
                detail = pane["error_text"]
            else:
                tool = inst.get("progress_tool") or ""
                detail = f"{tool}: {inst.get('progress_text') or ''}" if tool else inst.get("progress_text") or ""
            cwd = inst.get("cwd") or ""
            where = "home" if cwd.rstrip("/") in ("~", REAL_HOME) else os.path.basename(cwd.rstrip("/")) or inst.get("workspace")
            agents.append(Agent(
                key=key, session=session, target=target, host=inst.get("host"), ticket=ticket,
                title=self.title(ticket), status=status, group=group, words=words, tone=tone, since=since,
                detail=" ".join(str(detail).split()), slot=inst.get("slot"), where=where,
                pid=inst.get("claude_pid") or inst.get("pid")))
        agents.sort(key=lambda a: (GROUP_ORDER.get(a.group, 9), a.slot if a.slot is not None else 99,
                                   a.session or ""))
        out = []
        for m in mrs.get("mrs") or []:
            t = TICKET.search(m.get("title") or "") or TICKET.search(m.get("source_branch") or "")
            out.append(MR(iid=m.get("iid"), title=re.sub(r"^\s*\[[A-Z]+-\d+\]\s*", "", m.get("title") or ""),
                          url=m.get("web_url") or f"{MR_URL}{m.get('iid')}", ticket=t.group(1).upper() if t else "",
                          pipeline=m.get("pipeline_status"), draft=bool(m.get("draft")),
                          approved=m.get("approved"), unresolved=m.get("unresolved") or 0,
                          threads_open=not m.get("threads_resolved", True), conflicts=bool(m.get("has_conflicts"))))
        out.sort(key=lambda m: -(m.iid or 0))
        q = state.get("slotq") or {}
        self.agents, self.at = agents, now
        if mrs.get("warm", True):
            self.mrs, self.mrs_at, self.mrs_via = out, float(mrs.get("cached_at") or now), "rcmon"
        self.queue_text = q.get("text", "") if q.get("show", True) else ""
        self.runner_on = (q.get("runner") or {}).get("running")

    def glab_mrs(self) -> None:
        """rcmon is down: Tomek's open MRs straight from GitLab (GET only, real HOME)."""
        env = dict(os.environ, HOME=REAL_HOME)

        def api(path: str):
            r = subprocess.run(["glab", "api", "--hostname", GITLAB_HOST, path], env=env, capture_output=True,
                               text=True, timeout=10, stdin=subprocess.DEVNULL)
            return json.loads(r.stdout) if r.returncode == 0 else None

        try:
            listed = api(f"projects/{GITLAB_PROJECT}/merge_requests?state=opened"
                         f"&author_username={GITLAB_USER}&per_page=30")
            if not isinstance(listed, list):
                return
            out = []
            for m in listed:
                one = api(f"projects/{GITLAB_PROJECT}/merge_requests/{m['iid']}") or {}
                t = TICKET.search(m.get("title") or "") or TICKET.search(m.get("source_branch") or "")
                out.append(MR(iid=m["iid"], title=re.sub(r"^\s*\[[A-Z]+-\d+\]\s*", "", m.get("title") or ""),
                              url=m.get("web_url"), ticket=t.group(1).upper() if t else "",
                              pipeline=(one.get("head_pipeline") or {}).get("status"), draft=bool(m.get("draft")),
                              approved=m.get("detailed_merge_status") not in ("not_approved", None),
                              unresolved=0, threads_open=not m.get("blocking_discussions_resolved", True),
                              conflicts=bool(m.get("has_conflicts"))))
            self.mrs, self.mrs_at, self.mrs_via = out, time.time(), "glab"
            self.save_cache()
        except (OSError, ValueError, subprocess.SubprocessError) as err:
            core.log(f"agents: glab: {err!r}")

    def title(self, ticket: str) -> str:
        """The ticket's title from cmon's Linear cache, read once."""
        if not ticket:
            return ""
        if ticket not in self._titles:
            try:
                with open(f"{ISSUES_DIR}/{ticket}.json") as fh:
                    self._titles[ticket] = ((json.load(fh).get("linear_data") or {}).get("title") or "").strip()
            except (OSError, ValueError, AttributeError):
                return ""  # not cached yet: ask again next time
        return self._titles[ticket]

    # -- the queue -----------------------------------------------------------------------

    def read_queue(self) -> bool:
        """slotq's jobs, when its state file changed. True = they changed."""
        try:
            m = os.stat(SLOTQ_STATE).st_mtime
        except OSError:
            self.slotq, self.jobs = False, []
            return False
        self.slotq = True
        if m == self._queue_mtime:
            return False
        self._queue_mtime = m
        try:
            with open(SLOTQ_STATE) as fh:
                raw = json.load(fh).get("jobs") or []
        except (OSError, ValueError):
            return False
        now = time.time()
        jobs = []
        for j in raw:
            state = j.get("state") or "?"
            if state == "done" and now - float(j.get("done_at") or j.get("updated_at") or 0) > DONE_SHOWN_S:
                continue
            ticket = j.get("ticket") or ""
            jobs.append(Job(ticket=ticket, state=state, slot=j.get("slot"), mr=j.get("mr_iid"),
                            note=" ".join((j.get("note") or "").split()), title=self.title(ticket),
                            at=float(j.get("updated_at") or j.get("enqueued_at") or 0)))
        jobs.sort(key=lambda j: (JOB.get(j.state, (9,))[0], -j.at))
        self.jobs = jobs
        return True

    # -- acting --------------------------------------------------------------------------

    @staticmethod
    def attach(a: Agent) -> None:
        """A terminal on the agent's tmux pane, as cmon's `A` does it (monitor_mixin
        _attach_tmux, the window route): `=` makes tmux match the session's name
        exactly; the window and pane after it are made current, as cmon's attach to
        a session shows the agent's own window."""
        target = a.target or a.session
        target = f"={target}" if target and not target.startswith("=") else target
        cmd = f"tmux attach -t {shlex.quote(target)}"
        if a.remote:
            cmd = f"ssh -t {shlex.quote(a.host)} {shlex.quote(cmd)}"
        core.spawn([os.environ.get("TERMINAL") or "alacritty", "-e", "bash", "-c", cmd])


# ── the strip ────────────────────────────────────────────────────────────────


class AgentsStrip:
    """A robot (filled while one works) and how many work; an amber badge with the
    ones waiting for Tomek; a red dot on the robot when an MR's pipeline failed."""

    name = "agents"

    def __init__(self, m: Agents):
        self.m = m

    def watch(self, notify) -> None:
        self.m.watch(notify)

    def key(self, variant: str):
        m = self.m
        return bool(m.at), m.stale, m.count("working"), m.count("waiting") + m.count("error"), m.red

    def draw(self, variant: str, scale: int):
        m = self.m
        c = core.StripCanvas(scale)
        working, waiting, red = m.count("working"), m.count("waiting") + m.count("error"), m.red
        x0 = c.x
        if not m.at:
            c.icon(GLYPH_ROBOT_IDLE, "dim", 15, after=2)
            c.text("?", "dim", 12)
        else:
            tone = "dim" if m.stale else "fg"
            c.icon(GLYPH_ROBOT if working else GLYPH_ROBOT_IDLE, tone, 15, after=2)
            if working and not (waiting and variant == "compact"):
                c.text(str(working), "dim" if m.stale else "fg2", 13)
            if waiting:
                c.gap(4 if working and variant != "compact" else 1)
                tone = "hit" if m.count("error") and not m.count("waiting") else "warn"
                tone = "bg3" if m.stale else tone  # an old answer: maybe no longer so
                c.x += badge(c.cr, c.x, core.MID, str(waiting), tone)
        if red and m.at:
            # The dot sits on the robot's shoulder, in a ring of the pill's colour.
            cx, cy = x0 + 15, core.MID - 6
            c.cr.new_path()
            c.cr.arc(cx, cy, 4, 0, 6.3)
            c.cr.set_source_rgba(*rgba("bg"))
            c.cr.fill()
            c.cr.arc(cx, cy, 2.8, 0, 6.3)
            c.cr.set_source_rgba(*rgba("hit"))
            c.cr.fill()
        return c.finish()


# ── the panel ────────────────────────────────────────────────────────────────


class AgentsPanel(Panel):
    """AGENTS, QUEUE, MRS: one row each, a keyboard selection across all three."""

    name = "agents"
    live = 1.0  # the durations tick on; new data comes with an invalidate
    W = 640
    P = 16
    SECTIONS = ("agents", "queue", "mrs")
    ROWS = {"agents": 9, "queue": 5, "mrs": 7}
    ROW_H = {"agents": 26, "queue": 22, "mrs": 26}
    DETAIL_H = 22

    def __init__(self, m: Agents):
        self.m = m
        self.sel = -1
        self.hovered = -1
        self.tops = {s: 0 for s in self.SECTIONS}
        self.rows: list[tuple[float, float, int]] = []    # (y0, y1, flat index), for hover
        self.zones: list[tuple[float, float, str]] = []   # (y0, y1, section), for the wheel
        self._wheel_y = 0.0  # the pointer's y, from hover: the wheel scrolls the section under it

    # -- the items -------------------------------------------------------------------

    def items(self, section: str) -> list:
        m = self.m
        if section == "agents":
            return m.agents
        if section == "queue":
            return m.jobs
        return m.mrs

    def shown(self) -> list[str]:
        return [s for s in self.SECTIONS if s != "queue" or self.m.slotq]

    def flat(self) -> list[tuple[str, object]]:
        return [(s, it) for s in self.shown() for it in self.items(s)]

    def first(self, section: str) -> int:
        """The flat index of a section's first item."""
        n = 0
        for s in self.shown():
            if s == section:
                return n
            n += len(self.items(s))
        return n

    def section_h(self, s: str) -> float:
        n = len(self.items(s))
        h = 22 + max(1, min(self.ROWS[s], n)) * self.ROW_H[s] + 10
        if n > self.ROWS[s]:
            h += 14  # "n more" under it
        if s == "agents" and n:
            h += self.DETAIL_H
        return h

    def size(self):
        return self.W, 74 + sum(self.section_h(s) for s in self.shown())

    # -- state -----------------------------------------------------------------------

    def opened(self) -> None:
        m = self.m
        m.open = True
        m.read_queue()
        if time.monotonic() - m._asked > 2:
            m.fetch(wait=not m.watching)
        self.sel, self.hovered = -1, -1
        self.tops = {s: 0 for s in self.SECTIONS}

    def closed(self) -> None:
        self.m.open = False

    def follow(self) -> None:
        """Scroll the selected item's section so it shows."""
        flat = self.flat()
        if not 0 <= self.sel < len(flat):
            return
        s = flat[self.sel][0]
        i = self.sel - self.first(s)
        rows, top = self.ROWS[s], self.tops[s]
        if i < top:
            self.tops[s] = i
        elif i >= top + rows:
            self.tops[s] = i - rows + 1

    # -- actions ---------------------------------------------------------------------

    def act(self, section: str, it) -> bool:
        """Click or Enter. True closes the panel (a terminal or the browser opens)."""
        if section == "agents":
            self.m.attach(it)
            return True
        if section == "mrs":
            core.spawn(["xdg-open", it.url])
            return True
        if it.mr:
            mr = next((x for x in self.m.mrs if x.iid == it.mr), None)
            core.spawn(["xdg-open", mr.url if mr else f"{MR_URL}{it.mr}"])
            return True
        if it.slot is not None and it.state == "running":  # a queued job's slot is someone else's yet
            self.m.attach(Agent(session=f"legartis-{it.slot}"))
            return True
        return False

    def refresh(self) -> bool:
        self.m.fetching or self.m.fetch()
        return False

    @staticmethod
    def cmon() -> bool:
        core.spawn(["alacritty", "-e", f"{REAL_HOME}/bin/cmon"])
        return True

    # -- input -----------------------------------------------------------------------

    def key(self, key: str, ctrl: bool):
        flat = self.flat()
        n = len(flat)
        cur = flat[self.sel][0] if 0 <= self.sel < n else None
        half = max(1, self.ROWS[cur or "agents"] // 2)
        if key in ("i", "Down") or (ctrl and key == "n"):
            self.sel = min(n - 1, self.sel + 1)
        elif key in ("o", "Up") or (ctrl and key == "p"):
            self.sel = max(0, self.sel - 1)
        elif key in ("k", "Page_Down") or (ctrl and key == "v"):
            self.sel = min(n - 1, self.sel + half)
        elif key in ("l", "Page_Up"):
            self.sel = max(0, self.sel - half)
        elif key in ("semicolon", "j"):
            secs = [s for s in self.shown() if self.items(s)]
            if not secs:
                return False
            if cur is None:
                to = secs[0] if key == "semicolon" else secs[-1]
            else:
                i = secs.index(cur) + (1 if key == "semicolon" else -1)
                to = secs[i % len(secs)]
            self.sel = self.first(to)
        elif key in ("Return", "KP_Enter") and 0 <= self.sel < n:
            if self.act(*flat[self.sel]):
                return "close"  # a terminal or the browser opened: the Deck makes way for it
        elif key == "r":
            self.refresh()
        elif key == "c":
            return self.cmon() and "close"
        else:
            return False
        self.follow()
        return True

    def hover(self, x: float, y: float) -> bool:
        self._wheel_y = y
        idx = next((i for y0, y1, i in self.rows if y0 <= y < y1 and 0 <= x < self.W), -1)
        if idx != self.hovered:
            self.hovered = idx
            return True
        return False

    def scroll(self, down: bool) -> bool:
        s = next((s for y0, y1, s in self.zones if y0 <= self._wheel_y < y1), "agents")
        n = len(self.items(s))
        top = max(0, min(self.tops[s] + (1 if down else -1), n - self.ROWS[s]))
        if top == self.tops[s]:
            return False
        self.tops[s] = top
        return True

    # -- drawing ---------------------------------------------------------------------

    def draw(self, cr, hits: Hits) -> None:
        m = self.m
        W, P = self.W, self.P
        core.panel_frame(cr, W, self.size()[1])
        y = 12
        working, waiting = m.count("working"), m.count("waiting")
        core.icon(cr, P, y + 11, GLYPH_ROBOT if working else GLYPH_ROBOT_IDLE, 20, "title")
        text(cr, P + 28, y, "Agents", 18, "title", bold=True)

        right = W - P
        cw = self.chip_w(cr, "cmon", GLYPH_CONSOLE)
        button(cr, hits, right - cw, y + 1, "cmon", self.cmon, h=22, size=11, glyph=GLYPH_CONSOLE)
        right -= cw + 8
        label = "asking" if m.fetching else "refresh"
        cw = self.chip_w(cr, label, GLYPH_REFRESH)
        button(cr, hits, right - cw, y + 1, label, self.refresh, h=22, size=11, glyph=GLYPH_REFRESH,
               on=m.fetching, tone="bg3")
        y += 28

        # What the board says, in words.
        x = P + 28
        parts = [] if m.at else [("nothing read yet", "dim", False)]
        if waiting:
            parts.append((f"{waiting} waiting for you", "warn", True))
        if m.count("error"):
            parts.append((f"{m.count('error')} stuck", "hit", True))
        if m.at:
            parts.append((f"{working} working", "fg2", False))
        idle = m.count("idle")
        if idle:
            parts.append((f"{idle} idle", "dim", False))
        if m.count("done"):
            parts.append((f"{m.count('done')} done", "dim", False))
        for i, (words, tone, bold) in enumerate(parts):
            if i:
                x += text(cr, x, y, " · ", 12, "dim")
            x += text(cr, x, y, words, 12, tone, bold=bold)
        age = time.time() - m.at if m.at else None
        if not m.up and m.error:
            words = f"rcmon: {m.error}" + (f" · as of {ago(age)} ago" if age is not None else "")
            text(cr, W - P, y, words, 11, "hit", align=1, width=W - P - x - 12)
        elif age is not None:
            text(cr, W - P, y, f"rcmon · {ago(age)} ago", 11, "dim", align=1)
        y += 28

        cr.rectangle(P, y - 6, W - 2 * P, 1)
        cr.set_source_rgba(*rgba("bg2"))
        cr.fill()
        y += 6
        self.rows, self.zones = [], []
        flat_at = 0
        for s in self.shown():
            y0 = y
            y = self.draw_section(cr, hits, s, y, flat_at)
            self.zones.append((y0, y, s))
            flat_at += len(self.items(s))

    def draw_section(self, cr, hits: Hits, s: str, y: float, flat_at: int) -> float:
        m = self.m
        W, P = self.W, self.P
        end = y + self.section_h(s)
        items = self.items(s)
        if s == "agents":
            title, note, tone = "agents", f"{len(items)} sessions" if items else "", "dim"
        elif s == "queue":
            title, note = "queue", m.queue_text or (f"{len(items)} jobs" if items else "")
            tone = "warn" if m.runner_on is False else "dim"
            if m.runner_on is False and "runner" not in note.lower():
                note = f"{note} · runner off".strip(" ·")
        else:
            title, tone = "merge requests", "dim"
            via = f" via {m.mrs_via}" if m.mrs_via == "glab" else ""
            note = f"{len(items)} open · read {ago(time.time() - m.mrs_at)} ago{via}" if m.mrs_at else ""
        nw = text(cr, W - P, y - 1, note, 11, tone, align=1, width=W * 0.6) + 10 if note else 0
        heading(cr, P, y, title, W - 2 * P - nw)
        y += 22
        if not items:
            asking = f"rcmon is not answering ({m.error})" if m.error else "asking rcmon…"
            empty = {"agents": "no agents" if m.at else asking, "queue": "nothing queued",
                     "mrs": "no open MRs" if m.mrs_at else "not read yet"}[s]
            text(cr, P + 4, y + self.ROW_H[s] / 2, empty, 12, "dim", valign=0.5)
            return end
        rows, rh = self.ROWS[s], self.ROW_H[s]
        top = self.tops[s] = max(0, min(self.tops[s], len(items) - rows))
        now = time.time()
        draw_row = {"agents": self.draw_agent, "queue": self.draw_job, "mrs": self.draw_mr}[s]
        for i, it in enumerate(items[top:top + rows], start=top):
            idx = flat_at + i
            picked = idx == self.sel or idx == self.hovered
            self.draw_pick(cr, y, rh, idx, picked)
            hits.add(P - 6, y, W - 2 * P + 12, rh, lambda s=s, it=it: self.act(s, it))
            draw_row(cr, y, rh, it, picked, now)
            self.rows.append((y, y + rh, idx))
            y += rh
        more = len(items) - top - rows
        if len(items) > rows:
            words = f"▾ {more} more · scroll" if more > 0 else f"▴ {top} above"
            text(cr, W / 2, y + 1, words, 10, "dim", align=0.5)
            y += 14
        if s == "agents":
            self.draw_detail(cr, y + 2, flat_at)
        return end

    def draw_pick(self, cr, y: float, h: float, idx: int, picked: bool) -> None:
        if not picked:
            return
        x0, rw = self.P - 6, self.W - 2 * self.P + 12
        core.rrect(cr, x0, y + 1, rw, h - 2, 7)
        cr.set_source_rgba(*rgba("bg1"))
        cr.fill()
        if idx == self.sel:  # the keyboard's mark: a bar at the left edge
            core.rrect(cr, x0 + 1, y + 6, 3, h - 12, 1.5)
            cr.set_source_rgba(*rgba("accent"))
            cr.fill()

    def chip(self, cr, x_right: float, mid: float, label: str, tone: str = "dim") -> float:
        """A small outlined tag ending at x_right. Returns its width."""
        tw = core.text_w(cr, label, 9)
        w = tw + 8
        core.rrect(cr, x_right - w + 0.5, mid - 7.5, w - 1, 14, 4)
        cr.set_source_rgba(*rgba("bg2" if tone == "dim" else tone))
        cr.set_line_width(1)
        cr.stroke()
        text(cr, x_right - w + 4, mid, label, 9, tone, valign=0.5)
        return w

    def draw_agent(self, cr, y: float, h: float, a: Agent, picked: bool, now: float) -> None:
        P, W = self.P, self.W
        mid = y + h / 2
        cr.new_path()  # a text's move_to leaves a current point: the arc would draw a line from it
        cr.arc(P + 4, mid, 4, 0, 6.3)
        cr.set_source_rgba(*rgba(GROUP_DOT.get(a.group, "bg3")))
        cr.fill()
        # Right to left: where it runs, how long, its state.
        right = W - P
        where = f"slot {a.slot}" if a.slot is not None else (a.where or "")
        if a.remote:
            where = f"{a.host} · {where}" if where else a.host
        if where:  # a column of its own, so the durations and states line up
            self.chip(cr, right, mid, where[:12])
        right -= 70
        text(cr, right, mid, ago(now - a.since) if a.since else "", 10, "dim", align=1, valign=0.5)
        right -= 36
        bold = a.group in ("waiting", "error")
        right -= text(cr, right, mid, a.words, 11, a.tone, align=1, valign=0.5, bold=bold) + 10
        if a.group == "waiting":
            core.icon(cr, right, mid, GLYPH_HAND, 13, "warn", align=1)
            right -= 20
        x = P + 16
        name_tone = "title" if picked or a.group == "waiting" else "fg2"
        x += text(cr, x, mid, a.session or "?", 13, name_tone, bold=a.group == "waiting", valign=0.5,
                  width=118) + 10
        x = max(x, P + 16 + 128)
        if a.ticket:
            x += text(cr, x, mid, a.ticket, 11, "dim", valign=0.5) + 6
        rest = a.title or ("" if a.ticket else (a.detail or ""))
        if rest and right - x > 30:
            text(cr, x, mid, rest, 12, "fg" if a.title else "dim", valign=0.5, width=right - x - 8)

    def draw_detail(self, cr, y: float, flat_at: int) -> None:
        """The picked agent's last words (what it asks, or what it did last); with
        none picked, the first waiting one's."""
        P, W = self.P, self.W
        agents = self.m.agents
        idx = self.hovered if 0 <= self.hovered - flat_at < len(agents) else self.sel
        a = agents[idx - flat_at] if 0 <= idx - flat_at < len(agents) else next(
            (x for x in agents if x.group == "waiting"), None)
        mid = y + self.DETAIL_H / 2 - 2
        if a is None or not a.detail:
            words = "click or Enter: a terminal on its tmux session · i/o pick · j/; a section · c cmon"
            text(cr, W / 2, mid, words, 10, "dim", align=0.5, valign=0.5)
            return
        label = f"{a.session}:"
        x = P + 16 + text(cr, P + 16, mid, label, 11, a.tone if a.group == "waiting" else "dim", bold=True,
                          valign=0.5) + 6
        text(cr, x, mid, a.detail, 11, "fg", valign=0.5, width=W - P - x)

    def draw_job(self, cr, y: float, h: float, j: Job, picked: bool, now: float) -> None:
        P, W = self.P, self.W
        mid = y + h / 2
        _order, words, tone = JOB.get(j.state, (9, j.state, "dim"))
        x = P + 4
        text(cr, x, mid, j.ticket or "?", 11, "title" if picked else "fg2", bold=True, valign=0.5)
        x += 74
        text(cr, x, mid, words, 11, tone, valign=0.5, bold=j.state in ("running", "failed", "blocked"))
        x += 62
        right = W - P
        right -= text(cr, right, mid, ago(now - j.at) if j.at else "", 10, "dim", align=1, valign=0.5) + 10
        if j.slot is not None:
            right -= self.chip(cr, right, mid, f"slot {j.slot}", "ok" if j.state == "running" else "dim") + 6
        if j.mr:
            right -= text(cr, right, mid, f"!{j.mr}", 11, "dim", align=1, valign=0.5) + 8
        shout = j.state in ("blocked", "failed") and j.note
        rest = j.note if shout else (j.title or j.note)
        if rest and right - x > 30:
            text(cr, x, mid, rest, 11, tone if shout else "fg", valign=0.5, width=right - x - 6)

    def draw_mr(self, cr, y: float, h: float, mr: MR, picked: bool, now: float) -> None:
        P, W = self.P, self.W
        mid = y + h / 2
        words, tone = PIPELINE.get((mr.pipeline or "").lower(), ("no pipeline", "dim"))
        cr.new_path()
        cr.arc(P + 4, mid, 4, 0, 6.3)
        cr.set_source_rgba(*rgba(tone if tone != "dim" else "bg3"))
        cr.fill()
        # Right to left: the pipeline, the threads, approved, the tags.
        right = W - P
        text(cr, right, mid, words, 11, tone, align=1, valign=0.5, bold=tone == "hit")
        right -= 66
        if mr.unresolved or mr.threads_open:
            label = str(mr.unresolved) if mr.unresolved else "!"
            tw = text(cr, right, mid, label, 11, "warn", align=1, valign=0.5, bold=True)
            core.icon(cr, right - tw - 3, mid, GLYPH_THREAD, 12, "warn", align=1)
        right -= 34
        if mr.approved:
            core.icon(cr, right, mid, GLYPH_CHECK, 12, "ok", align=1)
        right -= 22
        if mr.conflicts:
            right -= self.chip(cr, right, mid, "conflict", "hit") + 6
        if mr.draft:
            right -= self.chip(cr, right, mid, "draft") + 6
        x = P + 16
        x += text(cr, x, mid, f"!{mr.iid}", 11, "title" if picked else "fg2", bold=True, valign=0.5) + 8
        if mr.ticket:
            x += text(cr, x, mid, mr.ticket, 11, "dim", valign=0.5) + 6
        text(cr, x, mid, mr.title or "", 12, "title" if picked else "fg", valign=0.5, width=right - x - 6)

    @staticmethod
    def chip_w(cr, label: str, glyph: str) -> float:
        return core.text_w(cr, label, 11) + core.text_w(cr, glyph, 13, family=core.ICON_FONT) + 23
