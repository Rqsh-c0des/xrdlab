"""Guard against heavy modules creeping back into the startup import path.

Launch time regressed once because ``scipy`` was imported at module load via
``core.processing``. This locks in the fix: after importing the UI entry module,
scipy / pymatgen / mp_api must NOT be loaded (they are lazy, on first use only).
Run in a fresh interpreter so other tests' imports don't pollute ``sys.modules``.
"""

from __future__ import annotations

import subprocess
import sys


def _modules_after_import(target: str) -> set[str]:
    code = (
        "import sys;"
        f"import {target};"
        "print('\\n'.join(sorted(m.split('.')[0] for m in sys.modules)))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return set(out.stdout.split())


def test_scipy_not_imported_at_startup():
    mods = _modules_after_import("xrdlab.ui.main_window")
    assert "scipy" not in mods, "scipy must stay lazy — it dominates cold start"


def test_pymatgen_not_imported_at_startup():
    mods = _modules_after_import("xrdlab.ui.main_window")
    assert "pymatgen" not in mods
    assert "mp_api" not in mods


def test_numpy_is_imported():
    # numpy is genuinely needed at startup; this sanity-checks the probe itself.
    assert "numpy" in _modules_after_import("xrdlab.core.pattern")
