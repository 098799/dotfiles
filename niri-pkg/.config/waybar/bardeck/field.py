"""A one-line text field with a caret and the readline / Emacs keys, for a panel that
types (the palette's field).

  move     Left / Right or Ctrl+b / Ctrl+f a character; Alt+b / Alt+f, Ctrl+Left /
           Ctrl+Right or Alt+Left / Alt+Right a word; Home / End or Ctrl+a / Ctrl+e
           the line
  delete   BackSpace or Ctrl+h back, Delete or Ctrl+d forward
  kill     Ctrl+k to the end, Ctrl+u to the start, Alt+d / Ctrl+Delete a word forward,
           Alt+BackSpace / Ctrl+BackSpace a word back, Ctrl+w back to the last space
           (a whole "word" with its dashes and slashes, as in a shell)
  yank     Ctrl+y puts back the last kill (Line.yank; the panel decides what Ctrl+y
           does when nothing was killed)
  other    Ctrl+t swaps the two characters at the caret, Ctrl+/ or Ctrl+_ or Ctrl+z undo

A word is a run of letters, digits and underscores, as readline's Alt+b / Alt+f have it.
"""

from __future__ import annotations

import re

WORD = re.compile(r"\w+")


class Line:
    def __init__(self) -> None:
        self.text = ""
        self.pos = 0       # the caret: characters before it
        self.killed = ""   # the last kill, for Ctrl+y
        self.undos: list[tuple[str, int]] = []
        self.typing_run = False  # the last change typed a character: typing undoes as one step

    def set(self, text: str) -> None:
        self.text, self.pos, self.undos, self.typing_run = text, len(text), [], False

    # -- the caret ---------------------------------------------------------------

    def word_left(self) -> int:
        starts = [m.start() for m in WORD.finditer(self.text) if m.start() < self.pos]
        return starts[-1] if starts else 0

    def word_right(self) -> int:
        m = next((m for m in WORD.finditer(self.text) if m.end() > self.pos), None)
        return m.end() if m else len(self.text)

    def space_left(self) -> int:
        """Ctrl+w's start: back over spaces, then over everything that is not one."""
        i = self.pos
        while i > 0 and self.text[i - 1].isspace():
            i -= 1
        while i > 0 and not self.text[i - 1].isspace():
            i -= 1
        return i

    # -- changes -----------------------------------------------------------------

    def remember(self, typing: bool = False) -> None:
        if not (typing and self.typing_run):
            self.undos.append((self.text, self.pos))
            del self.undos[:-100]
        self.typing_run = typing

    def insert(self, s: str, typing: bool = False) -> None:
        if not s:
            return
        self.remember(typing)
        self.text = self.text[:self.pos] + s + self.text[self.pos:]
        self.pos += len(s)

    def delete(self, a: int, b: int, kill: bool = False) -> bool:
        """Remove text[a:b]; a kill keeps it for Ctrl+y. False when there was nothing."""
        a, b = max(0, min(a, b)), min(len(self.text), max(a, b))
        if a == b:
            return False
        self.remember()
        if kill:
            self.killed = self.text[a:b]
        self.text = self.text[:a] + self.text[b:]
        self.pos = a
        return True

    def yank(self) -> bool:
        if not self.killed:
            return False
        self.insert(self.killed)
        return True

    def transpose(self) -> bool:
        """Ctrl+t: the character before the caret goes after the next one (at the end of
        the line: the last two swap)."""
        i = min(max(self.pos, 1), len(self.text) - 1)
        if i < 1:
            return False
        self.remember()
        t = self.text
        self.text = t[:i - 1] + t[i] + t[i - 1] + t[i + 1:]
        self.pos = i + 1
        return True

    def undo(self) -> bool:
        if not self.undos:
            return False
        self.text, self.pos = self.undos.pop()
        self.typing_run = False
        return True

    # -- keys --------------------------------------------------------------------

    def key(self, key: str, char: str, ctrl: bool, alt: bool) -> bool | None:
        """One key. None: not a field key; False: the caret moved (the text is the same);
        True: the text changed."""
        n, pos = len(self.text), self.pos
        word = ctrl or alt
        if key in ("Left", "KP_Left") or (ctrl and key == "b"):
            self.pos = self.word_left() if word and key != "b" else max(0, pos - 1)
        elif key in ("Right", "KP_Right") or (ctrl and key == "f"):
            self.pos = self.word_right() if word and key != "f" else min(n, pos + 1)
        elif alt and key == "b":
            self.pos = self.word_left()
        elif alt and key == "f":
            self.pos = self.word_right()
        elif key in ("Home", "KP_Home") or (ctrl and key == "a"):
            self.pos = 0
        elif key in ("End", "KP_End") or (ctrl and key == "e"):
            self.pos = n
        elif key == "BackSpace" and word:
            return self.delete(self.word_left(), pos, kill=True)
        elif key == "BackSpace" or (ctrl and key == "h"):
            return self.delete(pos - 1, pos)
        elif key in ("Delete", "KP_Delete") and word or (alt and key == "d"):
            return self.delete(pos, self.word_right(), kill=True)
        elif key in ("Delete", "KP_Delete") or (ctrl and key == "d"):
            return self.delete(pos, pos + 1)
        elif ctrl and key == "w":
            return self.delete(self.space_left(), pos, kill=True)
        elif ctrl and key == "k":
            return self.delete(pos, n, kill=True)
        elif ctrl and key == "u":
            return self.delete(0, pos, kill=True)
        elif ctrl and key == "t":
            return self.transpose()
        elif ctrl and key in ("slash", "underscore", "z"):
            return self.undo()
        elif char and not (ctrl or alt):
            self.insert(char, typing=True)
            return True
        else:
            return None
        self.typing_run = False
        return False
