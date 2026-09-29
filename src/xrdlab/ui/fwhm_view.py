"""FWHM comparison across samples (e.g. a growth-temperature series).

A table — one row per checked pattern, one column per reflection — of the chosen
metric (Kα1 FWHM from a doublet-aware pseudo-Voigt fit by default), with a trend
plot underneath (against temperature when every sample name carries one) and CSV
export of every measured quantity.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xrdlab.ui.widgets import MplCanvas

__all__ = ["FwhmCompareView", "METRICS"]

# label -> (record field, multiplier, decimals)
METRICS = {
    "FWHM — fit, Kα1 (°)": ("fwhm_fit", 1.0, 4),
    "FWHM — fit, Kα1 (arcsec)": ("fwhm_fit", 3600.0, 0),
    "FWHM — data (°)": ("fwhm_data", 1.0, 4),
    "Peak position 2θ (°)": ("two_theta", 1.0, 3),
    "Crystallite size (nm)": ("size_nm", 1.0, 1),
    "Intensity (counts)": ("intensity", 1.0, 0),
}
_CSV_FIELDS = ["sample", "temperature_C", "reflection", "two_theta", "intensity",
               "fwhm_data", "fwhm_fit", "fwhm_fit_arcsec", "eta", "r_squared",
               "size_nm", "fit_model"]


class FwhmCompareView(QWidget):
    """Tab widget: per-sample × per-reflection peak-width comparison."""

    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._records: list[dict] = []
        self._samples: list[tuple[str, float | None]] = []

        self.metric = QComboBox()
        self.metric.addItems(list(METRICS))
        self.metric.currentTextChanged.connect(lambda _: self._render())
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Re-measure (uses the checked patterns and Peaks settings).")
        refresh.clicked.connect(lambda: self.refresh_requested.emit())
        export = QPushButton("Export CSV…")
        export.clicked.connect(self._export_csv)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Show:"))
        bar.addWidget(self.metric, 1)
        bar.addWidget(refresh)
        bar.addWidget(export)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.canvas = MplCanvas(width=6.0, height=3.0)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.canvas)
        split.setSizes([260, 320])

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#666; font-size:11px;")

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(split, 1)
        layout.addWidget(self.note)

    # Ctrl+E ("Export current figure") exports the trend plot on this tab.
    @property
    def figure(self):
        return self.canvas.figure

    # -- data ------------------------------------------------------------------
    def set_data(self, samples, records, note: str = "") -> None:
        self._samples = list(samples)
        self._records = list(records)
        self.note.setText(note)
        self._render()

    def reflections(self) -> list[str]:
        """Reflection columns, ordered by 2θ."""
        pos: dict[str, list[float]] = {}
        for r in self._records:
            pos.setdefault(r["reflection"], []).append(r["two_theta"])
        return sorted(pos, key=lambda k: float(np.mean(pos[k])))

    def value(self, sample: str, reflection: str, metric: str | None = None):
        field, mult, _ = METRICS[metric or self.metric.currentText()]
        for r in self._records:
            if r["sample"] == sample and r["reflection"] == reflection:
                v = r.get(field)
                return None if v is None or not np.isfinite(v) else v * mult
        return None

    # -- render ----------------------------------------------------------------
    def _render(self) -> None:
        metric = self.metric.currentText()
        _, _, dec = METRICS[metric]
        refl = self.reflections()
        names = [s for s, _ in self._samples]
        self.table.clear()
        self.table.setRowCount(len(names))
        self.table.setColumnCount(len(refl))
        self.table.setHorizontalHeaderLabels(refl)
        self.table.setVerticalHeaderLabels(names)
        for i, s in enumerate(names):
            for j, rf in enumerate(refl):
                v = self.value(s, rf, metric)
                item = QTableWidgetItem("—" if v is None else f"{v:.{dec}f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(i, j, item)
        self._plot(metric, refl)

    def _plot(self, metric: str, refl: list[str]) -> None:
        fig = self.canvas.figure
        fig.clear()
        if not self._samples or not refl:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, "No peaks to compare — check patterns and assign phases\n"
                    "(overlay a reference or enable 'Identify from phase database').",
                    ha="center", va="center", transform=ax.transAxes, fontsize=9)
            ax.set_axis_off()
            self.canvas.draw_idle()
            return
        ax = fig.add_subplot(111)
        temps = [t for _, t in self._samples]
        numeric = all(t is not None for t in temps) and len(set(temps)) == len(temps)
        xs = temps if numeric else list(range(len(self._samples)))
        for rf in refl:
            ys = [self.value(s, rf, metric) for s, _ in self._samples]
            pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
            if pts:
                ax.plot(*zip(*pts), "o-", ms=4, lw=1.2, label=rf)
        if numeric:
            ax.set_xlabel("Temperature (°C)")
        else:
            ax.set_xticks(xs)
            ax.set_xticklabels([s for s, _ in self._samples], rotation=20, ha="right",
                               fontsize=8)
        ax.set_ylabel(metric)
        ax.legend(fontsize=7, loc="best")
        fig.tight_layout()
        self.canvas.draw_idle()

    # -- export ----------------------------------------------------------------
    def _export_csv(self) -> None:
        if not self._records:
            QMessageBox.information(self, "Export CSV", "Nothing to export yet.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export FWHM table", "fwhm_comparison.csv", "CSV (*.csv);;All files (*)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        self.write_csv(path)

    def write_csv(self, path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            w.writeheader()
            order = {s: i for i, (s, _) in enumerate(self._samples)}
            for r in sorted(self._records, key=lambda r: (order.get(r["sample"], 0),
                                                         r["two_theta"])):
                row = {k: r.get(k) for k in _CSV_FIELDS}
                f = r.get("fwhm_fit")
                row["fwhm_fit_arcsec"] = None if f is None or not np.isfinite(f) else f * 3600
                w.writerow({k: ("" if v is None or (isinstance(v, float) and not np.isfinite(v))
                                else v) for k, v in row.items()})
        self.note.setText(f"Exported → {Path(path).name}")
