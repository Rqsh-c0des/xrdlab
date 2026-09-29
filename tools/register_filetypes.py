"""Register XRDLab's file types with Windows for the current user (no admin needed).

    python tools/register_filetypes.py              # register
    python tools/register_filetypes.py --unregister # remove everything it added

What it does (all under HKEY_CURRENT_USER\\Software\\Classes):
  * .xrdlab (project) and .xrdov (overlay) open in XRDLab on double-click, with the
    XRDLab icon and proper type names ("XRDLab project", "XRDLab overlay").
  * XRDLab is *offered* in "Open with" for .xrdml scans — your existing default for
    .xrdml (e.g. Data Viewer) is left untouched.
  * Windows lists the app as "XRDLab" (via the .venv\\Scripts\\XRDLab.exe launcher),
    not as "Python".
If you previously ticked "Always use this app" for .xrdlab, Windows keeps that choice
(it is hash-protected and can't be changed by programs) — pick XRDLab once in
"Open with ▸ Choose another app" and tick "Always".
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / ".venv" / "Scripts" / "XRDLab.exe"
ICON = ROOT / "assets" / "xrdlab.ico"
BASE = r"Software\Classes"

# ProgID -> (friendly type name, extension it's the default for, or None = offer only)
PROGIDS = {
    "XRDLab.Project": ("XRDLab project", ".xrdlab"),
    "XRDLab.Overlay": ("XRDLab overlay", ".xrdov"),
    "XRDLab.Scan": ("Diffraction scan", None),
}
OFFER_ONLY = {".xrdml": "XRDLab.Scan"}  # show in Open-with, don't take the default


def _notify() -> None:
    """Tell Explorer associations changed so icons/handlers refresh immediately."""
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:  # noqa: BLE001
        pass


def register() -> None:
    import winreg as reg

    if not EXE.exists():
        sys.exit(f"Launcher not found: {EXE}\nRun `pip install -e .` in the venv first.")
    command = f'"{EXE}" "%1"'
    icon = f'"{ICON}",0' if ICON.exists() else f'"{EXE}",0'

    def setv(path: str, name: str | None, value: str) -> None:
        with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, f"{BASE}\\{path}", 0,
                             reg.KEY_SET_VALUE) as k:
            reg.SetValueEx(k, name, 0, reg.REG_SZ, value)

    for progid, (friendly, ext) in PROGIDS.items():
        setv(progid, None, friendly)
        setv(progid, "FriendlyTypeName", friendly)
        setv(f"{progid}\\DefaultIcon", None, icon)
        setv(f"{progid}\\shell\\open", "FriendlyAppName", "XRDLab")
        setv(f"{progid}\\shell\\open\\command", None, command)
        if ext:
            setv(ext, None, progid)                       # default handler
            setv(f"{ext}\\OpenWithProgids", progid, "")   # and listed in Open-with
    for ext, progid in OFFER_ONLY.items():
        setv(f"{ext}\\OpenWithProgids", progid, "")

    app = r"Applications\XRDLab.exe"
    setv(app, "FriendlyAppName", "XRDLab")
    setv(f"{app}\\DefaultIcon", None, icon)
    setv(f"{app}\\shell\\open\\command", None, command)
    for ext in [e for _, (_, e) in PROGIDS.items() if e] + list(OFFER_ONLY):
        setv(f"{app}\\SupportedTypes", ext, "")
    _notify()
    print(f"Registered .xrdlab / .xrdov → {EXE}")
    print("XRDLab is also offered in 'Open with' for .xrdml scans (default unchanged).")


def unregister() -> None:
    import winreg as reg

    def delete_tree(path: str) -> None:
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, f"{BASE}\\{path}", 0,
                             reg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        delete_tree(f"{path}\\{reg.EnumKey(k, 0)}")
                    except OSError:
                        break
            reg.DeleteKey(reg.HKEY_CURRENT_USER, f"{BASE}\\{path}")
        except FileNotFoundError:
            pass

    def delete_value(path: str, name: str) -> None:
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, f"{BASE}\\{path}", 0,
                             reg.KEY_SET_VALUE) as k:
                reg.DeleteValue(k, name)
        except FileNotFoundError:
            pass

    for progid, (_, ext) in PROGIDS.items():
        delete_tree(progid)
        if ext:
            delete_value(f"{ext}\\OpenWithProgids", progid)
            try:  # only clear the default if it's still ours
                with reg.OpenKey(reg.HKEY_CURRENT_USER, f"{BASE}\\{ext}", 0,
                                 reg.KEY_ALL_ACCESS) as k:
                    if reg.QueryValueEx(k, None)[0] == progid:
                        reg.DeleteValue(k, None)
            except (FileNotFoundError, OSError):
                pass
    for ext, progid in OFFER_ONLY.items():
        delete_value(f"{ext}\\OpenWithProgids", progid)
    delete_tree(r"Applications\XRDLab.exe")
    _notify()
    print("Removed XRDLab file-type registrations.")


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("File-type registration is Windows-only.")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--unregister", action="store_true")
    (unregister if ap.parse_args().unregister else register)()
