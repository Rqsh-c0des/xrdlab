"""One-step launcher for XRDLab — no manual venv / pip needed.

Run it with any Python::

    python run.py

On the first run it creates a local virtual environment in ``.venv`` and installs
XRDLab and its dependencies into it; on every run after that it just launches the
app (Windows users can simply double-click ``XRDLab.bat``, which calls this).

Nothing here needs third-party packages — it uses only the standard library, so it
works before anything is installed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"


def _venv_python() -> Path:
    sub, exe = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    return VENV / sub / exe


def _ensure_environment() -> Path:
    """Create the venv and install XRDLab if they aren't ready yet; return its python."""
    py = _venv_python()
    if not py.exists():
        print("Setting up XRDLab: creating a virtual environment in .venv …", flush=True)
        venv.create(VENV, with_pip=True)
    probe = subprocess.run(
        [str(py), "-c", "import PySide6, xrdlab"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if probe.returncode != 0:
        print(
            "Installing XRDLab and its dependencies (first run only — this can take a\n"
            "few minutes while pymatgen/PySide6 download) …",
            flush=True,
        )
        subprocess.check_call([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"])
        # ".[mp]" pulls the full Materials Project / pymatgen stack so the double-click
        # experience is complete; a bare "pip install -e ." gives the lighter core.
        subprocess.check_call([str(py), "-m", "pip", "install", "-e", f"{ROOT}[mp]"])
        print("Setup complete.", flush=True)
        if os.name == "nt":  # double-click .xrdlab / .xrdov files to open them
            subprocess.call([str(py), str(ROOT / "tools" / "register_filetypes.py")])
        _defender_tip()
    return py


def _defender_tip() -> None:
    """On Windows, suggest excluding .venv from Defender — the biggest launch-speed
    lever, since real-time scanning of the many package files dominates cold start."""
    if os.name != "nt":
        return
    print(
        "\nTIP: Windows Defender scanning the packages in .venv can make XRDLab slow\n"
        "to start. To exclude this folder (run in an *admin* PowerShell, once):\n"
        f'  Add-MpPreference -ExclusionPath "{VENV}"\n',
        flush=True,
    )


def main() -> int:
    py = _ensure_environment()
    if Path(sys.executable).resolve() == py.resolve():
        from xrdlab.app import main as app_main  # already inside the venv

        return app_main([sys.argv[0], *sys.argv[1:]])
    return subprocess.call([str(py), "-m", "xrdlab.app", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
