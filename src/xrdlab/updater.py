"""Self-update for installed copies of XRDLab (git-based, no admin, no installer).

Every installed copy is a ``git clone`` of the same repository. On launch the app
calls :func:`update` in a background thread: it fetches, and if the copy is simply
*behind* (no local edits, no unpushed commits) it fast-forwards to the newest
version, reinstalling dependencies only when ``pyproject.toml`` changed. The new
code takes effect on the next launch (the install is editable, so no rebuild).

A copy with local changes or unpushed commits — i.e. the machine you develop and
publish from — is never touched; it's reported instead. Offline / no git / not a
clone → silently does nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

__all__ = ["ROOT", "is_managed", "version", "check", "update"]

ROOT = Path(__file__).resolve().parents[2]  # <repo>/src/xrdlab/updater.py → <repo>
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # no console flash under pythonw


def _git(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          text=True, timeout=timeout, creationflags=_NO_WINDOW)


def is_managed() -> bool:
    """True if this install is a git clone and git is available."""
    return bool(shutil.which("git")) and (ROOT / ".git").exists()


def version() -> str:
    """Human-readable version: commit hash + date for a clone, else the package's."""
    if is_managed():
        try:
            r = _git("log", "-1", "--format=%h (%cs)", timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        from importlib.metadata import version as _v

        return _v("xrdlab")
    except Exception:  # noqa: BLE001
        return "unknown"


def check() -> dict:
    """Fetch and compare with the upstream branch (no changes made)."""
    if not is_managed():
        return {"managed": False}
    try:
        f = _git("fetch", "--quiet")
        if f.returncode != 0:
            return {"managed": True, "error": (f.stderr or "fetch failed").strip()}
        up = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if up.returncode != 0:
            return {"managed": True, "error": "no upstream branch configured"}
        counts = _git("rev-list", "--left-right", "--count", "HEAD...@{u}").stdout.split()
        ahead, behind = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
        dirty = bool(_git("status", "--porcelain", "--untracked-files=no").stdout.strip())
        return {"managed": True, "ahead": ahead, "behind": behind, "dirty": dirty,
                "upstream": up.stdout.strip()}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"managed": True, "error": str(exc)}


def update(install_deps: bool = True) -> dict:
    """Fast-forward to the newest published version if this copy is just behind.

    Returns a dict with ``updated`` (bool) and details: ``from``/``to`` commits,
    ``deps`` (dependencies reinstalled), or ``skipped`` with the reason.
    """
    st = check()
    if not st.get("managed") or st.get("error"):
        return {"updated": False, **st}
    if st["behind"] == 0:
        return {"updated": False, "skipped": "up to date", **st}
    if st["dirty"] or st["ahead"]:
        return {"updated": False, **st,
                "skipped": "this copy has local changes or unpublished commits — "
                           "not overwriting it (publish from here instead)"}
    old = _git("rev-parse", "--short", "HEAD").stdout.strip()
    pull = _git("pull", "--ff-only", "--quiet", timeout=120)
    if pull.returncode != 0:
        return {"updated": False, "error": (pull.stderr or "pull failed").strip(), **st}
    new = _git("rev-parse", "--short", "HEAD").stdout.strip()
    changed = _git("diff", "--name-only", old, new).stdout.split()
    deps = False
    if install_deps and "pyproject.toml" in changed:
        pip = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "-e", f"{ROOT}[mp]"],
            capture_output=True, text=True, timeout=900, creationflags=_NO_WINDOW)
        deps = pip.returncode == 0
    log = _git("log", "--format=%s", f"{old}..{new}").stdout.strip().splitlines()
    return {"updated": True, "from": old, "to": new, "deps": deps, "changes": log[:10],
            "n_commits": st["behind"]}


if __name__ == "__main__":  # python -m xrdlab.updater  → update from a terminal
    import json

    print(json.dumps(update(), indent=2))
