"""XRDLab desktop entry point.

Run with::

    python -m xrdlab.app
"""

from __future__ import annotations

import sys


def _prewarm() -> None:
    """Import the heavy optional stack (pymatgen) in the background after the window
    is up, so the *first* Materials Project overlay / simulation isn't a cold stall.
    Imports only — no Qt objects are touched off the main thread."""
    import threading

    def warm() -> None:
        try:
            import pymatgen.analysis.diffraction.xrd  # noqa: F401
            import pymatgen.symmetry.analyzer  # noqa: F401
        except Exception:  # noqa: BLE001 — pymatgen may be an optional extra
            pass

    threading.Thread(target=warm, daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QSplashScreen

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("XRDLab")

    # Splash so the app feels instant while numpy/matplotlib (and our modules) load.
    pix = QPixmap(440, 240)
    pix.fill(QColor("#1f77b4"))
    painter = QPainter(pix)
    painter.setPen(QColor("white"))
    f = painter.font()
    f.setPointSize(30)
    f.setBold(True)
    painter.setFont(f)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "XRDLab")
    painter.end()
    splash = QSplashScreen(pix)
    splash.showMessage("Loading…", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                       QColor("white"))
    splash.show()
    app.processEvents()

    from xrdlab.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    splash.finish(window)
    # Files passed on the command line — how Windows hands over a double-clicked or
    # "Open with…" file: projects/overlays open as sessions, scans load as patterns.
    args = list(argv if argv is not None else sys.argv)
    restore = _restore_arg(args)
    if restore:  # relaunched after an update: bring the previous session back
        window.restore_session(restore)
    for path in _file_args(args):
        window.open_path(path)
    _prewarm()
    from xrdlab import config

    if config.get_value("auto_update", True):
        window.start_update_check()  # background: newer version → notify to restart
    return app.exec()


def _restore_arg(argv) -> str | None:
    args = list(argv)
    if "--restore" in args:
        i = args.index("--restore")
        if i + 1 < len(args):
            return args[i + 1]
    return None


def _file_args(argv) -> list[str]:
    """Files to open: every existing path argument except the ``--restore`` value."""
    from pathlib import Path

    args = list(argv)[1:]
    skip = set()
    if "--restore" in args:
        i = args.index("--restore")
        skip = {i, i + 1}
    return [a for k, a in enumerate(args)
            if k not in skip and not a.startswith("-") and Path(a).is_file()]


if __name__ == "__main__":
    raise SystemExit(main())
