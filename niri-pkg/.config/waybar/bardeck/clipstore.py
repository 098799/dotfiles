"""The clipboard history's store, in ~/.local/state/bardeck/clip/.

There is no cliphist here. clip.py keeps ONE `wl-paste --watch` running, and
wl-paste runs this file for every new selection, with the content on stdin:

    wl-paste --watch python3 -I .../bardeck/clipstore.py store

Standard library only (and Pillow for an image's thumbnail), so a copy costs one
short process (~30 ms): no cairo, no GTK. The panel (clip.py) reads the same index
and changes it (pin, remove, clear) through the functions below; a lock file keeps
the two from writing at once.

What is kept: text, and images (as files, with a thumbnail). Not kept: anything a
password manager marks (wl-paste says CLIPBOARD_STATE=sensitive when the offer
has x-kde-passwordManagerHint; the types are checked too), an empty clipboard,
whitespace, and anything over MAX_BYTES. A copy that is already in the history
moves to the top. The newest KEEP entries stay, and every pinned one besides.

    index.json      newest first: [{id, kind, mime, ts, pinned, size, head | w, h}]
    <id>.txt        a text, as copied (bytes)
    <id>.img        an image, as copied; <id>.thumb.png its thumbnail
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import pwd
import subprocess
import sys
import time

REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir
DIR = os.environ.get("BARDECK_CLIP_DIR") or f"{REAL_HOME}/.local/state/bardeck/clip"
KEEP = 200
MAX_BYTES = 5 * 1024 * 1024
HEAD = 2000  # characters of a text kept in the index: its preview, and what a search sees
THUMB = (360, 120)  # the thumbnail's box in pixels (the panel shows it at half: 2x screens)
TEXT_TYPES = ("text/plain;charset=utf-8", "text/plain", "UTF8_STRING", "STRING", "TEXT")
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp")
SECRET = "x-kde-passwordManagerHint"


def path(name: str) -> str:
    return os.path.join(DIR, name)


@contextlib.contextmanager
def locked():
    os.makedirs(DIR, exist_ok=True)
    with open(path("lock"), "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def load() -> list[dict]:
    try:
        with open(path("index.json")) as fh:
            entries = json.load(fh)
        return entries if isinstance(entries, list) else []
    except (OSError, ValueError):
        return []


def save(entries: list[dict]) -> None:
    tmp = path("index.json.tmp")
    with open(tmp, "w") as fh:
        json.dump(entries, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path("index.json"))


def files(e: dict) -> list[str]:
    if e.get("kind") == "image":
        return [path(f"{e['id']}.img"), path(f"{e['id']}.thumb.png")]
    return [path(f"{e['id']}.txt")]


def data_file(e: dict) -> str:
    return files(e)[0]


def _unlink(e: dict) -> None:
    for f in files(e):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(f)


def prune(entries: list[dict]) -> list[dict]:
    """Every pinned entry, and the newest KEEP of the others; the rest's files go."""
    out, kept = [], 0
    for e in entries:
        if e.get("pinned") or kept < KEEP:
            kept += not e.get("pinned")
            out.append(e)
        else:
            _unlink(e)
    return out


def text_head(data: bytes) -> str:
    return data[:HEAD * 4].decode("utf-8", errors="replace")[:HEAD]


def thumbnail(src: str, dst: str) -> tuple[int, int]:
    """Write dst (PNG, inside THUMB); return the image's own size. (0, 0): unreadable."""
    try:
        from PIL import Image
    except ImportError:
        return 0, 0
    try:
        with Image.open(src) as im:
            size = im.size
            im.thumbnail(THUMB)
            im.convert("RGBA").save(dst, "PNG")
        return size
    except Exception:
        return 0, 0


def add(data: bytes, kind: str, mime: str, now: float | None = None) -> dict | None:
    """Put a copy on top of the history. None when it is not kept."""
    if not data or len(data) > MAX_BYTES or (kind == "text" and not data.strip()):
        return None
    now = time.time() if now is None else now
    ident = hashlib.sha1(kind.encode() + b"\0" + data).hexdigest()[:16]
    with locked():
        entries = load()
        old = next((e for e in entries if e.get("id") == ident), None)
        if old is not None:
            entries.remove(old)
            old["ts"] = now
            entries.insert(0, old)
            save(entries)
            return old
        e = {"id": ident, "kind": kind, "mime": mime, "ts": now, "pinned": False, "size": len(data)}
        with open(data_file(e), "wb") as fh:
            fh.write(data)
        if kind == "text":
            e["head"] = text_head(data)
        else:
            e["w"], e["h"] = thumbnail(data_file(e), path(f"{ident}.thumb.png"))
        entries.insert(0, e)
        save(prune(entries))
        return e


def change(ident: str, **fields) -> None:
    with locked():
        entries = load()
        for e in entries:
            if e.get("id") == ident:
                e.update(fields)
        save(prune(entries))


def remove(ident: str) -> None:
    with locked():
        entries = load()
        for e in [e for e in entries if e.get("id") == ident]:
            _unlink(e)
            entries.remove(e)
        save(entries)


def clear() -> None:
    """Everything but the pinned entries."""
    with locked():
        entries = load()
        for e in entries:
            if not e.get("pinned"):
                _unlink(e)
        save([e for e in entries if e.get("pinned")])


def choose(types: list[str]) -> tuple[str, str] | None:
    """(kind, mime) to keep from what the selection offers, or None. Text first: a
    browser's "copy" offers text/html too, and its "copy image" image/png and HTML."""
    if SECRET in types:
        return None
    for t in TEXT_TYPES:
        if t in types:
            return "text", t
    for t in IMAGE_TYPES:
        if t in types:
            return "image", t
    return next((("image", t) for t in types if t.startswith("image/")), None)


def _wl_paste(*args: str, limit: int = MAX_BYTES + 1) -> bytes:
    try:
        with subprocess.Popen(["wl-paste", *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL) as p:
            data = p.stdout.read(limit)
            p.kill()
            return data
    except OSError:
        return b""


def store(stdin, state: str, types: list[str] | None = None) -> dict | None:
    """One new selection: what wl-paste --watch gives its command."""
    if state != "data":  # nil, clear, or sensitive (a password)
        return None
    if types is None:
        types = _wl_paste("--list-types", limit=65536).decode(errors="replace").split("\n")
    pick = choose([t.strip() for t in types if t.strip()])
    if pick is None:
        return None
    kind, mime = pick
    if kind == "text":
        # wl-paste picks a text type for stdin when one is offered (it prefers
        # text/plain): the text is already here.
        data = stdin.read(MAX_BYTES + 1)
    else:
        stdin.close()  # what wl-paste chose for stdin may be text/html: ask for the image
        data = _wl_paste("--type", mime)
    if len(data) > MAX_BYTES:
        return None
    return add(data, kind, mime)


if __name__ == "__main__":
    if sys.argv[1:] == ["store"]:
        store(sys.stdin.buffer, os.environ.get("CLIPBOARD_STATE", "data"))
    else:
        sys.exit(f"usage: {sys.argv[0]} store   (run by wl-paste --watch; see clip.py)")
