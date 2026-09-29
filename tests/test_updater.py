"""Self-update: a clone that is behind fast-forwards; a clone with local work is left
alone. Uses a throwaway bare repo as the 'shared' remote (no network)."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not installed")

UPDATER = Path(__file__).resolve().parents[1] / "src" / "xrdlab" / "updater.py"


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _load_updater(clone: Path):
    """Import the updater copy living inside ``clone`` (its ROOT is that clone)."""
    spec = importlib.util.spec_from_file_location(f"upd_{clone.name}",
                                                  clone / "src" / "xrdlab" / "updater.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def repos(tmp_path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    pub = tmp_path / "publisher"
    git(tmp_path, "clone", str(origin), str(pub))
    for c in (pub,):
        git(c, "config", "user.email", "t@example.com")
        git(c, "config", "user.name", "t")
    (pub / "src" / "xrdlab").mkdir(parents=True)
    shutil.copy(UPDATER, pub / "src" / "xrdlab" / "updater.py")
    (pub / "feature.txt").write_text("v1\n")
    git(pub, "add", "-A")
    git(pub, "commit", "-m", "v1")
    git(pub, "push", "-u", "origin", "main")
    user = tmp_path / "labmate"
    git(tmp_path, "clone", str(origin), str(user))
    return pub, user


def _publish(pub, text, msg):
    (pub / "feature.txt").write_text(text)
    git(pub, "commit", "-am", msg)
    git(pub, "push")


def test_behind_clone_fast_forwards(repos):
    pub, user = repos
    upd = _load_updater(user)
    assert upd.update(install_deps=False)["skipped"] == "up to date"
    _publish(pub, "v2\n", "Add rocking-curve tool")
    r = upd.update(install_deps=False)
    assert r["updated"] is True and r["n_commits"] == 1
    assert r["changes"] == ["Add rocking-curve tool"]
    assert (user / "feature.txt").read_text() == "v2\n"


def test_clone_with_local_edits_is_not_overwritten(repos):
    pub, user = repos
    _publish(pub, "v2\n", "update")
    (user / "feature.txt").write_text("my local tweak\n")
    r = _load_updater(user).update(install_deps=False)
    assert r["updated"] is False and "local changes" in r["skipped"]
    assert (user / "feature.txt").read_text() == "my local tweak\n"


def test_publisher_with_unpushed_commits_is_not_touched(repos):
    """The developer's machine (local commits not yet pushed) must never be
    fast-forwarded or rewritten by the auto-updater."""
    pub, other = repos
    (pub / "feature.txt").write_text("unpushed\n")
    git(pub, "commit", "-am", "local only")          # pub is now ahead…
    git(other, "config", "user.email", "t@example.com")
    git(other, "config", "user.name", "t")
    (other / "other.txt").write_text("remote change\n")
    git(other, "add", "-A")
    git(other, "commit", "-m", "remote")
    git(other, "push")                                # …and behind
    r = _load_updater(pub).update(install_deps=False)
    assert r["updated"] is False and r["ahead"] == 1 and r["behind"] == 1
    assert (pub / "feature.txt").read_text() == "unpushed\n"


def test_not_a_clone_is_a_noop(tmp_path):
    d = tmp_path / "plain" / "src" / "xrdlab"
    d.mkdir(parents=True)
    shutil.copy(UPDATER, d / "updater.py")
    upd = _load_updater(tmp_path / "plain")
    assert upd.is_managed() is False
    assert upd.update()["updated"] is False
