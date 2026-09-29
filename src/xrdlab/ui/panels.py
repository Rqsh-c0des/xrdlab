"""Side-panel controls: pattern list, waterfall options, and MP reference search."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xrdlab import config
from xrdlab.core.pattern import Pattern
from xrdlab.mp.simulate import RADIATION

__all__ = [
    "PatternListPanel",
    "WaterfallControls",
    "MPSearchPanel",
    "PeakDisplayControls",
    "ProcessingControls",
]


class ProcessingControls(QGroupBox):
    """Non-destructive display/analysis transforms (never baked into export data).

    Surfaces the processing helpers so peaks are detected, drawn and measured on a
    cleaner signal when wanted. All toggles are off by default.
    """

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Processing (non-destructive)", parent)
        self.strip_ka2 = QCheckBox("Strip Kα2")
        self.strip_ka2.setToolTip(
            "Rachinger removal of the Kα2 satellite (assumes the source doublet)."
        )
        self.subtract_bg = QCheckBox("Subtract background (auto)")
        self.subtract_bg.setToolTip(
            "Estimate and remove a smooth background (asymmetric least squares)."
        )
        self.smooth = QCheckBox("Smooth (Savitzky–Golay)")
        self.smooth.setToolTip("Light smoothing for display / peak finding only.")
        for cb in (self.strip_ka2, self.subtract_bg, self.smooth):
            cb.stateChanged.connect(lambda _: self.changed.emit())

        layout = QVBoxLayout(self)
        layout.addWidget(self.strip_ka2)
        layout.addWidget(self.subtract_bg)
        layout.addWidget(self.smooth)


class PatternListPanel(QGroupBox):
    """A checkable, reorderable list of loaded patterns.

    Checked items (in list order) drive the waterfall; the current row drives the
    single-pattern view.
    """

    changed = Signal()
    selection_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Patterns", parent)
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.itemChanged.connect(lambda _: self.changed.emit())
        self._list.currentRowChanged.connect(lambda _: self.selection_changed.emit())
        self._list.model().rowsMoved.connect(lambda *_: self.changed.emit())
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)

        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self._remove_current)

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addWidget(remove_btn)

    def add_pattern(self, pattern: Pattern) -> None:
        item = QListWidgetItem(pattern.name or f"Pattern {self._list.count() + 1}")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        item.setData(Qt.ItemDataRole.UserRole, pattern)
        item.setToolTip(pattern.meta.get("source_stem", pattern.name))
        self._list.addItem(item)
        self._list.setCurrentItem(item)
        self.changed.emit()

    def _context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        rename = menu.addAction("Rename…")
        rename.triggered.connect(lambda: self._rename(item))
        menu.exec(self._list.mapToGlobal(pos))

    def _rename(self, item) -> None:
        pattern = item.data(Qt.ItemDataRole.UserRole)
        text, ok = QInputDialog.getText(
            self, "Rename pattern", "Name (used as the title / waterfall label):",
            text=pattern.name,
        )
        if ok and text.strip():
            pattern.name = text.strip()
            item.setText(pattern.name)
            self.selection_changed.emit()  # refresh single-view title
            self.changed.emit()             # refresh waterfall labels

    def relabel(self, label_fn) -> None:
        """Re-derive every pattern's display label with ``label_fn(stem)``."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            pattern = item.data(Qt.ItemDataRole.UserRole)
            stem = pattern.meta.get("source_stem", pattern.name)
            pattern.name = label_fn(stem)
            item.setText(pattern.name)
        self.changed.emit()

    def _remove_current(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self._list.takeItem(row)
            self.changed.emit()

    def clear(self) -> None:
        self._list.clear()
        self.changed.emit()

    def patterns_with_state(self) -> list[tuple[Pattern, bool]]:
        """Every pattern in list order, paired with its checked state."""
        out = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            checked = item.checkState() == Qt.CheckState.Checked
            out.append((item.data(Qt.ItemDataRole.UserRole), checked))
        return out

    def add_pattern_state(self, pattern: Pattern, checked: bool) -> None:
        """Append a pattern with an explicit checked state (used when loading a project)."""
        self.add_pattern(pattern)
        item = self._list.item(self._list.count() - 1)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def checked_patterns(self) -> list[Pattern]:
        out = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def current_pattern(self) -> Pattern | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None


class WaterfallControls(QGroupBox):
    """Offset / normalization controls for the waterfall view."""

    changed = Signal()
    add_guide_requested = Signal()
    guides_from_material_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Waterfall", parent)
        self.gap = QDoubleSpinBox()
        self.gap.setRange(0.0, 100.0)
        self.gap.setSingleStep(0.1)
        self.gap.setValue(1.0)
        self.gap.valueChanged.connect(lambda _: self.changed.emit())

        self.normalize = QCheckBox("Normalize each curve")
        self.normalize.setChecked(True)
        self.normalize.stateChanged.connect(lambda _: self.changed.emit())

        self.y_scale = QComboBox()
        self.y_scale.addItems(["log", "linear"])  # log default
        self.y_scale.currentTextChanged.connect(lambda _: self.changed.emit())

        self.label_side = QComboBox()
        self.label_side.addItems(["right", "left", "none"])
        self.label_side.currentTextChanged.connect(lambda _: self.changed.emit())

        self.show_guides = QCheckBox("Show guide lines")
        self.show_guides.setChecked(True)
        self.show_guides.setToolTip("Toggle the vertical comparison guide lines (independent of peak labels).")
        self.show_guides.stateChanged.connect(lambda _: self.changed.emit())

        self.add_guide_btn = QPushButton("Add guide line")
        self.add_guide_btn.setToolTip(
            "Add a draggable vertical dotted line to compare peaks at the same 2θ "
            "across the stacked patterns. Drag it (no tool active); right-click to name/remove."
        )
        self.add_guide_btn.clicked.connect(lambda: self.add_guide_requested.emit())

        self.guides_material_btn = QPushButton("Guides from material…")
        self.guides_material_btn.setToolTip(
            "Drop guide lines at the expected reflection positions of a database "
            "material, labelled with its (hkl)."
        )
        self.guides_material_btn.clicked.connect(lambda: self.guides_from_material_requested.emit())

        form = QFormLayout(self)
        form.addRow("Offset gap", self.gap)
        form.addRow(self.normalize)
        form.addRow("Y scale", self.y_scale)
        form.addRow("Labels", self.label_side)
        form.addRow(self.show_guides)
        form.addRow(self.add_guide_btn)
        form.addRow(self.guides_material_btn)


class PeakDisplayControls(QGroupBox):
    """Y-axis scaling and automatic peak-labelling controls (Single view)."""

    changed = Signal()
    add_peak_requested = Signal()
    peak_table_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Peaks & display", parent)

        self.y_scale = QComboBox()
        self.y_scale.addItems(["log", "sqrt", "linear"])  # log default
        self.y_scale.currentTextChanged.connect(lambda _: self.changed.emit())

        self.label_peaks = QCheckBox("Label peaks")
        self.label_peaks.stateChanged.connect(lambda _: self.changed.emit())

        self.sensitivity = QDoubleSpinBox()
        self.sensitivity.setRange(0.1, 50.0)
        self.sensitivity.setSingleStep(0.5)
        self.sensitivity.setValue(2.0)
        self.sensitivity.setSuffix(" %")
        self.sensitivity.setToolTip("Minimum peak prominence, as a % of the data range.")
        self.sensitivity.valueChanged.connect(lambda _: self.changed.emit())

        self.label_mode = QComboBox()
        self.label_mode.addItems(["Assigned only", "All peaks"])
        self.label_mode.currentTextChanged.connect(lambda _: self.changed.emit())

        self.identify_db = QCheckBox("Identify from phase database")
        self.identify_db.setToolTip(
            "Match unlabelled peaks against the local phase database "
            "(Settings ▸ Phase database…)."
        )
        self.identify_db.stateChanged.connect(lambda _: self.changed.emit())

        self.tolerance = QDoubleSpinBox()
        self.tolerance.setRange(0.05, 5.0)
        self.tolerance.setSingleStep(0.05)
        self.tolerance.setValue(0.5)
        self.tolerance.setSuffix(" °")
        self.tolerance.setToolTip("Max 2θ distance to assign a peak to a reference reflection.")
        self.tolerance.valueChanged.connect(lambda _: self.changed.emit())

        self.show_fwhm = QCheckBox("Show FWHM on labels")
        self.show_fwhm.setToolTip(
            "Append each labelled peak's full width at half maximum (°2θ), measured "
            "from the data. Full widths + crystallite sizes are in Peak table…."
        )
        self.show_fwhm.stateChanged.connect(lambda _: self.changed.emit())

        self.add_peak_btn = QPushButton("Add peak…")
        self.add_peak_btn.setToolTip(
            "Manually mark a peak the auto-detector missed (or one with no database "
            "match) and give it a label. You can also right-click the plot."
        )
        self.add_peak_btn.clicked.connect(lambda: self.add_peak_requested.emit())

        self.peak_table_btn = QPushButton("Peak table…")
        self.peak_table_btn.setToolTip(
            "List every detected peak with 2θ, d-spacing, intensity, FWHM and "
            "Scherrer crystallite size; export to CSV."
        )
        self.peak_table_btn.clicked.connect(lambda: self.peak_table_requested.emit())

        form = QFormLayout(self)
        form.addRow("Y scale", self.y_scale)
        form.addRow(self.label_peaks)
        form.addRow("Sensitivity", self.sensitivity)
        form.addRow("Label mode", self.label_mode)
        form.addRow(self.identify_db)
        form.addRow("Match tol.", self.tolerance)
        form.addRow(self.show_fwhm)
        form.addRow(self.add_peak_btn)
        form.addRow(self.peak_table_btn)


class MPSearchPanel(QGroupBox):
    """Formula search box that requests a Materials Project reference overlay."""

    overlay_requested = Signal(str, str)  # formula, wavelength
    clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Materials Project reference", parent)
        self.formula = QLineEdit()
        self.formula.setPlaceholderText("e.g. ScN  (or several: ScN, GaN, Al2O3)")
        self.formula.setToolTip(
            "One or more sample phases, comma-separated. Each is overlaid and "
            "used to assign peaks."
        )

        self.wavelength = QComboBox()
        self.wavelength.addItems(list(RADIATION))
        self.wavelength.setCurrentText("CuKa1")

        self.match_wavelength = QCheckBox("Match sample wavelength")
        self.match_wavelength.setChecked(True)
        self.match_wavelength.setToolTip(
            "Simulate the reference at the loaded scan's measured wavelength "
            "(recommended). Uncheck to use the Radiation choice above."
        )

        overlay_btn = QPushButton("Overlay reference")
        overlay_btn.clicked.connect(
            lambda: self.overlay_requested.emit(
                self.formula.text().strip(), self.wavelength.currentText()
            )
        )
        clear_btn = QPushButton("Clear overlay")
        clear_btn.clicked.connect(lambda: self.clear_requested.emit())

        # --- API key management ---
        self.key_status = QLabel()
        self.key_status.setWordWrap(True)
        key_btn = QPushButton("Set API key…")
        key_btn.clicked.connect(self.prompt_api_key)

        self.status = QLabel("")
        self.status.setWordWrap(True)

        form = QFormLayout(self)
        form.addRow("Formula", self.formula)
        form.addRow("Radiation", self.wavelength)
        form.addRow(self.match_wavelength)
        form.addRow(overlay_btn)
        form.addRow(clear_btn)
        form.addRow(QLabel("API key"), self.key_status)
        form.addRow(key_btn)
        form.addRow(self.status)

        self._refresh_key_status()

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def _refresh_key_status(self) -> None:
        key = config.resolve_api_key()
        source = ""
        if key and not config.get_saved_api_key():
            source = "  (from environment)"
        self.key_status.setText(config.mask_key(key) + source)

    def prompt_api_key(self) -> None:
        """Prompt for a Materials Project API key and save it persistently."""
        current = config.get_saved_api_key()
        text, ok = QInputDialog.getText(
            self,
            "Materials Project API key",
            "Enter your MP API key (leave blank to clear the saved key):",
            QLineEdit.EchoMode.Password,
            current,
        )
        if not ok:
            return
        config.set_api_key(text)
        self._refresh_key_status()
        self.set_status(
            "API key saved." if text.strip() else "Saved API key cleared."
        )
