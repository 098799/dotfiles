"""What closing the lid does, for the power panel, and the CPU guard while it is closed.

The switch: logind's HandleLidSwitch (on battery) in DROPIN, "suspend" or "ignore".
A chip rewrites that one line (the AC and docked lines stay as they are) with
`sudo -n tee` and makes logind read its config again with SIGHUP, not a restart: a
restart of systemd-logind can end the session.

The guard: with "ignore", a closed lid no longer stops the machine, and in a bag it
would cook. So while the lid is closed, no external screen is connected (that is
the desk) and the mode is "ignore", the CPU is held at its minimum: platform profile
low-power, no boost, EPP "power" and scaling_max_freq at CAP_KHZ on every core.
TLP switches the profile and EPP on every AC plug or unplug (PLATFORM_PROFILE_ON_AC
= performance), so check() reads the knobs again every CHECK_S and writes any that
drifted. What was there before is kept in STATE and written back when the lid opens,
a screen comes, or the mode goes back to suspend; STATE is in the runtime dir, so a
daemon restart (a theme switch reloads waybar) takes the guard up again and restores
the right values. The guard lives in the daemon: no bardeck, no guard.

Root: `sudo -n`, on a thread. Only the daemon calls check()."""

from __future__ import annotations

import glob
import json
import os
import re
import shlex
import subprocess
import threading
import time

from . import core

DROPIN = "/etc/systemd/logind.conf.d/lid.conf"
STATE = f"{core.RUN_DIR}/lid-guard.json"
CHECK_S = 5
CAP_KHZ = 1400000  # well under the 2 GHz base clock; the floor is cpuinfo_min_freq
PROFILE = "/sys/firmware/acpi/platform_profile"
BOOST = "/sys/devices/system/cpu/cpufreq/boost"
CPU0 = "/sys/devices/system/cpu/cpu0/cpufreq"
ALL_CPUS = "/sys/devices/system/cpu/cpu[0-9]*/cpufreq"

# (logind value, chip label)
MODES = (("suspend", "suspend"), ("ignore", "do nothing"))


def lid_closed() -> bool:
    return any("closed" in core.read(f) for f in glob.glob("/proc/acpi/button/lid/*/state"))


def has_lid() -> bool:
    return bool(glob.glob("/proc/acpi/button/lid/*/state"))


def external_screen() -> bool:
    """A connected screen that is not the laptop's own (DP, HDMI, …)."""
    for f in glob.glob("/sys/class/drm/card*-*/status"):
        name = f.split("/")[-2].split("-", 1)[1]
        if not name.startswith(("eDP", "LVDS", "Writeback")) and core.read(f) == "connected":
            return True
    return False


def knobs() -> dict[str, str]:
    """The values the guard changes, as they are now ('' where a knob does not exist)."""
    return {
        "profile": core.read(PROFILE),
        "boost": core.read(BOOST),
        "epp": core.read(f"{CPU0}/energy_performance_preference"),
        "max_freq": core.read(f"{CPU0}/scaling_max_freq"),
    }


def held() -> dict[str, str]:
    """The guard's values, for the knobs this machine has."""
    now = knobs()
    floor = int(core.read(f"{CPU0}/cpuinfo_min_freq", "0") or 0)
    want = {"profile": "low-power", "boost": "0", "epp": "power", "max_freq": str(max(CAP_KHZ, floor))}
    if "low-power" not in core.read("/sys/firmware/acpi/platform_profile_choices").split():
        want["profile"] = ""
    if "power" not in core.read(f"{CPU0}/energy_performance_available_preferences").split():
        want["epp"] = ""
    return {k: v for k, v in want.items() if v and now[k]}


def write_cmd(values: dict[str, str]) -> str:
    """One shell command that writes these knobs, boost before the frequency (boost
    moves cpuinfo_max_freq, and with it the ceiling scaling_max_freq can take)."""
    parts = []
    if "profile" in values:
        parts.append(f"echo {shlex.quote(values['profile'])} | sudo -n tee {PROFILE}")
    if "boost" in values:
        parts.append(f"echo {shlex.quote(values['boost'])} | sudo -n tee {BOOST}")
    if "epp" in values:
        parts.append(f"echo {shlex.quote(values['epp'])} | sudo -n tee {ALL_CPUS}/energy_performance_preference")
    if "max_freq" in values:
        parts.append(f"echo {shlex.quote(values['max_freq'])} | sudo -n tee {ALL_CPUS}/scaling_max_freq")
    return " && ".join(f"{p} >/dev/null" for p in parts)


class Lid:
    def __init__(self):
        self.status: tuple[str, str] | None = None  # (tone, words) of the last change of mode
        self.error = ""  # the guard's last failure
        self.guarding = False
        self.checked_at = 0.0
        self._busy = threading.Lock()

    # ── the switch ──

    def mode(self) -> str:
        """HandleLidSwitch as DROPIN saves it; logind's default when it does not."""
        m = re.search(r"^HandleLidSwitch=(\w+)", core.read(DROPIN), re.M)
        return m.group(1) if m else "suspend"

    def ac_words(self) -> str:
        text = core.read(DROPIN)
        ac = re.search(r"^HandleLidSwitchExternalPower=(\w+)", text, re.M)
        return "on AC: never suspends" if ac and ac.group(1) == "ignore" else ""

    def set_mode(self, mode: str) -> bool:
        """A chip's action. False keeps the panel open."""
        if mode == self.mode():
            return False
        text = core.read(DROPIN) or "[Login]\n"
        if re.search(r"^HandleLidSwitch=", text, re.M):
            text = re.sub(r"^HandleLidSwitch=.*$", f"HandleLidSwitch={mode}", text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\nHandleLidSwitch={mode}\n"
        if not text.endswith("\n"):
            text += "\n"
        self._run(f"printf '%s' {shlex.quote(text)} | sudo -n tee {DROPIN} >/dev/null"
                  " && sudo -n systemctl kill -s HUP systemd-logind", f"lid: {mode}", status=True)
        self.checked_at = 0.0  # the guard follows on the next tick
        return False

    # ── the guard ──

    def check(self) -> None:
        """Every tick of the daemon; acts every CHECK_S."""
        now = time.monotonic()
        if now - self.checked_at < CHECK_S or self._busy.locked():
            return
        self.checked_at = now
        want = self.mode() == "ignore" and lid_closed() and not external_screen()
        saved = core.read(STATE)
        if want:
            cur, hold = knobs(), held()
            drift = {k: v for k, v in hold.items() if cur[k] != v}
            self.guarding = True
            if not drift:
                return
            if not saved:
                try:
                    with open(STATE, "w") as fh:
                        json.dump({k: cur[k] for k in hold}, fh)
                except OSError as err:
                    core.log(f"lid guard: {err!r}")
            core.log(f"lid guard: closed, holding {drift}")
            self._run(write_cmd(drift), "lid guard")
        elif saved:
            self.guarding = False
            try:
                before = json.loads(saved)
            except ValueError:
                before = {}
            core.log(f"lid guard: open again, back to {before}")
            self._run(write_cmd(before) or "true", "lid guard off", done=lambda: os.path.exists(STATE) and os.remove(STATE))
        else:
            self.guarding = False

    def _run(self, cmd: str, words: str, status: bool = False, done=None) -> None:
        if not self._busy.acquire(blocking=False):
            return
        if status:
            self.status = ("warn", words + "…")

        def body():
            try:
                r = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=30,
                                   stdin=subprocess.DEVNULL)
                if r.returncode == 0:
                    if status:
                        self.status = None
                    else:
                        self.error = ""
                    if done:
                        done()
                else:
                    err = (r.stderr or r.stdout).strip().splitlines()
                    words_err = (err[-1] if err else f"failed (exit {r.returncode})")[:60]
                    if status:
                        self.status = ("hit", words_err)
                    else:
                        self.error = words_err
                    core.log(f"{words}: {(r.stderr or r.stdout).strip()[:200]}")
            except Exception as err:
                if status:
                    self.status = ("hit", "failed")
                else:
                    self.error = "failed"
                core.log(f"{words}: {err!r}")
            finally:
                self._busy.release()

        threading.Thread(target=body, daemon=True).start()
