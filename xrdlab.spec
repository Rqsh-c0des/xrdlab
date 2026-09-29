# PyInstaller spec for a one-file XRDLab build.
#
#   pip install -e .[mp,build]
#   pyinstaller xrdlab.spec
#
# Output: dist/XRDLab.exe (Windows) — a single executable end users can run with no
# Python, venv, or pip. pymatgen/mp-api ship large data files and many submodules,
# so we collect them wholesale; drop the "[mp]" install + these collects for a
# lighter build without Materials Project support.
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("pymatgen", "mp_api", "emmet", "spglib"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:  # noqa: BLE001 — optional MP stack may be absent
        pass

a = Analysis(
    ["src/xrdlab/app.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["scipy.signal", "scipy.sparse.linalg"],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="XRDLab",
    console=False,          # windowed app
    onefile=True,
    disable_windowed_traceback=False,
)
