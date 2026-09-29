"""Publish your current XRDLab changes to every installed copy.

    .venv\\Scripts\\python.exe tools\\publish_update.py "What changed"

Runs the full test suite first and refuses to publish if anything fails — a broken
build never reaches the other machines. Then commits everything and pushes; each
installed copy picks it up automatically the next time XRDLab starts.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*cmd, check=True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=ROOT, text=True)
    if check and r.returncode != 0:
        sys.exit(r.returncode)
    return r


def main() -> None:
    msg = " ".join(sys.argv[1:]).strip() or input("Describe this update: ").strip()
    if not msg:
        sys.exit("An update description is required.")
    print("Running tests …")
    if subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT).returncode:
        sys.exit("Tests failed — nothing was published. Fix them and try again.")
    run("git", "add", "-A")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        print("No changes to publish.")
    else:
        run("git", "commit", "-m", msg)
    run("git", "push")
    print("Published. Every installed copy updates on its next launch.")


if __name__ == "__main__":
    main()
