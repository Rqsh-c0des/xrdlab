"""Main application window wiring the panels, plot tabs, and file I/O together."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xrdlab.core import hrxrd
from xrdlab.core.generic_io import read_pattern
from xrdlab.core.rietveld_io import read_rietveld_csv
from xrdlab.ml.labeling import (
    ProminencePeakLabeler,
    assign_peaks,
    hkl_display,
    subscript_digits,
    subscriptify,
)


def _phase_text(formula, hkl) -> str:
    """Formula with subscripted coefficients + hkl with overbars (Al₂O₃ (0 0 0 6))."""
    f = subscript_digits(str(formula))
    h = hkl_display(hkl)
    return f"{f} ({h})" if h else f
from xrdlab.ml.phase_db import PhaseDatabase
from xrdlab.plotting.export import EXPORT_FORMATS, save_figure
from xrdlab.plotting.overlay import overlay_reference
from xrdlab.plotting.rietveld import plot_rietveld
from xrdlab.plotting.style import AXIS_LABELS, apply_publication_style
from xrdlab.plotting.waterfall import plot_waterfall
from xrdlab.ui.panels import (
    MPSearchPanel,
    PatternListPanel,
    PeakDisplayControls,
    ProcessingControls,
    WaterfallControls,
)
from xrdlab.ui.widgets import CitationsView, PlotWidget

_PATTERN_FILTER = "Diffraction data (*.xrdml *.xy *.dat *.txt *.csv);;All files (*)"

# Distinct colours cycled across multiple reference phases.
_REF_COLORS = ["#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b"]


_TOKENS = __import__("itertools").count(1)


def _pkey(pattern) -> int:
    """A cache key unique to this pattern object for the whole session.

    ``id()`` is recycled once an object is freed, so a newly loaded scan could
    inherit a removed scan's cached peaks/fits; this token is never reused.
    """
    tok = getattr(pattern, "_xrdlab_token", None)
    if tok is None:
        tok = next(_TOKENS)
        object.__setattr__(pattern, "_xrdlab_token", tok)
    return tok


class MainWindow(QMainWindow):
    """Top-level window: pattern list + controls docked beside plot tabs."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("XRDLab — XRD figure builder")
        self.resize(1180, 760)
        self.setAcceptDrops(True)
        apply_publication_style()

        self._references = []   # list[ReferencePattern] — sample phases to overlay
        self._rietveld = None   # loaded RietveldData
        self._phase_db = PhaseDatabase()  # local phase database for peak ID
        self._current_bibtex = ""  # BibTeX for the Citations tab's current report
        self._last_peaks = []      # peaks from the most recent Single-view detection
        self._peak_overrides = {}  # {round(2θ,1): (formula, hkl, 2θ, I) | None}
        self._manual_labels = []   # [{"x": 2θ, "text": str, "pattern": stem}] user labels
        self._label_offsets = {}   # {key: (dx, dy)} draggable label positions
        self._draggable_anns = []  # (key, annotation) rebuilt each Single redraw
        self._cleared = []         # 2θ positions whose auto-labels are suppressed
        self._wf_guides = []       # [{"x": float, "name": str}] waterfall guide lines
        self._wf_guide_artists = []  # [(line, annotation)] current guide artists
        self._wf_drag = None       # index of the guide line being dragged
        self._project_path = None  # current .xrdlab file (Save rewrites it)
        self._peak_cache = {}      # _pkey(pattern) -> (signature, [(2θ, I, fwhm), …])
        self._proc_cache = {}      # _pkey(pattern) -> (proc-signature, processed Pattern)
        self._undo_stack = []      # project snapshots for undo
        self._redo_stack = []

        # --- plot tabs ---
        self.single_plot = PlotWidget()
        self.waterfall_plot = PlotWidget()
        self.rietveld_plot = PlotWidget()
        self.citations_view = CitationsView()
        from xrdlab.ui.fwhm_view import FwhmCompareView

        self.fwhm_view = FwhmCompareView()
        self._fit_cache = {}  # (_pkey(pattern), 2θ rounded, doublet?) -> PeakFit | None
        self.tabs = QTabWidget()
        self.tabs.addTab(self.single_plot, "Single")
        self.tabs.addTab(self.waterfall_plot, "Waterfall")
        self.tabs.addTab(self.fwhm_view, "FWHM")
        self.tabs.addTab(self.rietveld_plot, "Rietveld")
        self.tabs.addTab(self.citations_view, "Citations")
        self.setCentralWidget(self.tabs)
        self.citations_view.export_requested.connect(self._export_citations)
        # Click a peak on the Single plot to see / assign candidate phases;
        # right-click to add a manual label; drag any label to reposition it.
        self.single_plot.canvas.mpl_connect("button_press_event", self._on_single_click)
        self.single_plot.canvas.mpl_connect("button_release_event", self._on_label_release)

        # --- side panels ---
        self.pattern_panel = PatternListPanel()
        self.display_controls = PeakDisplayControls()
        self.processing_controls = ProcessingControls()
        self.waterfall_controls = WaterfallControls()
        self.mp_panel = MPSearchPanel()
        self._build_dock()

        # --- signals ---
        self.pattern_panel.changed.connect(self._redraw_waterfall)
        self.pattern_panel.selection_changed.connect(self._redraw_single)
        self.pattern_panel.selection_changed.connect(self._redraw_citations)
        self.display_controls.changed.connect(self._redraw_single)
        self.display_controls.changed.connect(self._redraw_citations)
        self.display_controls.add_peak_requested.connect(self._prompt_add_peak)
        self.display_controls.peak_table_requested.connect(self._show_peak_table)
        self.processing_controls.changed.connect(self._on_processing_changed)
        # FWHM comparison tab: measured lazily — when shown, or when its inputs
        # change while it's the visible tab.
        self.fwhm_view.refresh_requested.connect(self._refresh_fwhm)
        self.tabs.currentChanged.connect(lambda _: self._refresh_fwhm_if_visible())
        for sig in (self.pattern_panel.changed, self.display_controls.changed,
                    self.processing_controls.changed):
            sig.connect(self._refresh_fwhm_if_visible)
        self.waterfall_controls.changed.connect(self._redraw_waterfall)
        self.waterfall_controls.add_guide_requested.connect(self._wf_add_guide)
        self.waterfall_controls.guides_from_material_requested.connect(
            self._prompt_guides_from_material
        )
        self.mp_panel.overlay_requested.connect(self._on_overlay)
        self.mp_panel.clear_requested.connect(self._on_clear_overlay)

        self.waterfall_plot.lock_y = True  # y is arbitrary offset; scroll zooms x only

        # Waterfall guide-line interaction (drag to move, right-click to manage).
        wc = self.waterfall_plot.canvas
        wc.mpl_connect("button_press_event", self._wf_on_press)
        wc.mpl_connect("motion_notify_event", self._wf_on_motion)
        wc.mpl_connect("button_release_event", self._wf_on_release)

        self._build_menu()
        self.statusBar().showMessage("Open or drag in .xrdml / .xy / .csv files to begin.")

        self._restore_geometry()
        # Periodic auto-save of the working session for crash recovery.
        from PySide6.QtCore import QTimer

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(120_000)  # 2 min
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()
        QTimer.singleShot(0, self._maybe_recover)  # after the window is shown

    def _restore_geometry(self) -> None:
        from PySide6.QtCore import QByteArray

        from xrdlab import config

        geo = config.get_value("window_geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
            except Exception:  # noqa: BLE001
                pass

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        from xrdlab import config

        try:
            config.set_value(
                "window_geometry",
                bytes(self.saveGeometry().toBase64()).decode("ascii"),
            )
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)

    # -- layout --------------------------------------------------------------
    def _build_dock(self) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit

        container = QWidget()
        layout = QVBoxLayout(container)

        # Custom centered figure title (applies to Single, Waterfall, Rietveld).
        title_row = QWidget()
        trow = QHBoxLayout(title_row)
        trow.setContentsMargins(0, 0, 0, 0)
        trow.addWidget(QLabel("Title:"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("optional centered figure title")
        self.title_edit.textChanged.connect(self._redraw_single)
        self.title_edit.textChanged.connect(self._redraw_waterfall)
        self.title_edit.textChanged.connect(self._redraw_rietveld)
        trow.addWidget(self.title_edit)
        layout.addWidget(title_row)

        layout.addWidget(self.pattern_panel, stretch=1)
        layout.addWidget(self.display_controls)
        layout.addWidget(self.processing_controls)
        layout.addWidget(self.waterfall_controls)
        layout.addWidget(self.mp_panel)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        dock = QDockWidget("Controls", self)
        dock.setWidget(scroll)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_act = QAction("&Open patterns…", self)
        open_act.setShortcut(QKeySequence.StandardKey.Open)
        open_act.triggered.connect(self._open_patterns)
        file_menu.addAction(open_act)

        riet_act = QAction("Open &Rietveld CSV…", self)
        riet_act.triggered.connect(self._open_rietveld)
        file_menu.addAction(riet_act)

        file_menu.addSeparator()
        open_proj_act = QAction("Open pro&ject…", self)
        open_proj_act.setShortcut("Ctrl+Shift+O")
        open_proj_act.setToolTip("Open a saved .xrdlab session and resume where you left off.")
        open_proj_act.triggered.connect(self._open_project)
        file_menu.addAction(open_proj_act)

        save_proj_act = QAction("&Save project", self)
        save_proj_act.setShortcut(QKeySequence.StandardKey.Save)  # Ctrl+S
        save_proj_act.setToolTip("Rewrite the current project file (or choose one the first time).")
        save_proj_act.triggered.connect(self._save_project)
        file_menu.addAction(save_proj_act)

        save_as_act = QAction("Save project &as…", self)
        save_as_act.setShortcut(QKeySequence.StandardKey.SaveAs)  # Ctrl+Shift+S
        save_as_act.triggered.connect(self._save_project_as)
        file_menu.addAction(save_as_act)

        overlay_act = QAction("Export &overlay (.xrdov)…", self)
        overlay_act.setToolTip(
            "Save just the multi-pattern comparison (checked scans, overlays, guides) "
            "as its own .xrdov file; it opens straight into the Waterfall.")
        overlay_act.triggered.connect(self._export_overlay)
        file_menu.addAction(overlay_act)

        self._recent_menu = file_menu.addMenu("Open &recent project")
        self._rebuild_recent_menu()

        file_menu.addSeparator()
        export_act = QAction("&Export current figure…", self)
        export_act.setShortcut("Ctrl+E")
        export_act.triggered.connect(self._export_current)
        file_menu.addAction(export_act)

        file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence.StandardKey.Quit)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        edit_menu = self.menuBar().addMenu("&Edit")
        self._undo_act = QAction("&Undo", self)
        self._undo_act.setShortcut(QKeySequence.StandardKey.Undo)  # Ctrl+Z
        self._undo_act.triggered.connect(self._undo)
        edit_menu.addAction(self._undo_act)
        self._redo_act = QAction("&Redo", self)
        self._redo_act.setShortcut(QKeySequence.StandardKey.Redo)  # Ctrl+Y
        self._redo_act.triggered.connect(self._redo)
        edit_menu.addAction(self._redo_act)
        self._refresh_undo_actions()

        analyze_menu = self.menuBar().addMenu("&Analyze")
        rock_act = QAction("&Rocking curve FWHM…", self)
        rock_act.setToolTip("Measure/fit the FWHM of the current scan's dominant peak.")
        rock_act.triggered.connect(self._analyze_rocking_curve)
        analyze_menu.addAction(rock_act)
        fwhm_act = QAction("&FWHM comparison (all checked patterns)", self)
        fwhm_act.setToolTip("Peak widths per reflection across samples, with a trend plot.")
        fwhm_act.triggered.connect(lambda: self.tabs.setCurrentWidget(self.fwhm_view))
        analyze_menu.addAction(fwhm_act)
        lat_act = QAction("&Lattice parameter / strain…", self)
        lat_act.triggered.connect(self._analyze_lattice)
        analyze_menu.addAction(lat_act)
        analyze_menu.addSeparator()
        rsm_act = QAction("Open reciprocal-space &map…", self)
        rsm_act.triggered.connect(self._open_rsm)
        analyze_menu.addAction(rsm_act)

        hr = self.menuBar().addMenu("&HRXRD")
        for text, tip, slot in (
            ("&Rocking curves — FWHM, dislocations, tilt/twist…",
             "Compare ω rocking curves; Dunn–Kogh dislocation density; mosaic tilt & "
             "twist from symmetric + skew-symmetric RCs; Williamson–Hall-ω.",
             self._analyze_rocking_curve),
            ("Reciprocal-space &map (strain / relaxation)…",
             "Open an area-measurement .xrdml (or CSV) as a Qx–Qz map; lattice "
             "parameters, strain and degree of relaxation.", self._open_rsm),
            ("Film &thickness from fringes…",
             "Thickness from Pendellösung / Laue fringes around a 2θ-ω peak.",
             self._hrxrd_thickness),
            ("&Williamson–Hall (size / microstrain)…",
             "Vertical coherence length and microstrain from several orders.",
             self._hrxrd_wh),
            ("&φ-scan symmetry…",
             "n-fold in-plane symmetry and rotation twins from a φ scan.",
             self._hrxrd_phi),
            ("&Lattice parameter / strain (from 2θ-ω peaks)…",
             "Cubic a (Nelson–Riley) or hexagonal a, c from assigned peaks.",
             self._analyze_lattice),
        ):
            act = QAction(text, self)
            act.setToolTip(tip)
            act.setStatusTip(tip)
            act.triggered.connect(slot)
            hr.addAction(act)

        settings_menu = self.menuBar().addMenu("&Settings")
        key_act = QAction("Set Materials Project &API key…", self)
        key_act.triggered.connect(self.mp_panel.prompt_api_key)
        settings_menu.addAction(key_act)

        instr_act = QAction("&Instrument broadening (FWHM)…", self)
        instr_act.triggered.connect(self._set_instrument_fwhm)
        settings_menu.addAction(instr_act)

        naming_act = QAction("&Filename parsing…", self)
        naming_act.triggered.connect(self._edit_filename_parsing)
        settings_menu.addAction(naming_act)

        db_act = QAction("&Phase database…", self)
        db_act.triggered.connect(self._manage_phase_db)
        settings_menu.addAction(db_act)

        mailto_act = QAction("Crossref &email…", self)
        mailto_act.triggered.connect(self._set_crossref_email)
        settings_menu.addAction(mailto_act)

        from xrdlab import config

        help_menu = self.menuBar().addMenu("&Help")
        upd = QAction("Check for &updates now", self)
        upd.triggered.connect(lambda: self.start_update_check(manual=True))
        help_menu.addAction(upd)
        self._auto_update_act = QAction("&Automatically update on launch", self)
        self._auto_update_act.setCheckable(True)
        self._auto_update_act.setChecked(bool(config.get_value("auto_update", True)))
        self._auto_update_act.toggled.connect(lambda on: config.set_value("auto_update", on))
        help_menu.addAction(self._auto_update_act)
        help_menu.addSeparator()
        about = QAction("&About XRDLab", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    # -- updates -------------------------------------------------------------
    def start_update_check(self, manual: bool = False) -> None:
        """Fetch + fast-forward to the newest published version in the background."""
        import threading

        from PySide6.QtCore import QObject, Signal

        from xrdlab import updater

        if not updater.is_managed():
            if manual:
                QMessageBox.information(
                    self, "Updates",
                    "This copy isn't linked to the shared repository (it wasn't "
                    "installed with git clone), so it can't update itself.")
            return

        class _Bridge(QObject):
            done = Signal(object)

        self._update_bridge = _Bridge()
        self._update_bridge.done.connect(lambda r: self._on_update_result(r, manual))
        if manual:
            self.statusBar().showMessage("Checking for updates …")
        threading.Thread(target=lambda: self._update_bridge.done.emit(updater.update()),
                         daemon=True).start()

    def _on_update_result(self, r: dict, manual: bool) -> None:
        if r.get("updated"):
            changes = "\n".join(f"  • {c}" for c in r.get("changes", []))
            deps = "\nDependencies were updated too." if r.get("deps") else ""
            self.statusBar().showMessage(
                f"XRDLab updated ({r['from']} → {r['to']}) — restart to use it.", 0)
            QMessageBox.information(
                self, "XRDLab updated",
                f"A new version was installed ({r['n_commits']} change"
                f"{'s' if r['n_commits'] != 1 else ''}):\n{changes}{deps}\n\n"
                "Restart XRDLab to use it. Save your work first.")
        elif manual:
            msg = r.get("error") or r.get("skipped") or "Up to date."
            if r.get("skipped") == "up to date":
                msg = "You have the latest version."
            self.statusBar().showMessage(f"Updates: {msg}", 6000)
            QMessageBox.information(self, "Updates", msg)

    def _about(self) -> None:
        from xrdlab import updater

        QMessageBox.about(
            self, "About XRDLab",
            f"<b>XRDLab</b> — XRD / HRXRD analysis and publication figures<br>"
            f"Version: {updater.version()}<br>Installed at: {updater.ROOT}")

    def _set_crossref_email(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        from xrdlab import config

        current = config.get_crossref_mailto()
        text, ok = QInputDialog.getText(
            self, "Crossref contact email",
            "Optional email for the Crossref polite pool (improves reliability of "
            "citation lookups; leave blank to skip):",
            text=current,
        )
        if ok:
            config.set_crossref_mailto(text)

    def _set_instrument_fwhm(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        from xrdlab import config

        cur = config.get_instrument_fwhm()
        val, ok = QInputDialog.getDouble(
            self, "Instrument broadening",
            "Instrumental FWHM (°2θ) from a standard (LaB₆ / Si). 0 = no correction:",
            cur, 0.0, 2.0, 4,
        )
        if ok:
            config.set_instrument_fwhm(val)
            self.statusBar().showMessage(
                f"Instrument FWHM {val:.4f}° — Scherrer sizes now corrected." if val
                else "Instrument broadening correction disabled.", 4000)

    # -- undo / redo ---------------------------------------------------------
    def _snapshot(self) -> None:
        """Record the current project state so the next change can be undone."""
        try:
            self._undo_stack.append(self._gather_project())
        except Exception:  # noqa: BLE001
            return
        del self._undo_stack[:-25]  # bound the history
        self._redo_stack.clear()
        self._refresh_undo_actions()

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self._gather_project())
        self._apply_project(self._undo_stack.pop())
        self._refresh_undo_actions()
        self.statusBar().showMessage("Undo.", 2000)

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self._gather_project())
        self._apply_project(self._redo_stack.pop())
        self._refresh_undo_actions()
        self.statusBar().showMessage("Redo.", 2000)

    def _refresh_undo_actions(self) -> None:
        self._undo_act.setEnabled(bool(self._undo_stack))
        self._redo_act.setEnabled(bool(self._redo_stack))

    # -- recent projects / last directory ------------------------------------
    def _rebuild_recent_menu(self) -> None:
        from xrdlab import config

        self._recent_menu.clear()
        recent = config.get_recent_projects()
        if not recent:
            act = self._recent_menu.addAction("(none yet)")
            act.setEnabled(False)
            return
        for p in recent:
            act = self._recent_menu.addAction(Path(p).name)
            act.setToolTip(p)
            act.triggered.connect(lambda _=False, path=p: self._open_project_path(path))

    def _last_dir(self) -> str:
        from xrdlab import config

        return str(config.get_value("last_dir", "") or "")

    def _remember_dir(self, path: str) -> None:
        from xrdlab import config

        config.set_value("last_dir", str(Path(path).parent))

    # -- autosave / crash recovery -------------------------------------------
    def _autosave(self) -> None:
        if not self.pattern_panel.patterns_with_state():
            return
        try:
            from xrdlab import config
            from xrdlab.core.project import save_project

            save_project(config.CONFIG_DIR / "autosave.xrdlab", self._gather_project())
        except Exception:  # noqa: BLE001 — autosave must never interrupt work
            pass

    def _maybe_recover(self) -> None:
        from xrdlab import config
        from xrdlab.core.project import load_project

        path = config.CONFIG_DIR / "autosave.xrdlab"
        if not path.exists() or self.pattern_panel.patterns_with_state():
            return
        reply = QMessageBox.question(
            self, "Recover session",
            "An auto-saved session from a previous run was found. Restore it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self._apply_project(load_project(path))
                self.statusBar().showMessage("Recovered auto-saved session.", 5000)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Recovery failed", str(exc))

    def _manage_phase_db(self) -> None:
        from xrdlab.ui.dialogs import PhaseDatabaseDialog

        PhaseDatabaseDialog(self._phase_db, parent=self).exec()
        self._redraw_single()

    def _edit_filename_parsing(self) -> None:
        from xrdlab.core.naming import label_for
        from xrdlab.ui.dialogs import FilenameParsingDialog

        current = self.pattern_panel.current_pattern()
        example = current.meta.get("source_stem", "") if current else ""
        dialog = FilenameParsingDialog(example=example, parent=self)
        if dialog.exec():
            # Re-apply the new convention to any already-loaded patterns.
            self.pattern_panel.relabel(label_for)

    # -- project save / load -------------------------------------------------
    def _gather_project(self) -> dict:
        from xrdlab.core.project import (
            encode_keyed,
            serialize_pattern,
            serialize_reference,
        )

        dc, wc = self.display_controls, self.waterfall_controls
        return {
            "title": self.title_edit.text(),
            "patterns": [serialize_pattern(p, checked=c)
                         for p, c in self.pattern_panel.patterns_with_state()],
            "references": [serialize_reference(r) for r in self._references],
            "wf_guides": [dict(g) for g in self._wf_guides],
            "manual_labels": [dict(m) for m in self._manual_labels],
            "peak_overrides": encode_keyed(self._peak_overrides),
            "label_offsets": encode_keyed(self._label_offsets),
            "cleared": list(self._cleared),
            "controls": {
                "display_y_scale": dc.y_scale.currentText(),
                "label_peaks": dc.label_peaks.isChecked(),
                "sensitivity": dc.sensitivity.value(),
                "label_mode": dc.label_mode.currentText(),
                "identify_db": dc.identify_db.isChecked(),
                "show_fwhm": dc.show_fwhm.isChecked(),
                "tolerance": dc.tolerance.value(),
                "proc_strip_ka2": self.processing_controls.strip_ka2.isChecked(),
                "proc_subtract_bg": self.processing_controls.subtract_bg.isChecked(),
                "proc_smooth": self.processing_controls.smooth.isChecked(),
                "wf_gap": wc.gap.value(),
                "wf_normalize": wc.normalize.isChecked(),
                "wf_y_scale": wc.y_scale.currentText(),
                "wf_label_side": wc.label_side.currentText(),
                "wf_show_guides": wc.show_guides.isChecked(),
            },
        }

    def _apply_project(self, data: dict) -> None:
        from PySide6.QtCore import QSignalBlocker

        from xrdlab.core.project import (
            decode_keyed,
            deserialize_pattern,
            deserialize_reference,
        )

        dc, wc = self.display_controls, self.waterfall_controls
        # Block control/list signals so setting values doesn't trigger a redraw per
        # field (and per pattern) — we redraw once at the end.
        blockers = [QSignalBlocker(w) for w in (  # noqa: F841 — kept alive in scope
            self.pattern_panel, dc, wc, self.mp_panel, self.title_edit,
            self.processing_controls,
        )]

        self.pattern_panel.clear()
        for pd in data.get("patterns", []):
            self.pattern_panel.add_pattern_state(deserialize_pattern(pd),
                                                 pd.get("checked", True))
        self._references = [deserialize_reference(r) for r in data.get("references", [])]
        self._wf_guides = [dict(g) for g in data.get("wf_guides", [])]
        self._manual_labels = [dict(m) for m in data.get("manual_labels", [])]
        self._peak_overrides = decode_keyed(data.get("peak_overrides", []))
        self._label_offsets = decode_keyed(data.get("label_offsets", []))
        self._cleared = list(data.get("cleared", []))
        self.title_edit.setText(data.get("title", ""))

        c = data.get("controls", {})
        dc.y_scale.setCurrentText(c.get("display_y_scale", "log"))
        dc.label_peaks.setChecked(c.get("label_peaks", False))
        dc.sensitivity.setValue(c.get("sensitivity", 2.0))
        dc.label_mode.setCurrentText(c.get("label_mode", "Assigned only"))
        dc.identify_db.setChecked(c.get("identify_db", False))
        dc.show_fwhm.setChecked(c.get("show_fwhm", False))
        dc.tolerance.setValue(c.get("tolerance", 0.5))
        self.processing_controls.strip_ka2.setChecked(c.get("proc_strip_ka2", False))
        self.processing_controls.subtract_bg.setChecked(c.get("proc_subtract_bg", False))
        self.processing_controls.smooth.setChecked(c.get("proc_smooth", False))
        self._proc_cache.clear()
        wc.gap.setValue(c.get("wf_gap", 1.0))
        wc.normalize.setChecked(c.get("wf_normalize", True))
        wc.y_scale.setCurrentText(c.get("wf_y_scale", "log"))
        wc.label_side.setCurrentText(c.get("wf_label_side", "right"))
        wc.show_guides.setChecked(c.get("wf_show_guides", True))

        del blockers  # unblock before the single, deliberate redraw
        self._redraw_single()
        self._redraw_waterfall()
        self._redraw_citations()

    def _open_project(self) -> None:
        from xrdlab.core.project import PROJECT_FILTER

        path, _ = QFileDialog.getOpenFileName(
            self, "Open project or overlay", self._last_dir(), PROJECT_FILTER
        )
        if path:
            self._open_project_path(path)

    def _gather_overlay(self) -> dict:
        """The multi-pattern comparison only: checked scans (in stack order), their
        reference overlays, guides and view settings."""
        data = self._gather_project()
        data["patterns"] = [p for p in data["patterns"] if p.get("checked", True)]
        return data

    def _export_overlay(self) -> None:
        from xrdlab.core.project import OVERLAY_EXT, OVERLAY_FILTER

        if not self.pattern_panel.checked_patterns():
            QMessageBox.information(
                self, "Export overlay",
                "Tick the patterns to include in the overlay (pattern list) first.")
            return
        stem = Path(self._project_path).stem if self._project_path else "overlay"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export overlay", str(Path(self._last_dir()) / f"{stem}{OVERLAY_EXT}"),
            OVERLAY_FILTER,
        )
        if not path:
            return
        if not path.lower().endswith(OVERLAY_EXT):
            path += OVERLAY_EXT
        self._write_project(path)  # .xrdov → overlay contents
        self._remember_dir(path)

    def _open_project_path(self, path: str) -> None:
        from xrdlab.core.project import load_project

        if not Path(path).exists():
            QMessageBox.warning(self, "Open project failed", f"File not found:\n{path}")
            return
        try:
            data = load_project(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Open project failed", str(exc))
            return
        self._apply_project(data)
        self._set_project_path(path)
        self._remember_dir(path)
        n = len(data.get("patterns", []))
        kind = data.get("kind", "project")
        if kind == "overlay":  # an overlay file is the comparison view
            self.tabs.setCurrentWidget(self.waterfall_plot)
        self.statusBar().showMessage(f"Opened {kind} {Path(path).name} ({n} patterns).", 5000)

    def _save_project(self) -> None:
        if self._project_path is None:
            self._save_project_as()
            return
        self._write_project(self._project_path)

    def _save_project_as(self) -> None:
        from xrdlab.core.project import PROJECT_EXT, PROJECT_SAVE_FILTER

        start = self._project_path if (self._project_path or "").endswith(PROJECT_EXT) \
            else str(Path(self._last_dir()) / f"session{PROJECT_EXT}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project as", start, PROJECT_SAVE_FILTER
        )
        if not path:
            return
        if not path.lower().endswith(PROJECT_EXT):
            path += PROJECT_EXT
        self._write_project(path)
        self._set_project_path(path)
        self._remember_dir(path)

    def _write_project(self, path: str) -> None:
        """Save to ``path``; a .xrdov path gets overlay contents (checked scans only)."""
        from xrdlab.core.project import OVERLAY_EXT, save_project

        overlay = path.lower().endswith(OVERLAY_EXT)
        try:
            save_project(path, self._gather_overlay() if overlay else self._gather_project())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        what = "overlay" if overlay else "project"
        self.statusBar().showMessage(f"Saved {what} → {Path(path).name}", 4000)

    def _set_project_path(self, path: str) -> None:
        from xrdlab import config

        self._project_path = path
        self.setWindowTitle(f"XRDLab — {Path(path).name}")
        config.add_recent_project(path)
        if hasattr(self, "_recent_menu"):
            self._rebuild_recent_menu()

    # -- file loading --------------------------------------------------------
    def _open_patterns(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open diffraction patterns", self._last_dir(), _PATTERN_FILTER
        )
        if paths:
            self._snapshot()
            self._remember_dir(paths[0])
        for p in paths:
            self._load_pattern_file(p)

    def _load_pattern_file(self, path: str) -> None:
        if str(path).lower().endswith(".xrdml"):
            from xrdlab.core.xrdml import is_area_measurement

            if is_area_measurement(path):  # a reciprocal-space map, not a line scan
                self._open_rsm_path(path)
                return
        try:
            pattern = read_pattern(path)
        except Exception as exc:  # noqa: BLE001 — surface to the user
            QMessageBox.warning(self, "Load failed", f"{Path(path).name}:\n{exc}")
            return
        self._apply_naming(pattern)
        self.pattern_panel.add_pattern(pattern)
        self.statusBar().showMessage(f"Loaded {Path(path).name}", 4000)

    def _apply_naming(self, pattern) -> None:
        """Derive the display label from the filename via the configured regex."""
        from xrdlab.core.naming import label_for, parse_filename

        stem = pattern.meta.get("source_stem", pattern.name)
        pattern.meta["source_stem"] = stem
        pattern.meta["filename_fields"] = parse_filename(stem)
        pattern.name = label_for(stem)

    def _open_rietveld(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Rietveld CSV", "", "CSV (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            self._rietveld = read_rietveld_csv(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Load failed", str(exc))
            return
        self._redraw_rietveld()
        self.tabs.setCurrentWidget(self.rietveld_plot)

    # -- drag & drop ---------------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def open_path(self, path: str) -> None:
        """Open any supported file: a project/overlay session, or a scan to add."""
        from xrdlab.core.project import SESSION_EXTS

        if Path(path).suffix.lower() in SESSION_EXTS:
            self._open_project_path(path)
        else:
            self._snapshot()
            self._load_pattern_file(path)

    def dropEvent(self, event) -> None:  # noqa: N802
        from xrdlab.core.project import SESSION_EXTS

        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if Path(path).suffix.lower() in SESSION_EXTS:
                self._open_project_path(path)
                continue
            if path.lower().endswith(".csv"):
                # Ambiguous: try Rietveld first, fall back to a pattern.
                try:
                    self._rietveld = read_rietveld_csv(path)
                    self._redraw_rietveld()
                    continue
                except Exception:  # noqa: BLE001
                    pass
            self._load_pattern_file(path)

    # -- redraw --------------------------------------------------------------
    def _apply_yscale(self, ax) -> None:
        """Set the Single-view y-axis scale (real count ticks, XRD-style spacing)."""
        mode = self.display_controls.y_scale.currentText()
        if mode == "sqrt":
            ax.set_yscale(
                "function",
                functions=(lambda a: np.sqrt(np.clip(a, 0, None)), lambda a: np.square(a)),
            )
            ax.set_ylim(bottom=0)
        elif mode == "log":
            ax.set_yscale("log")
            ax.set_ylim(bottom=1)

    def _processing_sig(self):
        p = self.processing_controls
        return (p.strip_ka2.isChecked(), p.subtract_bg.isChecked(), p.smooth.isChecked())

    def _processed_pattern(self, pattern):
        """Apply the enabled non-destructive transforms; cached, original untouched."""
        sig = self._processing_sig()
        if not any(sig):
            return pattern
        cached = self._proc_cache.get(_pkey(pattern))
        if cached and cached[0] == sig:
            return cached[1]
        from xrdlab.core.processing import (
            background_als,
            smooth_savgol,
            strip_kalpha2,
        )

        strip, bg, smooth = sig
        x = pattern.two_theta
        y = np.asarray(pattern.intensity, dtype=float)
        if strip and hrxrd.is_two_theta(pattern):
            ka1 = float(pattern.wavelength)
            y = strip_kalpha2(x, y, ka1, ka1 * 1.002468)  # ~Cu Kα2/Kα1 ratio
        if bg:
            y = np.clip(y - background_als(y), 0.0, None)
        if smooth:
            y = smooth_savgol(y)
        proc = pattern.with_intensity(y)
        self._proc_cache[_pkey(pattern)] = (sig, proc)
        return proc

    def _on_processing_changed(self) -> None:
        self._proc_cache.clear()
        self._peak_cache.clear()  # detection depends on the processed signal
        self._redraw_single()
        self._redraw_waterfall()
        self._redraw_citations()

    def _detect_and_identify(self, pattern, use_db: bool) -> list:
        """Detect peaks, assign from overlaid references, and optionally the DB.

        The expensive part — peak finding + FWHM, which depends only on the data and
        sensitivity — is cached per pattern; cheap assignment (references / DB /
        overrides) is redone each call so labels always reflect the current state.
        """
        from xrdlab.ml.labeling import PeakLabel

        raw = pattern
        pattern = self._processed_pattern(pattern)  # detect on the processed signal
        tol = self.display_controls.tolerance.value()
        frac = self.display_controls.sensitivity.value() / 100.0
        sig = (round(frac, 6), len(pattern), self._processing_sig())
        cached = self._peak_cache.get(_pkey(raw))
        if cached and cached[0] == sig:
            base = cached[1]
        else:
            found = ProminencePeakLabeler(min_prominence_frac=frac).label(pattern)
            self._measure_fwhm(pattern, found)
            base = [(p.two_theta, p.intensity, p.fwhm) for p in found]
            self._peak_cache[_pkey(raw)] = (sig, base)
        peaks = [PeakLabel(two_theta=tt, intensity=inten, fwhm=fw)
                 for tt, inten, fw in base]
        if self._references:
            assign_peaks(peaks, self._references, tol_deg=tol)
        if use_db and len(self._phase_db):
            self._phase_db.identify_peaks(peaks, float(pattern.wavelength), tol_deg=tol)
        # Manual overrides (from click-a-peak) win over automatic assignment.
        for pk in peaks:
            key = round(pk.two_theta, 1)
            if key in self._peak_overrides:
                override = self._peak_overrides[key]
                if override is None:  # explicitly cleared
                    pk.label, pk.hkl = "", None
                else:
                    pk.label, pk.hkl = override[0], override[1]
        self._last_peaks = peaks
        return peaks

    def _measure_fwhm(self, pattern, peaks) -> None:
        """Attach the data FWHM (°2θ) to each detected peak."""
        from xrdlab.core.processing import peak_fwhm

        x, y = pattern.two_theta, pattern.intensity
        if not peaks:
            return
        # Peak 2θ values come straight from the x grid, so a single searchsorted
        # locates every index (nearest of the two bracketing samples) — no per-peak
        # argmin scan of the whole array.
        tts = np.fromiter((p.two_theta for p in peaks), dtype=float, count=len(peaks))
        j = np.clip(np.searchsorted(x, tts), 1, len(x) - 1)
        left_closer = np.abs(tts - x[j - 1]) <= np.abs(tts - x[j])
        idx = np.where(left_closer, j - 1, j)
        for pk, i in zip(peaks, idx):
            fwhm = peak_fwhm(x, y, int(i))[0]
            pk.fwhm = None if np.isnan(fwhm) else float(fwhm)

    def _labels_for_curve(self, pattern, max_labels: int = 10, min_sep: float = 2.5) -> list:
        """Clean per-curve waterfall labels: merge Kα2, then greedily pick the
        strongest, skipping any within ``min_sep`` degrees so nothing overlaps."""
        use_db = self.display_controls.identify_db.isChecked()
        label_all = self.display_controls.label_mode.currentText() == "All peaks"
        peaks = [p for p in self._detect_and_identify(pattern, use_db=use_db)
                 if not self._is_cleared(p.two_theta)]

        merged: list = []
        for pk in sorted(peaks, key=lambda p: p.two_theta):
            window = 0.25 + 0.004 * pk.two_theta
            if merged and abs(pk.two_theta - merged[-1].two_theta) < window:
                if pk.intensity > merged[-1].intensity:
                    merged[-1] = pk
            else:
                merged.append(pk)

        eligible = [pk for pk in merged if pk.label or label_all]
        chosen: list = []
        for pk in sorted(eligible, key=lambda p: -p.intensity):
            if any(abs(pk.two_theta - c.two_theta) < min_sep for c in chosen):
                continue
            chosen.append(pk)
            if len(chosen) >= max_labels:
                break

        out = []
        for pk in sorted(chosen, key=lambda p: p.two_theta):
            if pk.label:
                out.append((pk.two_theta, _phase_text(pk.label, pk.hkl)))
            else:
                out.append((pk.two_theta, f"{pk.two_theta:.1f}°"))
        return out

    def _candidates_for(self, two_theta: float, wavelength: float, tol: float) -> list:
        """All phase candidates within ``tol`` of ``two_theta`` (deduped, closest-first)."""
        uniq: dict[tuple, object] = {}
        for c in self._phase_db.identify(two_theta, wavelength, tol):
            key = (c.formula, c.hkl)
            if key not in uniq or c.delta_deg < uniq[key].delta_deg:
                uniq[key] = c
        return sorted(uniq.values(), key=lambda c: c.delta_deg)

    def _label_peaks(self, ax, pattern) -> None:
        """Annotate peaks; co-located phases are listed together, comma-separated."""
        peaks = [p for p in self._detect_and_identify(
            pattern, use_db=self.display_controls.identify_db.isChecked())
            if not self._is_cleared(p.two_theta)]
        wavelength = float(pattern.wavelength)
        tol = self.display_controls.tolerance.value()
        use_db = self.display_controls.identify_db.isChecked()
        label_all = self.display_controls.label_mode.currentText() == "All peaks"

        # Merge near-coincident detections (Kα2 shoulders / doublets); keep the
        # strongest. The split widens with angle, so scale the merge window.
        merged: list = []
        for pk in sorted(peaks, key=lambda p: p.two_theta):
            window = 0.25 + 0.004 * pk.two_theta  # ~0.35° at 25°, ~0.7° at 110°
            if merged and abs(pk.two_theta - merged[-1].two_theta) < window:
                if pk.intensity > merged[-1].intensity:
                    merged[-1] = pk
            else:
                merged.append(pk)

        show_fwhm = self.display_controls.show_fwhm.isChecked()

        def _with_fwhm(text: str, pk) -> str:
            if show_fwhm and pk.fwhm:
                return f"{text}  ·  FWHM {pk.fwhm:.3f}°"
            return text

        labelled_any = False
        rendered_overrides: set = set()
        for pk in merged:
            key = round(pk.two_theta, 1)
            override = self._peak_overrides.get(key, "auto")
            if override not in ("auto", None):
                rendered_overrides.add(key)
                text, color = _phase_text(override[0], override[1]), "#111111"
            elif override is None:  # explicitly cleared
                rendered_overrides.add(key)
                if not label_all:
                    continue
                text, color = f"{pk.two_theta:.2f}°", "#777777"
            else:
                cands = self._candidates_for(pk.two_theta, wavelength, tol) if use_db else []
                if cands:
                    # Co-located phases, comma-separated (cap 3 to stay legible).
                    text = ", ".join(_phase_text(c.formula, c.hkl) for c in cands[:3])
                    if len(cands) > 3:
                        text += ", …"
                    color = "#111111"
                elif pk.label:  # from an overlaid reference (DB off)
                    text = _phase_text(pk.label, pk.hkl)
                    color = "#111111"
                elif label_all:
                    text, color = f"{pk.two_theta:.2f}°", "#777777"
                else:
                    continue
            self._annotate(ax, ("peak", key), _with_fwhm(text, pk),
                           pk.two_theta, pk.intensity, color)
            labelled_any = True

        # Render manual overrides whose peak wasn't auto-detected (using the click
        # position/height stored at assignment time) so clicked labels always show.
        for key, override in self._peak_overrides.items():
            if key in rendered_overrides or override is None or len(override) < 4:
                continue
            self._annotate(ax, ("peak", key), _phase_text(override[0], override[1]),
                           override[2], override[3], "#111111")
            labelled_any = True

        # Headroom so vertical labels sit inside the frame, not over the title.
        if labelled_any:
            lo, hi = ax.get_ylim()
            if ax.get_yscale() == "log":
                ax.set_ylim(lo, hi * 40)  # ~1.6 extra decades above the tallest peak
            else:
                ax.set_ylim(lo, hi * 1.6)

    def _redraw_single(self) -> None:
        pattern = self.pattern_panel.current_pattern()
        fig = self.single_plot.figure
        fig.clear()
        if pattern is None and not self._references:
            self.single_plot.refresh()
            return
        ax = fig.add_subplot(111)
        if pattern is not None:
            from xrdlab.core.processing import decimate_for_display

            disp = self._processed_pattern(pattern)
            px, py = decimate_for_display(disp.two_theta, disp.intensity)
            ax.plot(px, py, lw=1.0, color="#1f77b4")
            two_theta_scan = hrxrd.is_two_theta(pattern)
            ax.set_xlabel(AXIS_LABELS["x"] if two_theta_scan
                          else hrxrd.axis_label(hrxrd.axis_of(pattern)))
            ax.set_ylabel(f"Intensity (counts) — {self.display_controls.y_scale.currentText()} scale")
            custom = self.title_edit.text().strip()
            if custom:
                ax.set_title(custom, pad=12, loc="center")
            else:
                ax.set_title(pattern.name, pad=12, loc="left")
            ax.set_xlim(*pattern.two_theta_range)
            self._apply_yscale(ax)
            self._draggable_anns = []
            # References and phase labels are positions in 2θ — they don't apply to
            # rocking curves (ω) or φ/χ scans, which get a scan-specific readout.
            refs = self._references if two_theta_scan else []
            for i, ref in enumerate(refs):
                # PDF-card tick row along the bottom (small, never touches data);
                # stacked per phase; every reflection is labelled.
                overlay_reference(ax, ref, tick_row=True, label_hkl=True,
                                  color=_REF_COLORS[i % len(_REF_COLORS)],
                                  row_base=i * 0.09)
            if two_theta_scan:
                if self.display_controls.label_peaks.isChecked():
                    self._label_peaks(ax, pattern)
            else:
                self._annotate_scan_peaks(ax, disp)
            self._render_manual_labels(ax, disp)
            if refs:
                ax.legend(loc="upper right")
            if custom:  # extra headroom so peak labels clear the centered title
                lo, hi = ax.get_ylim()
                ax.set_ylim(lo, hi * (8.0 if ax.get_yscale() == "log" else 1.4))
        else:
            # Reference(s) only, no measured pattern — draw the sticks alone.
            lo = min(float(r.two_theta.min()) for r in self._references)
            hi = max(float(r.two_theta.max()) for r in self._references)
            ax.set_xlim(lo, hi)
            ax.set_ylim(0, 105)
            ax.set_xlabel(AXIS_LABELS["x"])
            ax.set_ylabel("Relative intensity")
            names = ", ".join(r.formula for r in self._references)
            ax.set_title(f"{names} reference")
            for i, ref in enumerate(self._references):
                overlay_reference(ax, ref, scale=1.0, label_hkl=True,
                                  color=_REF_COLORS[i % len(_REF_COLORS)])
            ax.legend(loc="upper right")
        fig.tight_layout()
        self.single_plot.refresh()

    # -- labels: annotate, drag, add manually --------------------------------
    def _annotate(self, ax, key, text, x, y, color):
        """Draggable annotation whose position persists across redraws."""
        dx, dy = self._label_offsets.get(key, (0, 4))
        ann = ax.annotate(
            text, xy=(x, y), xytext=(dx, dy), textcoords="offset points",
            ha="center", va="bottom", fontsize=6.5, color=color,
            rotation=90, annotation_clip=False,
        )
        try:
            ann.draggable()
        except Exception:  # noqa: BLE001
            pass
        self._draggable_anns.append((key, ann))
        return ann

    def _pattern_key(self, pattern) -> str:
        return pattern.meta.get("source_stem", pattern.name)

    def _render_manual_labels(self, ax, pattern) -> None:
        key = self._pattern_key(pattern)
        x, y = pattern.two_theta, pattern.intensity
        for i, m in enumerate(self._manual_labels):
            if m.get("pattern") not in (None, key):
                continue  # this manual peak belongs to a different pattern
            idx = int(np.argmin(np.abs(x - m["x"])))
            py = float(y[idx])
            # A marker so a manually-added peak reads as a peak, plus its label.
            ax.plot([m["x"]], [py], marker="v", markersize=5, color="#0055aa",
                    zorder=5, clip_on=False)
            self._annotate(ax, ("manual", i), subscriptify(m["text"]), m["x"], py, "#0055aa")

    def _prompt_add_peak(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        pattern = self.pattern_panel.current_pattern()
        if pattern is None:
            QMessageBox.information(self, "Add peak", "Load a pattern first.")
            return
        lo, hi = pattern.two_theta_range
        val, ok = QInputDialog.getDouble(
            self, "Add peak", "2θ position (°) — snaps to the nearest peak:",
            (lo + hi) / 2.0, lo, hi, 2,
        )
        if ok:
            self._prompt_add_label(val)  # snaps to local max, then asks for a label
        self.tabs.setCurrentWidget(self.single_plot)

    # -- HRXRD ---------------------------------------------------------------
    def _guess_reflection(self, pattern) -> str:
        """Name the reflection a rocking curve was measured on, from its fixed 2θ."""
        tt = hrxrd.fixed_two_theta(pattern)
        if tt is None:
            return ""
        wl = float(pattern.wavelength)
        formulas = list(dict.fromkeys([r.formula for r in self._references]
                                      + self._phase_db.formulas()))
        best = None
        for f in formulas:
            for hkl, _d, t2, inten in self._phase_db.reflection_table(f, wl):
                dd = abs(t2 - tt)
                if dd < 0.4 and inten > 0 and (best is None or dd < best[0]):
                    best = (dd, f, hkl)
        return _phase_text(best[1], best[2]) if best else ""

    @staticmethod
    def _material_for(reflection: str) -> str:
        from xrdlab.core.naming import canonical_formula

        f = canonical_formula(reflection.split(" ")[0].translate(
            str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))) if reflection else ""
        for name in hrxrd.MATERIALS:
            if f and name.split(" ")[0] == f:
                return name
        return "GaN (wurtzite)"

    def _analyze_rocking_curve(self) -> None:
        from xrdlab import config
        from xrdlab.ui.hrxrd_dialogs import RockingCurvesDialog

        rcs = [p for p in self.pattern_panel.checked_patterns()
               if hrxrd.axis_of(p) == "Omega"]
        cur = self.pattern_panel.current_pattern()
        if not rcs and cur is not None and hrxrd.axis_of(cur) == "Omega":
            rcs = [cur]
        if not rcs:
            QMessageBox.information(
                self, "Rocking curves",
                "No ω rocking curves are loaded/checked.\n\nLoad the .xrdml files of "
                "your ω scans (scan axis 'Omega') — XRDLab reads them on an ω axis "
                "automatically — and tick them in the pattern list. Coupled 2θ-ω scans "
                "are analysed with the other HRXRD tools.")
            return
        guess = self._guess_reflection(rcs[0])
        dlg = RockingCurvesDialog(
            rcs, parent=self, reflection_guess=self._guess_reflection,
            instrument_arcsec=float(config.get_value("instrument_omega_arcsec", 0.0) or 0),
            material=config.get_value("hrxrd_material") or self._material_for(guess))
        dlg.exec()
        config.set_value("instrument_omega_arcsec", dlg.instr.value() or None)
        config.set_value("hrxrd_material", dlg.material.currentText())

    def _scan_record(self, p) -> dict:
        """FWHM-tab record for a non-2θ scan (dominant peak, e.g. a rocking curve)."""
        from xrdlab.core.fitting import doublet_kwargs

        m = hrxrd.rocking_curve_metrics(p.two_theta, p.intensity,
                                        fit_kwargs=doublet_kwargs(p))
        axis = hrxrd.axis_of(p)
        tt = hrxrd.fixed_two_theta(p)
        name = {"Omega": "ω", "Phi": "φ", "Chi": "χ"}.get(axis, axis)
        refl = self._guess_reflection(p) if axis == "Omega" else ""
        key = f"{name} scan" + (f" {refl}" if refl else
                                (f" @ 2θ {tt:.1f}°" if tt is not None else ""))
        return {"sample": p.name, "temperature_C": self._temperature_of(p),
                "reflection": key, "two_theta": m["peak"], "intensity": m["peak_counts"],
                "fwhm_data": m["fwhm_data"], "fwhm_fit": m["fwhm_fit"], "eta": m["eta"],
                "r_squared": m["r_squared"], "size_nm": float("nan"),
                "fit_model": "pseudo-Voigt" + (" Kα1+Kα2" if m["doublet"] else "")}

    def _annotate_scan_peaks(self, ax, pattern) -> None:
        """Single-view readout for non-2θ scans: RC fit + FWHM, or φ-scan peaks."""
        from xrdlab.core.fitting import doublet_kwargs

        axis = hrxrd.axis_of(pattern)
        x, y = pattern.two_theta, pattern.intensity
        box = dict(boxstyle="round", fc="white", ec="#999", alpha=0.85)
        if axis == "Omega":
            m = hrxrd.rocking_curve_metrics(x, y, fit_kwargs=doublet_kwargs(pattern))
            if m["fit"] is not None:
                xs = np.linspace(x.min(), x.max(), 1500)
                ax.plot(xs, np.clip(m["fit"].model(xs), 1e-3, None), "--", lw=0.9,
                        color="#d62728", label="pseudo-Voigt fit")
            tt = hrxrd.fixed_two_theta(pattern)
            txt = (f"ω = {m['peak']:.4f}°" + (f"  (2θ = {tt:.3f}°)" if tt else "")
                   + f"\nFWHM {m['fwhm_arcsec']:.0f}″ ({m['fwhm']:.4f}°)")
            ax.text(0.02, 0.97, txt, transform=ax.transAxes, va="top", fontsize=8, bbox=box)
        elif axis == "Phi":
            r = hrxrd.phi_symmetry(x, y)
            for p_ in r["peaks"]:
                ax.axvline(p_, color="#d62728", lw=0.6, ls=":")
            ax.text(0.02, 0.97, f"{r.get('n_peaks', 0)} peaks · {r['n_fold']}-fold",
                    transform=ax.transAxes, va="top", fontsize=8, bbox=box)

    def _require(self, axis: str, title: str):
        p = self.pattern_panel.current_pattern()
        if p is None:
            QMessageBox.information(self, title, "Load and select a scan first.")
            return None
        if hrxrd.axis_of(p) != axis:
            want = {"2Theta": "a coupled 2θ-ω scan", "Phi": "a φ scan",
                    "Omega": "an ω rocking curve"}[axis]
            QMessageBox.information(
                self, title, f"Select {want} in the pattern list — '{p.name}' is a "
                f"{hrxrd.axis_label(hrxrd.axis_of(p))} scan.")
            return None
        return p

    def _labelled_peaks(self, p):
        use_db = self.display_controls.identify_db.isChecked()
        peaks = self._merge_kalpha([q for q in self._detect_and_identify(p, use_db=use_db)
                                    if not self._is_cleared(q.two_theta)])
        return [(_phase_text(q.label, q.hkl) if q.label else f"{q.two_theta:.2f}°", q)
                for q in peaks]

    def _hrxrd_thickness(self) -> None:
        from xrdlab.ui.hrxrd_dialogs import ThicknessDialog

        p = self._require("2Theta", "Film thickness")
        if p is None:
            return
        lp = sorted(self._labelled_peaks(p), key=lambda t: -t[1].intensity)
        ThicknessDialog(p, [(lab, q.two_theta) for lab, q in lp], parent=self).exec()

    def _hrxrd_wh(self) -> None:
        from xrdlab import config
        from xrdlab.ui.hrxrd_dialogs import WilliamsonHallDialog

        p = self._require("2Theta", "Williamson–Hall")
        if p is None:
            return
        assigned = [(lab, q) for lab, q in self._labelled_peaks(p) if q.label]
        if len(assigned) < 2:
            QMessageBox.information(
                self, "Williamson–Hall",
                "Needs at least two assigned reflections of one phase (e.g. ScN 111 and "
                "222). Overlay a reference or enable 'Identify from phase database'.")
            return
        WilliamsonHallDialog(p, assigned, parent=self,
                             instrument_fwhm_deg=config.get_instrument_fwhm()).exec()

    def _hrxrd_phi(self) -> None:
        from xrdlab.ui.hrxrd_dialogs import PhiScanDialog

        p = self._require("Phi", "φ-scan symmetry")
        if p is not None:
            PhiScanDialog(p, parent=self).exec()

    def _analyze_lattice(self) -> None:
        pattern = self.pattern_panel.current_pattern()
        if pattern is None:
            QMessageBox.information(self, "Lattice / strain", "Load/select a scan first.")
            return
        use_db = self.display_controls.identify_db.isChecked()
        peaks = [p for p in self._detect_and_identify(pattern, use_db=use_db)
                 if p.hkl is not None]
        if not peaks:
            QMessageBox.information(
                self, "Lattice / strain",
                "No peaks have an assigned (h k l). Overlay a reference or turn on "
                "'Identify from phase database', or click-assign peaks first.",
            )
            return
        from xrdlab.ui.dialogs import LatticeDialog

        LatticeDialog(pattern, peaks, parent=self).exec()

    def _open_rsm(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open reciprocal-space map", self._last_dir(),
            "Reciprocal-space map (*.xrdml *.csv);;All files (*)",
        )
        if path:
            self._open_rsm_path(path)

    def _open_rsm_path(self, path: str) -> None:
        from xrdlab.ui.hrxrd_dialogs import RSMDialog, rsm_from_csv

        try:
            if str(path).lower().endswith(".xrdml"):
                from xrdlab.core.xrdml import read_xrdml_area

                data = read_xrdml_area(path)
            else:
                data = rsm_from_csv(path)
            dlg = RSMDialog(data, parent=self)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Reciprocal-space map", f"{Path(path).name}:\n{exc}")
            return
        self._remember_dir(path)
        self._rsm_windows = [w for w in getattr(self, "_rsm_windows", []) if w.isVisible()]
        self._rsm_windows.append(dlg)
        dlg.show()  # non-modal: several maps can be open side by side
        self.statusBar().showMessage(
            f"Opened reciprocal-space map {Path(path).name} "
            f"({data.get('n_scans', '?')} scans).", 5000)

    # -- FWHM comparison -----------------------------------------------------
    @staticmethod
    def _merge_kalpha(peaks) -> list:
        """Collapse near-coincident detections (Kα2 shoulders) to the strongest."""
        merged: list = []
        for pk in sorted(peaks, key=lambda p: p.two_theta):
            window = 0.25 + 0.004 * pk.two_theta  # the doublet split grows with angle
            if merged and abs(pk.two_theta - merged[-1].two_theta) < window:
                if pk.intensity > merged[-1].intensity:
                    merged[-1] = pk
            else:
                merged.append(pk)
        return merged

    @staticmethod
    def _temperature_of(pattern) -> float | None:
        """Growth/anneal temperature (°C) from the label or file name, if present."""
        import re

        for text in (pattern.name or "", pattern.meta.get("source_stem", "")):
            m = re.search(r"(\d+(?:\.\d+)?)\s*°?\s*C(?![a-z])", text)
            if m:
                return float(m.group(1))
        return None

    def _fit_cached(self, pattern, index: int, kw: dict):
        from xrdlab.core.fitting import fit_peak

        key = (_pkey(pattern), round(float(pattern.two_theta[index]), 4), bool(kw))
        if key not in self._fit_cache:
            self._fit_cache[key] = fit_peak(pattern.two_theta, pattern.intensity,
                                            index, **kw)
        return self._fit_cache[key]

    def _fwhm_records(self):
        """Measure every reflection in every checked pattern (for the FWHM tab)."""
        from xrdlab import config
        from xrdlab.core.fitting import doublet_kwargs
        from xrdlab.core.processing import scherrer_size

        instr = config.get_instrument_fwhm()
        use_db = self.display_controls.identify_db.isChecked()
        label_all = self.display_controls.label_mode.currentText() == "All peaks"
        from xrdlab.core.processing import peak_fwhm
        from xrdlab.ml.labeling import PeakLabel

        samples, records, clusters = [], [], []  # clusters: unassigned 2θ groups
        per_sample = []  # (pattern, {reflection: peak})
        for p in self.pattern_panel.checked_patterns():
            samples.append((p.name, self._temperature_of(p)))
            if not hrxrd.is_two_theta(p):  # rocking curve / φ scan: dominant peak
                records.append(self._scan_record(p))
                continue
            peaks = [q for q in self._detect_and_identify(p, use_db=use_db)
                     if not self._is_cleared(q.two_theta)]
            best: dict = {}
            for pk in self._merge_kalpha(peaks):
                if pk.label:
                    key = _phase_text(pk.label, pk.hkl)
                elif label_all:  # group unassigned peaks across samples by position
                    near = [c for c in clusters if abs(c - pk.two_theta) < 0.5]
                    if not near:
                        clusters.append(pk.two_theta)
                    key = f"{(near[0] if near else pk.two_theta):.1f}°"
                else:
                    continue
                if key not in best or pk.intensity > best[key].intensity:
                    best[key] = pk
            per_sample.append((p, best))

        # A reflection found in some samples but below the detection threshold in
        # another (a weak peak next to a huge substrate line) is still measured there
        # if a real maximum stands well clear of counting noise near the position the
        # other samples give.
        where: dict = {}
        for _p, best in per_sample:
            for key, pk in best.items():
                where.setdefault(key, []).append(pk.two_theta)
        for p, best in per_sample:
            x, y = p.two_theta, p.intensity
            for key, positions in where.items():
                if key in best:
                    continue
                target = float(np.median(positions))
                win = np.where(np.abs(x - target) <= 0.5)[0]
                ring = np.where(np.abs(x - target) <= 2.0)[0]
                if win.size < 5:
                    continue
                i = int(win[np.argmax(y[win])])
                bg = float(np.percentile(y[ring], 10))
                if i in (win[0], win[-1]) or y[i] - bg < 10.0 * np.sqrt(max(bg, 1.0)):
                    continue  # not a real, clearly resolved peak
                fw = peak_fwhm(x, y, i)[0]
                best[key] = PeakLabel(two_theta=float(x[i]), intensity=float(y[i]),
                                      fwhm=None if np.isnan(fw) else float(fw))

        for p, best in per_sample:
            # Fit the raw scan: the doublet model handles Kα2; processing is display-only.
            kw = doublet_kwargs(p)
            x = p.two_theta
            for key, pk in best.items():
                i = int(np.clip(np.searchsorted(x, pk.two_theta), 0, len(x) - 1))
                fit = self._fit_cached(p, i, kw)
                ok = fit is not None and fit.r_squared > 0.8
                width = fit.fwhm if ok else (pk.fwhm or float("nan"))
                records.append({
                    "sample": p.name, "temperature_C": self._temperature_of(p),
                    "reflection": key,
                    "two_theta": fit.center if ok else pk.two_theta,
                    "intensity": pk.intensity,
                    "fwhm_data": pk.fwhm if pk.fwhm else float("nan"),
                    "fwhm_fit": fit.fwhm if ok else float("nan"),
                    "eta": fit.eta if ok else float("nan"),
                    "r_squared": fit.r_squared if fit else float("nan"),
                    "size_nm": scherrer_size(width, pk.two_theta, float(p.wavelength),
                                             instrument_fwhm_deg=instr)
                    if np.isfinite(width) else float("nan"),
                    "fit_model": ("pseudo-Voigt Kα1+Kα2" if kw else "pseudo-Voigt")
                    if ok else "",
                })
        corr = (f"corrected for instrumental FWHM {instr:.3f}°" if instr
                else "not corrected for instrumental broadening (upper bound)")
        note = (f"{len(samples)} checked patterns · fit = doublet-aware pseudo-Voigt; "
                f"width reported is Kα1 · size = Scherrer (K=0.9), {corr}. "
                "Uses the Peaks panel's sensitivity, match tolerance and label mode.")
        return samples, records, note

    def _refresh_fwhm(self) -> None:
        samples, records, note = self._fwhm_records()
        self.fwhm_view.set_data(samples, records, note)

    def _refresh_fwhm_if_visible(self) -> None:
        if self.tabs.currentWidget() is self.fwhm_view:
            self._refresh_fwhm()

    def _show_peak_table(self) -> None:
        pattern = self.pattern_panel.current_pattern()
        if pattern is None:
            QMessageBox.information(self, "Peak table", "Load a pattern first.")
            return
        from xrdlab.ui.dialogs import PeakTableDialog

        use_db = self.display_controls.identify_db.isChecked()
        peaks = [p for p in self._detect_and_identify(pattern, use_db=use_db)
                 if not self._is_cleared(p.two_theta)]
        PeakTableDialog(pattern, peaks, parent=self).exec()

    def _on_label_release(self, event) -> None:
        """After a drag, remember each label's offset so it survives redraws."""
        for key, ann in self._draggable_anns:
            try:
                self._label_offsets[key] = (float(ann.xyann[0]), float(ann.xyann[1]))
            except Exception:  # noqa: BLE001
                pass

    # -- interaction: left-drag labels, right-click menu for everything ------
    def _on_single_click(self, event) -> None:
        """Left-click drags labels (matplotlib native); right-click opens the menu."""
        if event.button == 3 and event.inaxes is not None and event.xdata is not None:
            self._show_context_menu(event)
        # Left / middle clicks are ignored so draggable labels can be moved.

    def _prompt_add_label(self, x: float) -> None:
        from PySide6.QtWidgets import QInputDialog

        pattern = self.pattern_panel.current_pattern()
        if pattern is None:
            return
        xarr, yarr = pattern.two_theta, pattern.intensity
        x0, x1 = self.single_plot.figure.axes[0].get_xlim()
        window = max(0.5, 0.02 * abs(x1 - x0))
        near = np.abs(xarr - x) <= window
        px = float(xarr[np.where(near)[0][np.argmax(yarr[near])]]) if near.any() else float(x)
        text, ok = QInputDialog.getText(self, "Add label", f"Label text at {px:.2f}°:")
        if ok and text.strip():
            self._snapshot()
            self._manual_labels.append(
                {"x": px, "text": text.strip(), "pattern": self._pattern_key(pattern)}
            )
            self._redraw_single()
            self._redraw_waterfall()

    def _edit_manual(self, i: int) -> None:
        from PySide6.QtWidgets import QInputDialog

        if not (0 <= i < len(self._manual_labels)):
            return
        text, ok = QInputDialog.getText(
            self, "Edit label", "Label text (use _ for subscripts, e.g. Al_2O_3):",
            text=self._manual_labels[i]["text"],
        )
        if ok and text.strip():
            self._manual_labels[i]["text"] = text.strip()
            self._redraw_single()
            self._redraw_waterfall()

    def _delete_manual(self, i: int) -> None:
        if 0 <= i < len(self._manual_labels):
            self._manual_labels.pop(i)
            self._redraw_single()
            self._redraw_waterfall()

    def _clear_manual_labels(self) -> None:
        self._manual_labels = []
        self._redraw_single()
        self._redraw_waterfall()

    def _reset_label_positions(self) -> None:
        self._label_offsets = {}
        self._redraw_single()

    def _show_context_menu(self, event) -> None:
        import numpy as np
        from types import SimpleNamespace

        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        pattern = self.pattern_panel.current_pattern()
        if pattern is not None:
            x, y = pattern.two_theta, pattern.intensity
            x0, x1 = event.inaxes.get_xlim()
            window = max(0.5, 0.02 * abs(x1 - x0))
            near = np.abs(x - event.xdata) <= window
            if near.any():
                idx = int(np.where(near)[0][np.argmax(y[near])])
                px, py = float(x[idx]), float(y[idx])
                wl = float(pattern.wavelength)
                d = wl / (2.0 * np.sin(np.radians(px / 2.0)))
                head = menu.addAction(f"Peak {px:.2f}°    d = {d:.4f} Å")
                head.setEnabled(False)
                ov = self._peak_overrides.get(round(px, 1), "auto")
                if ov not in ("auto", None):
                    cur = menu.addAction(f"  current: {_phase_text(ov[0], ov[1])}")
                    cur.setEnabled(False)
                peak = SimpleNamespace(two_theta=px, intensity=py)
                cands = self._candidates_for(px, wl, tol=1.5)
                if cands:
                    sub = menu.addMenu("Assign phase")
                    for c in cands[:12]:
                        a = sub.addAction(
                            f"{_phase_text(c.formula, c.hkl)}   Δ{c.delta_deg:.2f}°  d={c.d:.3f} Å"
                        )
                        a.triggered.connect(
                            lambda _=False, pk=peak, cand=c: self._assign_override(pk, cand)
                        )
                # Delete the single nearest labelled peak to the click (handles
                # shoulders and lets you remove peaks one at a time).
                labelled = [p for p in self._last_peaks if p.label] or self._last_peaks
                if labelled:
                    tgt = min(labelled, key=lambda p: abs(p.two_theta - event.xdata))
                    clr = menu.addAction(f"Delete this peak label ({tgt.two_theta:.2f}°)")
                    clr.triggered.connect(lambda _=False, tt=tgt.two_theta: self._clear_at(tt))
                menu.addSeparator()
                add = menu.addAction(f"Add custom label at {px:.2f}°…")
                add.triggered.connect(lambda _=False, xx=px: self._prompt_add_label(xx))

                # Edit / delete the nearest custom label (only that one).
                cur_key = self._pattern_key(pattern)
                mine = [(i, m) for i, m in enumerate(self._manual_labels)
                        if m.get("pattern") in (None, cur_key)]
                if mine:
                    ni, nm = min(mine, key=lambda im: abs(im[1]["x"] - event.xdata))
                    if abs(nm["x"] - event.xdata) <= window:
                        ed = menu.addAction(f"Edit custom label “{nm['text']}”…")
                        ed.triggered.connect(lambda _=False, i=ni: self._edit_manual(i))
                        de = menu.addAction("Delete this custom label")
                        de.triggered.connect(lambda _=False, i=ni: self._delete_manual(i))

        if self._cleared:
            menu.addAction("Restore cleared peaks").triggered.connect(self._restore_cleared)
        if self._manual_labels:
            menu.addAction("Clear ALL custom labels").triggered.connect(self._clear_manual_labels)
        if self._label_offsets:
            menu.addAction("Reset label positions").triggered.connect(self._reset_label_positions)
        if not menu.isEmpty():
            menu.exec(QCursor.pos())

    def _is_cleared(self, two_theta: float) -> bool:
        # Tight window so you can delete individual peaks (incl. a shoulder next to
        # a main peak) without also removing its neighbour.
        return any(abs(c - two_theta) < 0.12 for c in self._cleared)

    def _clear_at(self, two_theta: float) -> None:
        self._cleared.append(round(float(two_theta), 2))
        self._redraw_single()
        self._redraw_waterfall()
        self._redraw_citations()

    def _restore_cleared(self) -> None:
        self._cleared = []
        self._redraw_single()
        self._redraw_waterfall()
        self._redraw_citations()

    def _assign_override(self, peak, candidate) -> None:
        self._snapshot()
        # Store the click position + height too, so the label renders even if the
        # peak is below the auto-detection threshold.
        self._peak_overrides[round(peak.two_theta, 1)] = (
            candidate.formula, candidate.hkl, peak.two_theta, peak.intensity,
        )
        self.statusBar().showMessage(
            f"{peak.two_theta:.2f}° → {candidate.formula} ({candidate.hkl})", 4000
        )
        # Ensure the assignment is visible (setChecked emits -> triggers redraw).
        if not self.display_controls.label_peaks.isChecked():
            self.display_controls.label_peaks.setChecked(True)
        else:
            self._redraw_single()
        self._redraw_citations()

    def _clear_override(self, peak) -> None:
        self._snapshot()
        self._peak_overrides[round(peak.two_theta, 1)] = None
        self._redraw_single()
        self._redraw_citations()

    def _redraw_waterfall(self) -> None:
        patterns = self.pattern_panel.checked_patterns()
        fig = self.waterfall_plot.figure
        fig.clear()
        if not patterns:
            self.waterfall_plot.refresh()
            return
        ax = fig.add_subplot(111)
        side = self.waterfall_controls.label_side.currentText()
        label_peaks = self.display_controls.label_peaks.isChecked()

        # Per-curve labels: auto phase/hkl (if enabled) plus that pattern's manual
        # peaks — so manually-added peaks show on the waterfall too.
        # Where a guide line already names a reflection, don't also label that peak
        # on every curve — the stacked duplicates collide with the guide names.
        guide_xs = [g["x"] for g in self._wf_guides] \
            if self.waterfall_controls.show_guides.isChecked() else []
        peak_labels = []
        for p in patterns:
            entries = self._labels_for_curve(p) if label_peaks else []
            if guide_xs:
                entries = [e for e in entries
                           if min(abs(e[0] - gx) for gx in guide_xs) > 0.6]
            key = self._pattern_key(p)
            entries += [(m["x"], subscriptify(m["text"])) for m in self._manual_labels
                        if m.get("pattern") in (None, key)]
            peak_labels.append(entries)

        plot_waterfall(
            [self._processed_pattern(p) for p in patterns],
            ax=ax,
            gap=self.waterfall_controls.gap.value(),
            normalize_each=self.waterfall_controls.normalize.isChecked(),
            label_side=side,
            yscale=self.waterfall_controls.y_scale.currentText(),
            peak_labels=peak_labels,
        )
        axes_set = {hrxrd.axis_of(p) for p in patterns}
        if len(axes_set) == 1 and "2Theta" not in axes_set:
            ax.set_xlabel(hrxrd.axis_label(axes_set.pop()))
        custom = self.title_edit.text().strip()
        if custom:
            ax.set_title(custom, pad=12, loc="center")
            lo, hi = ax.get_ylim()  # headroom so curve labels clear the title
            ax.set_ylim(lo, hi * (8.0 if ax.get_yscale() == "log" else 1.4))
        self._draw_guides(ax)
        fig.tight_layout()
        self._reserve_guide_margin(fig)
        self.waterfall_plot.refresh()

    def _reserve_guide_margin(self, fig) -> None:
        """Shrink the axes so guide labels (names above, angles below) aren't clipped."""
        arts = self._wf_guide_artists
        if not arts:
            return
        ax = fig.axes[0]
        try:
            fig.canvas.draw()  # realise renderer so extents are known
            r = fig.canvas.get_renderer()
            h = fig.bbox.height
            top_frac = max(a.get_window_extent(r).y1 / h for _l, a, _b in arts)
            bot_items = [b.get_window_extent(r).y0 / h for _l, _a, b in arts]
            bot_items.append(ax.xaxis.label.get_window_extent(r).y0 / h)
            bot_frac = min(bot_items)
        except Exception:  # noqa: BLE001
            return
        top = fig.subplotpars.top
        bottom = fig.subplotpars.bottom
        changed = False
        over = top_frac - top
        if over > 0:
            new_top = 0.97 - over
            if new_top < top:
                fig.subplots_adjust(top=max(0.45, new_top))
                changed = True
        depth = bottom - bot_frac  # how far the lowest element sits below the spine
        new_bottom = 0.03 + depth
        if new_bottom > bottom:
            fig.subplots_adjust(bottom=min(0.45, new_bottom))
            changed = True
        if changed:
            fig.canvas.draw_idle()

    # -- waterfall guide lines ----------------------------------------------
    def _draw_guides(self, ax) -> None:
        self._wf_guide_artists = []
        if not self.waterfall_controls.show_guides.isChecked() or not self._wf_guides:
            return
        # Show EVERY label: cluster guides that are too close and spread their
        # labels side-by-side (lower angle → left, higher angle → right) instead of
        # dropping any. Name goes above the graph, 2θ at the bottom of the line.
        # Push labels apart so none overlap: guarantee a minimum pixel gap between
        # consecutive labels (sorted by angle), keeping each near its line. Labels
        # that get shifted keep a thin leader line back to their guide line.
        dpi = ax.figure.dpi
        pt_per_px = 72.0 / dpi
        min_sep = 10.0 / pt_per_px  # ~10 pt, in pixels
        order = sorted(range(len(self._wf_guides)), key=lambda i: self._wf_guides[i]["x"])
        px = {i: ax.transData.transform((self._wf_guides[i]["x"], 0))[0] for i in order}
        # left-to-right pass: push right if too close to the previous label
        targ = {}
        prev = -1e18
        for i in order:
            t = max(px[i], prev + min_sep)
            targ[i] = t
            prev = t
        xoff = {i: (targ[i] - px[i]) * pt_per_px for i in order}  # offset in points

        for i, g in enumerate(self._wf_guides):
            color = g.get("color", "#555555")
            line = ax.axvline(g["x"], ls=":", lw=1.1, color=color, zorder=8)
            text = subscriptify(g["name"]) if g["name"] else f"{g['x']:.2f}°"
            leader = dict(arrowstyle="-", lw=0.4, color=color, shrinkA=0, shrinkB=0)
            name_ann = ax.annotate(  # above the graph
                text, xy=(g["x"], 1.0), xycoords=("data", "axes fraction"),
                xytext=(xoff[i], 6), textcoords="offset points", fontsize=7,
                color=color, ha="center", va="bottom", rotation=90,
                annotation_clip=False, arrowprops=leader,
            )
            # 2θ under the axis, below the tick numbers so it never overlaps them.
            angle_ann = ax.annotate(
                f"{g['x']:.2f}°", xy=(g["x"], 0.0), xycoords=("data", "axes fraction"),
                xytext=(xoff[i], -17), textcoords="offset points", fontsize=6,
                color=color, ha="center", va="top", rotation=90, annotation_clip=False,
            )
            self._wf_guide_artists.append((line, name_ann, angle_ann))
        ax.xaxis.labelpad = 48  # push "2θ (degrees)" below the under-axis angle labels

    def _wf_add_guide(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        axes = self.waterfall_plot.figure.axes
        lo, hi = axes[0].get_xlim() if axes else (10.0, 120.0)
        gx, ok = QInputDialog.getDouble(
            self, "Add guide line", "2θ position (°):", (lo + hi) / 2.0, lo, hi, 2
        )
        if not ok:
            return
        name, ok2 = QInputDialog.getText(
            self, "Add guide line",
            "Name (optional — use _ for subscripts, e.g. Al_2O_3):",
        )
        if not ok2:
            return
        self._snapshot()
        self._wf_guides.append({"x": float(gx), "name": name.strip()})
        self.tabs.setCurrentWidget(self.waterfall_plot)
        self._redraw_waterfall()

    def _prompt_guides_from_material(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        formulas = self._phase_db.formulas()
        # Offer overlaid references first, then everything in the database.
        overlaid = [r.formula for r in self._references if r.formula]
        choices = list(dict.fromkeys(overlaid + formulas))
        if not choices:
            QMessageBox.information(
                self, "Guides from material",
                "No materials yet — add one under Settings ▸ Phase database, or "
                "overlay a Materials Project reference.",
            )
            return
        shown = {g.get("material") for g in self._wf_guides if g.get("material")}
        labelled = [f"{c}   ✓ shown (toggle off)" if c in shown else c for c in choices]
        item, ok = QInputDialog.getItem(
            self, "Guides from material",
            "Material — expected reflections become guide lines (select again to toggle off):",
            labelled, 0, False,
        )
        if ok and item:
            self._guides_from_material(item.split("   ✓")[0].strip())

    @staticmethod
    def _parse_hkl(s):
        """Parse a stored hkl string (compact/spaced, overbar or minus) to ints."""
        if not isinstance(s, str):
            try:
                return tuple(int(round(float(v))) for v in s)
            except Exception:  # noqa: BLE001
                return None
        toks = s.split() if " " in s else list(s)
        out = []
        for t in toks:
            t = t.strip()
            if not t:
                continue
            neg = ("̅" in t) or t.startswith("-")
            digits = t.replace("̅", "").lstrip("-")
            if not digits.isdigit():
                return None
            out.append(-int(digits) if neg else int(digits))
        return tuple(out) if out else None

    @staticmethod
    def _reduce_dir(v):
        from functools import reduce as freduce
        from math import gcd

        nz = [abs(c) for c in v if c != 0]
        g = freduce(gcd, nz) if nz else 0
        v = tuple(c // g for c in v) if g > 0 else tuple(v)
        for c in v:  # canonical sign: first nonzero component positive
            if c > 0:
                return v
            if c < 0:
                return tuple(-x for x in v)
        return v

    def _same_family(self, hkl, base) -> bool:
        return hkl is not None and base is not None and \
            self._reduce_dir(hkl) == self._reduce_dir(base)

    def _detect_orientation(self, parsed, tol_deg: float = 0.5):
        """Assume the growth direction from what the scan actually shows.

        Each reflection family scores one point per order that coincides with a
        measured peak (plus a small log-intensity tie-break), so the family whose
        harmonics are present wins — e.g. ScN (111)+(222) on sapphire, even though the
        strongest peak in the scan belongs to the substrate. ``tol_deg`` allows for
        strain shifts. Falls back to the material's strongest reflection.
        """
        pattern = self.pattern_panel.current_pattern()
        if pattern is not None:
            peaks = ProminencePeakLabeler(min_prominence_frac=0.002).label(pattern)
            if peaks:
                tts = np.array([p.two_theta for p in peaks])
                ints = np.array([p.intensity for p in peaks])
                scores: dict = {}
                for hkl, r in parsed:
                    j = int(np.argmin(np.abs(tts - r[2])))
                    if abs(tts[j] - r[2]) <= tol_deg:
                        d = self._reduce_dir(hkl)
                        scores[d] = scores.get(d, 0.0) + 1.0 + np.log10(max(ints[j], 1.0)) / 10.0
                if scores:
                    return max(scores, key=scores.get)
        return self._reduce_dir(max(parsed, key=lambda pr: pr[1][3])[0])

    def _material_color(self, formula: str) -> str:
        """One colour per material across views: its overlay colour if it's overlaid
        (Single-view tick row), otherwise a stable colour from its database index."""
        overlaid = [r.formula for r in self._references]
        if formula in overlaid:
            return _REF_COLORS[overlaid.index(formula) % len(_REF_COLORS)]
        formulas = self._phase_db.formulas()
        if formula in formulas:
            return _REF_COLORS[formulas.index(formula) % len(_REF_COLORS)]
        return "#d62728"

    def _pick_orientation(self, formula, rows, min_intensity=5.0):
        """Ask which reflection family (film growth direction) to show.

        Returns the chosen family's rows (full harmonic ladder), or the powder set
        above ``min_intensity``, or None if cancelled. Auto-selects the assumed
        growth direction; the user can override it.
        """
        from PySide6.QtWidgets import QInputDialog

        powder_rows = [r for r in rows if r[3] >= min_intensity]
        parsed = [(self._parse_hkl(r[0]), r) for r in rows]
        parsed = [(p, r) for p, r in parsed if p]
        if len(parsed) < 2:  # nothing to disambiguate
            return powder_rows or rows

        # Group into families (unique reduced directions), keep the strongest
        # representative of each for display/ordering.
        fams: dict = {}     # direction -> strongest member (for ordering)
        lowest: dict = {}   # direction -> lowest-order member (for the label)
        for p, r in parsed:
            d = self._reduce_dir(p)
            if d not in fams or r[3] > fams[d][1][3]:
                fams[d] = (p, r)
            if d not in lowest or r[2] < lowest[d][1][2]:
                lowest[d] = (p, r)
        fam_list = sorted(fams.items(), key=lambda kv: -kv[1][1][3])  # strong first
        # Name each family by its lowest order (0006, not 0 0 0 12), as usually written.
        fam_list = [(d, lowest[d]) for d, _ in fam_list]

        auto = self._detect_orientation(parsed)
        # Put the assumed direction first so it is the default selection.
        fam_list.sort(key=lambda kv: kv[0] != auto)

        POWDER = "— all reflections (powder / unoriented) —"
        items = []
        for d, (p, r) in fam_list:
            tag = "   ← assumed" if d == auto else ""
            items.append(f"{hkl_display(r[0])} family  (e.g. {r[2]:.2f}°){tag}")
        items.append(POWDER)

        choice, ok = QInputDialog.getItem(
            self, f"{formula}: film orientation",
            "Epitaxial θ–2θ shows only the family along the growth direction.\n"
            "Pick the growth orientation (or all reflections for a powder):",
            items, 0, False,
        )
        if not ok:
            return None
        if choice == POWDER:
            return powder_rows or rows
        base = fam_list[items.index(choice)][0]
        kept = [r for p, r in parsed if self._same_family(p, base)]
        return kept or powder_rows or rows

    def _guides_from_material(self, formula: str, min_intensity: float = 5.0,
                              max_lines: int = 12) -> None:
        # Toggle: if this material's guides are already shown, remove them.
        self._snapshot()
        if any(g.get("material") == formula for g in self._wf_guides):
            self._wf_guides = [g for g in self._wf_guides if g.get("material") != formula]
            self.tabs.setCurrentWidget(self.waterfall_plot)
            self._redraw_waterfall()
            self.statusBar().showMessage(f"Removed expected guide lines for {formula}.", 4000)
            return

        pattern = self.pattern_panel.current_pattern()
        wl = float(pattern.wavelength) if pattern else 1.5405980
        lo, hi = pattern.two_theta_range if pattern else (0.0, 180.0)

        rows = self._phase_db.reflection_table(formula, wl)  # (hkl, d, 2θ, I)
        rows = [r for r in rows if lo <= r[2] <= hi]  # range only (floor applied below)
        if not rows:
            self.statusBar().showMessage(
                f"No reflections for {formula} in the current 2θ range.", 4000
            )
            return

        # Epitaxial orientation filter: a θ–2θ scan of an oriented film shows only
        # the reflection family collinear with the growth direction (e.g. (000ℓ)
        # for c-oriented hexagonal, (nnn) for (111) rock-salt), not the full powder
        # set. Assume the growth direction (from the data / strongest line) but let
        # the user pick a different family — or the full powder pattern. For a chosen
        # family the weak higher-order harmonics are kept (they show for a film even
        # though their powder intensity is tiny); powder mode uses the intensity floor.
        rows = self._pick_orientation(formula, rows, min_intensity)
        if rows is None:  # user cancelled
            return
        rows.sort(key=lambda r: -r[3])  # strongest first
        rows = rows[:max_lines]

        color = self._material_color(formula)
        for hkl, _d, tt, I in rows:
            name = f"{subscript_digits(formula)} {hkl_display(hkl)}"
            self._wf_guides.append(
                {"x": float(tt), "name": name, "color": color,
                 "material": formula, "intensity": float(I)}
            )

        self.waterfall_controls.show_guides.setChecked(True)
        self.tabs.setCurrentWidget(self.waterfall_plot)
        self._redraw_waterfall()
        self.statusBar().showMessage(
            f"Added {len(rows)} expected guide lines for {formula}.", 5000
        )

    def _set_guide_position(self, i: int) -> None:
        from PySide6.QtWidgets import QInputDialog

        if not (0 <= i < len(self._wf_guides)):
            return
        axes = self.waterfall_plot.figure.axes
        lo, hi = axes[0].get_xlim() if axes else (10.0, 120.0)
        gx, ok = QInputDialog.getDouble(
            self, "Guide line position", "2θ (°):", self._wf_guides[i]["x"], lo, hi, 2
        )
        if ok:
            self._wf_guides[i]["x"] = float(gx)
            self._redraw_waterfall()

    def _nearest_guide(self, ax, event) -> int | None:
        """Index of the guide line nearest the cursor within ~6 px, else None."""
        if event.x is None or not self._wf_guides:
            return None
        best, best_d = None, 6.0
        for i, g in enumerate(self._wf_guides):
            px = ax.transData.transform((g["x"], 0))[0]
            if abs(px - event.x) < best_d:
                best_d, best = abs(px - event.x), i
        return best

    def _wf_on_press(self, event) -> None:
        ax = event.inaxes
        if ax is None:
            return
        if event.button == 3:  # right-click: manage guides
            self._wf_guide_menu(event)
            return
        if event.button != 1:
            return
        if str(getattr(self.waterfall_plot.toolbar, "mode", "")):
            return  # a nav tool is active — let it handle the drag
        self._wf_drag = self._nearest_guide(ax, event)

    def _wf_on_motion(self, event) -> None:
        if self._wf_drag is None or event.inaxes is None or event.xdata is None:
            return
        x = float(event.xdata)
        g = self._wf_guides[self._wf_drag]
        g["x"] = x
        line, name_ann, angle_ann = self._wf_guide_artists[self._wf_drag]
        line.set_xdata([x, x])
        name_ann.xy = (x, 1.0)
        name_ann.set_text(subscriptify(g["name"]) if g["name"] else f"{x:.2f}°")
        angle_ann.xy = (x, 0.0)
        angle_ann.set_text(f"{x:.2f}°")
        self.waterfall_plot.canvas.draw_idle()

    def _wf_on_release(self, event) -> None:
        was_dragging = self._wf_drag is not None
        self._wf_drag = None
        if was_dragging:  # re-optimise which labels are shown for the new position
            self._redraw_waterfall()

    def _wf_guide_menu(self, event) -> None:
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QInputDialog, QMenu

        ax = event.inaxes
        menu = QMenu(self)
        idx = self._nearest_guide(ax, event)
        add = menu.addAction(f"Add guide line at {event.xdata:.2f}°")
        add.triggered.connect(
            lambda _=False, xx=float(event.xdata): (
                self._wf_guides.append({"x": xx, "name": ""}), self._redraw_waterfall()
            )
        )
        if idx is not None:
            rename = menu.addAction("Name this guide line…")

            def _rename(_=False, i=idx):
                text, ok = QInputDialog.getText(
                    self, "Guide line", "Name:", text=self._wf_guides[i]["name"]
                )
                if ok:
                    self._wf_guides[i]["name"] = text.strip()
                    self._redraw_waterfall()

            rename.triggered.connect(_rename)
            setpos = menu.addAction("Set position (2θ)…")
            setpos.triggered.connect(lambda _=False, i=idx: self._set_guide_position(i))
            rem = menu.addAction("Remove this guide line")
            rem.triggered.connect(
                lambda _=False, i=idx: (self._wf_guides.pop(i), self._redraw_waterfall())
            )
        if self._wf_guides:
            menu.addAction("Clear all guide lines").triggered.connect(
                lambda: (self._wf_guides.clear(), self._redraw_waterfall())
            )
        if not menu.isEmpty():
            menu.exec(QCursor.pos())

    def _redraw_citations(self) -> None:
        from xrdlab.citations import build_bibtex, build_report_html

        pattern = self.pattern_panel.current_pattern()
        if pattern is None:
            self.citations_view.set_html(
                "<p style='font-family:sans-serif;color:#888'>"
                "Load a pattern to see per-peak citations.</p>"
            )
            self._current_bibtex = ""
            return
        peaks = self._detect_and_identify(pattern, use_db=True)  # always identify here
        self.citations_view.set_html(
            build_report_html(pattern.name, float(pattern.wavelength), peaks, self._phase_db)
        )
        self._current_bibtex = build_bibtex(peaks, self._phase_db)

    def _export_citations(self) -> None:
        if not self._current_bibtex:
            QMessageBox.information(
                self, "Citations", "No identified phases to export yet."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export citations", "references.bib", "BibTeX (*.bib);;All files (*)"
        )
        if not path:
            return
        Path(path).write_text(self._current_bibtex, encoding="utf-8")
        self.statusBar().showMessage(f"Exported {Path(path).name}", 4000)

    def _redraw_rietveld(self) -> None:
        fig = self.rietveld_plot.figure
        fig.clear()
        if self._rietveld is None:
            self.rietveld_plot.refresh()
            return
        custom = self.title_edit.text().strip()
        plot_rietveld(self._rietveld, fig=fig, title=custom or self._rietveld.name or None)
        self.rietveld_plot.refresh()

    # -- Materials Project overlay ------------------------------------------
    def _on_overlay(self, formula: str, wavelength: str) -> None:
        formulas = [f.strip() for f in formula.split(",") if f.strip()]
        if not formulas:
            self.mp_panel.set_status("Enter a formula first.")
            return
        self.mp_panel.set_status(f"Querying Materials Project for {', '.join(formulas)}…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        references, notes, failures = [], [], []

        # Match the reference to the measured pattern: use its wavelength and 2θ
        # window so the sticks line up and the range isn't over-populated. The
        # "Match sample wavelength" checkbox controls the wavelength; the 2θ range
        # is always clipped to a loaded scan. No scan -> use the dropdown.
        pattern = self.pattern_panel.current_pattern()
        match_wl = self.mp_panel.match_wavelength.isChecked()
        if pattern is not None:
            sim_range = pattern.two_theta_range
            sim_wavelength: str | float = float(pattern.wavelength) if match_wl else wavelength
        else:
            sim_wavelength = wavelength
            sim_range = (10.0, 120.0)

        try:
            from xrdlab.mp.client import MPClient

            client = MPClient()
            for f in formulas:
                try:
                    ref = client.formula_to_reference(
                        f, wavelength=sim_wavelength, two_theta_range=sim_range
                    )
                    references.append(ref)
                    notes.append(f"{f}: {len(ref.two_theta)} refl ({ref.material_id})")
                except Exception as exc:  # noqa: BLE001 — per-phase failure
                    failures.append(f"{f}: {exc}")
        except ModuleNotFoundError as exc:
            self.mp_panel.set_status(
                f"{exc}. The Materials Project features need the optional stack — "
                "install it with:  pip install -e .[mp]"
            )
            QApplication.restoreOverrideCursor()
            return
        except Exception as exc:  # noqa: BLE001 — e.g. missing API key
            self.mp_panel.set_status(f"Failed: {exc}")
            QApplication.restoreOverrideCursor()
            return
        finally:
            QApplication.restoreOverrideCursor()

        self._references = references
        # Grow the phase database (with provenance + Crossref formatting) so these
        # phases can identify and cite peaks in any dataset.
        from xrdlab import config
        from xrdlab.citations import enrich_citation

        mailto = config.get_crossref_mailto()
        for ref in references:
            try:
                citation = enrich_citation(client.get_provenance(ref.material_id), mailto)
            except Exception:  # noqa: BLE001
                citation = None
            self._phase_db.add_reference(ref, citation=citation)
        self.mp_panel.set_status("  |  ".join(notes + failures) or "No matches.")
        self.tabs.setCurrentWidget(self.single_plot)
        self._redraw_single()
        self._redraw_citations()

    def _on_clear_overlay(self) -> None:
        self._references = []
        self.mp_panel.set_status("")
        self._redraw_single()
        self._redraw_citations()

    # -- export --------------------------------------------------------------
    def _export_current(self) -> None:
        widget = self.tabs.currentWidget()
        exts = " ".join(f"*.{f}" for f in EXPORT_FORMATS)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export figure", "figure.pdf", f"Vector/raster ({exts})"
        )
        if not path:
            return
        try:
            save_figure(widget.figure, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage(f"Exported {Path(path).name}", 4000)
