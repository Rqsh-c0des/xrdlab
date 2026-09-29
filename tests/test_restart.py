"""Auto-restart after an update: the session survives, the relaunch command is right,
and the countdown both fires and can be cancelled."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from xrdlab import app as app_mod  # noqa: E402
from xrdlab import config  # noqa: E402
from xrdlab.core.pattern import Pattern  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    from xrdlab.ui.main_window import MainWindow

    w = MainWindow()
    x = np.linspace(20, 80, 600)
    for i, name in enumerate(("ScN/Al₂O₃ 600 °C", "ScN/Al₂O₃ 700 °C")):
        w.pattern_panel.add_pattern(Pattern(x, 100 + 1e4 * np.exp(-((x - 34.4 - i * .05) / .1) ** 2),
                                            name=name, meta={"source_stem": f"s{i}"}))
    w.title_edit.setText("Growth series")
    w._manual_labels.append({"x": 34.4, "text": "ScN (111)", "pattern": None})
    w.tabs.setCurrentIndex(1)
    yield w
    w.deleteLater()


def test_session_survives_restart(window, qapp):
    from xrdlab.ui.main_window import MainWindow

    path = window.restart_app(launch=False)
    fresh = MainWindow()
    assert fresh.restore_session(path) is True
    names = [p.name for p, _ in fresh.pattern_panel.patterns_with_state()]
    assert names == ["ScN/Al₂O₃ 600 °C", "ScN/Al₂O₃ 700 °C"]
    assert fresh.title_edit.text() == "Growth series"
    assert fresh._manual_labels[0]["text"] == "ScN (111)"
    assert fresh.tabs.currentIndex() == 1
    assert not os.path.exists(path)  # restore file is consumed


def test_relaunch_command(window, monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.Popen", lambda cmd, **kw: calls.append((cmd, kw)))
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: None))
    path = window.restart_app(launch=True)
    cmd, kw = calls[0]
    assert cmd[-2:] == ["--restore", path]
    assert cmd[0].lower().endswith(("xrdlab.exe", "pythonw.exe", "python.exe", "python"))


def test_restore_file_is_not_opened_as_a_project(tmp_path):
    f = tmp_path / "restart_session.xrdlab"
    f.write_text("{}")
    scan = tmp_path / "scan.xrdml"
    scan.write_text("x")
    argv = ["XRDLab.exe", "--restore", str(f), str(scan)]
    assert app_mod._restore_arg(argv) == str(f)
    assert app_mod._file_args(argv) == [str(scan)]


def _spin(qapp, seconds):
    import time

    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.02)


def test_countdown_restarts(window, qapp, monkeypatch):
    fired = []
    monkeypatch.setattr(window, "restart_app", lambda **k: fired.append(True))
    window._restart_countdown({"changes": ["New tool"], "n_commits": 1}, seconds=1)
    _spin(qapp, 1.6)
    assert fired == [True]


def test_later_cancels_countdown(window, qapp, monkeypatch):
    fired = []
    monkeypatch.setattr(window, "restart_app", lambda **k: fired.append(True))
    window._restart_countdown({"changes": ["New tool"], "n_commits": 1}, seconds=1)
    later = [b for b in window._restart_box.buttons()
             if window._restart_box.buttonRole(b) == QMessageBox.ButtonRole.RejectRole][0]
    later.click()
    _spin(qapp, 1.6)
    assert fired == []
