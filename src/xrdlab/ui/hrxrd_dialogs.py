"""HRXRD tools: rocking curves & mosaicity, RSM, thickness fringes, Williamson–Hall,
φ-scan symmetry. Thin Qt layers over :mod:`xrdlab.core.hrxrd`."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from xrdlab.core import hrxrd
from xrdlab.ui.widgets import MplCanvas, NavigationToolbar

__all__ = ["RockingCurvesDialog", "RSMDialog", "ThicknessDialog",
           "WilliamsonHallDialog", "PhiScanDialog", "parse_hkl_text", "rsm_from_csv"]

_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf",
           "#8c564b", "#e377c2"]


def parse_hkl_text(text: str):
    """'1 0 -1 5', '10-15', '(224)', '1,0,-1,2' → tuple of ints (or None)."""
    t = text.strip().strip("()[]{}").replace(",", " ")
    if " " in t:
        try:
            return tuple(int(v) for v in t.split())
        except ValueError:
            return None
    toks = re.findall(r"-?\d", t)
    return tuple(int(v) for v in toks) if toks else None


def _fmt(v, dec=1, sci=False):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    return f"{v:.2e}" if sci else f"{v:.{dec}f}"


def _item(text, editable=False):
    it = QTableWidgetItem(text)
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return it


def _save_figure(parent, fig, stem: str):
    from xrdlab.plotting.export import EXPORT_FORMATS, save_figure

    exts = " ".join(f"*.{f}" for f in EXPORT_FORMATS)
    path, _ = QFileDialog.getSaveFileName(parent, "Export figure", f"{stem}.pdf",
                                          f"Vector/raster ({exts})")
    if path:
        save_figure(fig, path)


def _material_combo(default: str | None = None) -> QComboBox:
    cb = QComboBox()
    cb.addItems(list(hrxrd.MATERIALS))
    if default and default in hrxrd.MATERIALS:
        cb.setCurrentText(default)
    return cb


def _close_bar(dialog, *buttons) -> QHBoxLayout:
    close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    close.rejected.connect(dialog.reject)
    bar = QHBoxLayout()
    for b in buttons:
        bar.addWidget(b)
    bar.addStretch(1)
    bar.addWidget(close)
    return bar


def _button(text, slot) -> QPushButton:
    b = QPushButton(text)
    b.clicked.connect(slot)
    return b


# =============================================================================
# Rocking curves, mosaicity & dislocation density
# =============================================================================

class RockingCurvesDialog(QDialog):
    """Compare rocking curves; FWHM, dislocation density, tilt/twist, WH-ω.

    One row per ω scan. Rows sharing a *Sample* value are analysed together:
    symmetric (χ≈0) + skew-symmetric (χ>0) rows → tilt & twist; several symmetric
    orders → Williamson–Hall-ω (tilt + lateral coherence length).
    """

    COLS = ["Sample", "Scan", "Reflection", "χ (°)", "2θ (°)", "ω peak (°)",
            "FWHM (″)", "Corrected (″)", "η", "ρ (cm⁻²)"]

    def __init__(self, patterns, parent=None, *, reflection_guess=None,
                 instrument_arcsec: float = 0.0, material: str = "GaN (wurtzite)"):
        super().__init__(parent)
        self.setWindowTitle("Rocking curves — FWHM, mosaicity & dislocations")
        self.resize(1100, 780)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self._patterns = list(patterns)
        self._guess = reflection_guess or (lambda p: "")
        self._rows: list[dict] = []
        self._busy = False

        self.material = _material_combo(material)
        self.profile = QComboBox()
        self.profile.addItems(["pseudo-Voigt", "Gaussian", "Lorentzian"])
        self.instr = QDoubleSpinBox()
        self.instr.setRange(0.0, 3600.0)
        self.instr.setDecimals(1)
        self.instr.setSuffix(" ″")
        self.instr.setValue(instrument_arcsec)
        self.instr.setToolTip("Instrumental ω resolution (e.g. a perfect-substrate RC); "
                              "subtracted in quadrature. 0 = none.")
        self.logy = QCheckBox("Log intensity")
        self.logy.setChecked(True)
        self.norm = QCheckBox("Normalize")
        self.norm.setChecked(True)
        self.material.currentTextChanged.connect(lambda _: self._refresh_derived())
        self.profile.currentTextChanged.connect(lambda _: self._recompute())
        self.instr.valueChanged.connect(lambda _: self._recompute())
        for w in (self.logy, self.norm):
            w.stateChanged.connect(lambda _: self._plot())
        self.bvec = QLabel()

        top = QHBoxLayout()
        for lbl, w in (("Material", self.material), ("Profile", self.profile),
                       ("Instrument", self.instr)):
            top.addWidget(QLabel(lbl))
            top.addWidget(w)
        top.addWidget(self.bvec, 1)
        top.addWidget(self.norm)
        top.addWidget(self.logy)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._on_edit)
        self.table.horizontalHeaderItem(0).setToolTip(
            "Editable. Rows with the same Sample are combined for tilt/twist and "
            "Williamson–Hall-ω.")
        self.table.horizontalHeaderItem(3).setToolTip(
            "Editable. Inclination of the reflecting planes to the surface: 0 for "
            "symmetric (e.g. 0002), ≈61.96° for GaN (101̄1) in skew-symmetric geometry. "
            "Pre-filled from the scan's χ position.")
        self.table.horizontalHeaderItem(9).setToolTip(
            "Dunn–Kogh ρ = β²/(4.35 b²): screw b for χ<5°, edge b otherwise.")

        self.canvas = MplCanvas(width=6.0, height=3.4)
        self.toolbar = NavigationToolbar(self.canvas, self)
        plot_box = QWidget()
        pl = QVBoxLayout(plot_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.toolbar)
        pl.addWidget(self.canvas)
        self.summary = QTextBrowser()
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(plot_box)
        split.addWidget(self.summary)
        split.setSizes([200, 360, 180])

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(split, 1)
        lay.addLayout(_close_bar(
            self, _button("Export CSV…", self._export_csv),
            _button("Export figure…",
                    lambda: _save_figure(self, self.canvas.figure, "rocking_curves"))))

        for p in self._patterns:
            fixed = p.meta.get("fixed_positions") or {}
            self._rows.append({"pattern": p, "sample": p.name, "reflection": self._guess(p),
                               "chi": float(fixed.get("Chi", 0.0) or 0.0),
                               "two_theta": hrxrd.fixed_two_theta(p)})
        self._recompute()

    def _b(self):
        return hrxrd.burgers_vectors(self.material.currentText())

    def _recompute(self):
        from xrdlab.core.fitting import doublet_kwargs

        instr_deg = self.instr.value() / 3600.0
        for r in self._rows:
            p = r["pattern"]
            r["m"] = hrxrd.rocking_curve_metrics(
                p.two_theta, p.intensity, fit_kwargs=doublet_kwargs(p),
                profile=self.profile.currentText(), instrument_fwhm_deg=instr_deg)
        self._refresh_derived()
        self._plot()

    def _refresh_derived(self):
        self._fill_table()
        self._summarize()

    def _fill_table(self):
        b = self._b()
        self.bvec.setText(f"b: screw {b['screw']:.3f} Å · edge {b['edge']:.3f} Å")
        self._busy = True
        self.table.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            m = r["m"]
            bb = b["screw"] if abs(r["chi"]) < 5 else b["edge"]
            vals = [
                _item(r["sample"], True), _item(r["pattern"].name),
                _item(r["reflection"], True), _item(_fmt(r["chi"], 2), True),
                _item(_fmt(r["two_theta"], 3)), _item(_fmt(m["peak"], 4)),
                _item(_fmt(m["fwhm_arcsec"], 1) + (" ᵈ" if m["doublet"] else "")),
                _item(_fmt(m["fwhm_corrected_arcsec"], 1)),
                _item(_fmt(m["eta"], 2)),
                _item(_fmt(hrxrd.dislocation_density(m["fwhm_corrected"], bb), sci=True)),
            ]
            for j, it in enumerate(vals):
                self.table.setItem(i, j, it)
        self._busy = False

    def _on_edit(self, item):
        if self._busy:
            return
        r = self._rows[item.row()]
        col = item.column()
        if col == 0:
            r["sample"] = item.text().strip()
        elif col == 2:
            r["reflection"] = item.text().strip()
        elif col == 3:
            try:
                r["chi"] = float(item.text())
            except ValueError:
                pass
        else:
            return
        self._refresh_derived()
        self._plot()

    def _plot(self):
        fig = self.canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        widths = [r["m"]["fwhm_arcsec"] for r in self._rows
                  if np.isfinite(r["m"]["fwhm_arcsec"])]
        for k, r in enumerate(self._rows):
            p, m = r["pattern"], r["m"]
            x = (p.two_theta - m["peak"]) * 3600.0
            y = np.asarray(p.intensity, dtype=float)
            if self.norm.isChecked():
                y = y / max(float(np.max(y)), 1.0)
            lab = f"{r['sample']} {r['reflection']}".strip() + \
                f" — {_fmt(m['fwhm_arcsec'], 0)}″"
            ax.plot(x, y, "-", lw=1.1, color=_COLORS[k % len(_COLORS)], label=lab)
        if self.logy.isChecked():
            ax.set_yscale("log")
        ax.set_xlabel("Δω (arcsec)")
        ax.set_ylabel("Normalized intensity" if self.norm.isChecked() else "Intensity (counts)")
        if widths:
            span = max(4 * max(widths), 60.0)
            ax.set_xlim(-span, span)
        if self._rows:
            ax.legend(fontsize=7, loc="upper right")
        fig.tight_layout()
        self.canvas.draw_idle()

    def group_results(self) -> dict[str, dict]:
        """Per-sample tilt/twist, ρ_screw/ρ_edge and Williamson–Hall-ω."""
        b = self._b()
        groups: dict[str, list[dict]] = {}
        for r in self._rows:
            groups.setdefault(r["sample"], []).append(r)
        out = {}
        for name, rows in groups.items():
            tt = hrxrd.tilt_twist([r["m"]["fwhm_corrected"] for r in rows],
                                  [r["chi"] for r in rows])
            res = {"n": len(rows), "tilt": tt["tilt"], "twist": tt["twist"],
                   "rho_screw": hrxrd.dislocation_density(tt["tilt"], b["screw"]),
                   "rho_edge": hrxrd.dislocation_density(tt["twist"], b["edge"])}
            sym = [r for r in rows if abs(r["chi"]) < 5 and r["two_theta"]]
            if len({round(r["two_theta"], 1) for r in sym}) >= 2:
                wh = hrxrd.williamson_hall_omega(
                    [r["m"]["fwhm_corrected"] for r in sym], [r["two_theta"] for r in sym],
                    float(sym[0]["pattern"].wavelength))
                res["wh_tilt"], res["L_par_nm"] = wh["tilt_deg"], wh["L_par_nm"]
            out[name] = res
        return out

    def _summarize(self):
        parts = ["<b>Per sample</b> (rows sharing a Sample name are combined):<ul>"]
        for name, r in self.group_results().items():
            line = f"<li><b>{name}</b> — tilt {_fmt(r['tilt'] * 3600, 0)}″"
            if np.isfinite(r["twist"]):
                line += (f", twist {_fmt(r['twist'] * 3600, 0)}″ · ρ<sub>screw</sub> "
                         f"{_fmt(r['rho_screw'], sci=True)}, ρ<sub>edge</sub> "
                         f"{_fmt(r['rho_edge'], sci=True)}, total "
                         f"{_fmt(r['rho_screw'] + r['rho_edge'], sci=True)} cm⁻²")
            else:
                line += (f" · ρ<sub>screw</sub> {_fmt(r['rho_screw'], sci=True)} cm⁻²"
                         " <i>(add a skew-symmetric RC (χ&gt;0) under the same Sample "
                         "for twist and the edge density)</i>")
            if "L_par_nm" in r:
                line += (f" · WH-ω: tilt {_fmt(r['wh_tilt'] * 3600, 0)}″, "
                         f"L<sub>∥</sub> {_fmt(r['L_par_nm'], 0)} nm")
            parts.append(line + "</li>")
        parts.append("</ul><p style='color:#666;font-size:11px'>ρ = β²/(4.35 b²) (Dunn &amp; "
                     "Kogh 1957; mosaic-block upper bound). Tilt/twist from β(χ)² = "
                     "(β<sub>tilt</sub> cos χ)² + (β<sub>twist</sub> sin χ)². WH-ω: "
                     "β sinθ/λ vs sinθ/λ, L<sub>∥</sub> = 0.9/(2y₀) (Moram &amp; Vickers, "
                     "Rep. Prog. Phys. 2009). ᵈ = Kα1/Kα2 doublet modelled (no "
                     "monochromator in the file's optics).</p>")
        self.summary.setHtml("".join(parts))

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export rocking curves",
                                              "rocking_curves.csv", "CSV (*.csv)")
        if not path:
            return
        b = self._b()
        groups = self.group_results()
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["sample", "scan", "reflection", "chi_deg", "two_theta_deg",
                        "omega_peak_deg", "fwhm_arcsec", "fwhm_fit_arcsec",
                        "fwhm_data_arcsec", "fwhm_corrected_arcsec", "eta", "r_squared",
                        "rho_cm2", "sample_tilt_arcsec", "sample_twist_arcsec",
                        "sample_rho_screw_cm2", "sample_rho_edge_cm2", "sample_L_par_nm"])
            for r in self._rows:
                m, g = r["m"], groups[r["sample"]]
                bb = b["screw"] if abs(r["chi"]) < 5 else b["edge"]
                w.writerow([r["sample"], r["pattern"].name, r["reflection"], r["chi"],
                            r["two_theta"], m["peak"], m["fwhm_arcsec"],
                            m["fwhm_fit_arcsec"], m["fwhm_data_arcsec"],
                            m["fwhm_corrected_arcsec"], m["eta"], m["r_squared"],
                            hrxrd.dislocation_density(m["fwhm_corrected"], bb),
                            g["tilt"] * 3600, g["twist"] * 3600, g["rho_screw"],
                            g["rho_edge"], g.get("L_par_nm", "")])


# =============================================================================
# Reciprocal-space maps
# =============================================================================

class RSMDialog(QDialog):
    """Reciprocal-space map viewer + strain / relaxation analysis."""

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Reciprocal-space map — {data.get('name', '')}")
        self.resize(1150, 780)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.data = data
        self.qx, self.qz = hrxrd.rsm_to_q(data["omega"], data["two_theta"],
                                          data["wavelength"])
        self.I = np.asarray(data["intensity"], dtype=float)
        self.peaks = hrxrd.rsm_peaks(self.qx, self.qz, self.I, n=2)

        self.space = QComboBox()
        self.space.addItems(["Q space (Å⁻¹)", "Angles (ω, 2θ)"])
        self.space.currentTextChanged.connect(lambda _: self._plot())
        self.levels = QDoubleSpinBox()
        self.levels.setRange(1.0, 8.0)
        self.levels.setValue(4.0)
        self.levels.setSuffix(" decades")
        self.levels.valueChanged.connect(lambda _: self._plot())
        self.system = QComboBox()
        self.system.addItems(["hexagonal (0001)", "cubic (001)"])
        self.hkl = QLineEdit("1 0 -1 5")
        self.hkl.setToolTip("Reflection of the map, e.g. '1 0 -1 5' (hexagonal) or "
                            "'2 2 4' (cubic).")
        self.film_mat = _material_combo("GaN (wurtzite)")
        self.a0, self.c0, self.asub = QDoubleSpinBox(), QDoubleSpinBox(), QDoubleSpinBox()
        for sp in (self.a0, self.c0, self.asub):
            sp.setRange(0.0, 50.0)
            sp.setDecimals(4)
            sp.setSuffix(" Å")
        self.sub_from_peak = QCheckBox("Substrate a∥ from substrate peak (same hkl)")
        self.sub_from_peak.setChecked(True)
        self.film_mat.currentTextChanged.connect(self._fill_bulk)
        self.system.currentTextChanged.connect(lambda _: self._analyse())
        self.hkl.textChanged.connect(lambda _: self._analyse())
        for sp in (self.a0, self.c0, self.asub):
            sp.valueChanged.connect(lambda _: self._analyse())
        self.sub_from_peak.stateChanged.connect(lambda _: self._analyse())

        form = QFormLayout()
        form.addRow("Axes", self.space)
        form.addRow("Contour range", self.levels)
        form.addRow("Geometry", self.system)
        form.addRow("Reflection (hkl)", self.hkl)
        form.addRow("Film material", self.film_mat)
        form.addRow("Film bulk a₀", self.a0)
        form.addRow("Film bulk c₀ (hex)", self.c0)
        form.addRow(self.sub_from_peak)
        form.addRow("Substrate a∥", self.asub)
        form.addRow(_button("Swap substrate / film", self._swap))
        hint = QLabel("Click the map (Q space) to place the <b>film</b> peak — it snaps "
                      "to the local maximum. The strongest peak is taken as the substrate.")
        hint.setWordWrap(True)
        form.addRow(hint)

        self.result = QTextBrowser()
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.addLayout(form)
        sl.addWidget(self.result, 1)
        sl.addWidget(_button("Export map CSV (Qx, Qz, I)…", self._export_csv))
        sl.addWidget(_button("Export figure…", lambda: _save_figure(
            self, self.canvas.figure, f"{data.get('name', 'rsm')}_rsm")))
        side.setMaximumWidth(390)

        self.canvas = MplCanvas(width=7.0, height=6.0)
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.canvas.mpl_connect("button_press_event", self._on_click)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.toolbar)
        ll.addWidget(self.canvas)
        main = QHBoxLayout()
        main.addWidget(left, 1)
        main.addWidget(side)
        lay = QVBoxLayout(self)
        lay.addLayout(main, 1)
        lay.addLayout(_close_bar(self))

        self._fill_bulk(self.film_mat.currentText())
        self._plot()
        self._analyse()

    def _fill_bulk(self, name):
        m = hrxrd.MATERIALS.get(name)
        if not m:
            return
        for sp in (self.a0, self.c0):
            sp.blockSignals(True)
        self.a0.setValue(m["a"])
        self.c0.setValue(m.get("c", m["a"]))
        for sp in (self.a0, self.c0):
            sp.blockSignals(False)
        self.system.setCurrentText("hexagonal (0001)" if m["system"] == "hexagonal"
                                   else "cubic (001)")
        self._analyse()

    def _swap(self):
        if len(self.peaks) >= 2:
            self.peaks[0], self.peaks[1] = self.peaks[1], self.peaks[0]
            self._plot()
            self._analyse()

    def _on_click(self, ev):
        if ev.inaxes is None or ev.button != 1 or str(self.toolbar.mode):
            return
        if not self.space.currentText().startswith("Q"):
            return
        px, pz = float(ev.xdata), float(ev.ydata)
        d = np.hypot((self.qx - px) / (np.ptp(self.qx) or 1),
                     (self.qz - pz) / (np.ptp(self.qz) or 1))
        m = d < 0.02
        if m.any():
            j = int(np.argmax(np.where(m, self.I, -np.inf)))
            px, pz = float(self.qx[j]), float(self.qz[j])
        film = {"qx": px, "qz": pz, "intensity": float(self.I[m].max()) if m.any() else 0.0}
        if len(self.peaks) >= 2:
            self.peaks[1] = film
        else:
            self.peaks.append(film)
        self._plot()
        self._analyse()

    def _plot(self):
        import matplotlib.tri as mtri

        fig = self.canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        q = self.space.currentText().startswith("Q")
        x, y = (self.qx, self.qz) if q else (np.asarray(self.data["two_theta"]),
                                             np.asarray(self.data["omega"]))
        logI = np.log10(np.clip(self.I, 1.0, None))
        top = float(logI.max())
        lv = np.linspace(max(top - self.levels.value(), 0.0), top, 30)
        tri = mtri.Triangulation(x / (np.ptp(x) or 1), y / (np.ptp(y) or 1))
        t = tri.triangles
        xs, ys = tri.x[t], tri.y[t]
        edge = np.max(np.hypot(xs - np.roll(xs, 1, axis=1), ys - np.roll(ys, 1, axis=1)),
                      axis=1)
        mask = edge > 5 * np.median(edge)  # don't bridge gaps between scans
        tri = mtri.Triangulation(x, y, triangles=t, mask=mask)
        cf = ax.tricontourf(tri, np.clip(logI, lv[0], None), levels=lv, cmap="viridis")
        cb = fig.colorbar(cf, ax=ax, label="intensity (counts)")
        decades = np.arange(np.ceil(lv[0]), np.floor(lv[-1]) + 1)
        cb.set_ticks(decades)
        cb.set_ticklabels([f"10$^{{{int(d)}}}$" for d in decades])
        if q:
            ax.set_xlabel("Qx (Å⁻¹)")
            ax.set_ylabel("Qz (Å⁻¹)")
            for k, p in enumerate(self.peaks[:2]):
                ax.plot(p["qx"], p["qz"], "+", ms=14, mew=2,
                        color="white" if k == 0 else "#ff4040")
                ax.annotate("substrate" if k == 0 else "film", (p["qx"], p["qz"]),
                            xytext=(8, 8), textcoords="offset points", color="white",
                            fontsize=9)
            if self.peaks:
                s = self.peaks[0]
                zz = ax.get_ylim()
                ax.axvline(s["qx"], color="w", ls="--", lw=0.8, alpha=0.8)
                if s["qz"]:
                    ax.plot(s["qx"] / s["qz"] * np.array(zz), zz, color="w", ls=":",
                            lw=0.8, alpha=0.8)
                ax.set_ylim(*zz)
        else:
            ax.set_xlabel("2θ (°)")
            ax.set_ylabel("ω (°)")
        ax.set_title(self.data.get("name", ""), fontsize=10)
        fig.tight_layout()
        self.canvas.draw_idle()

    def results(self) -> dict:
        """Peak positions, lattice parameters, strain and relaxation (for tests/CSV)."""
        hkl = parse_hkl_text(self.hkl.text())
        sysname = self.system.currentText()
        out = {"peaks": self.peaks[:2], "lattice": []}
        if not hkl or not self.peaks:
            return out
        out["lattice"] = [hrxrd.lattice_from_q(p["qx"], p["qz"], hkl, sysname)
                          for p in self.peaks[:2]]
        if len(out["lattice"]) == 2:
            if self.sub_from_peak.isChecked() and np.isfinite(out["lattice"][0]["a_par"]):
                self.asub.blockSignals(True)
                self.asub.setValue(out["lattice"][0]["a_par"])
                self.asub.blockSignals(False)
            cub = sysname.startswith("cubic")
            a0 = self.a0.value()
            c0 = a0 if cub else self.c0.value()
            f = out["lattice"][1]
            out["strain_par"] = (f["a_par"] - a0) / a0 * 100 if a0 else float("nan")
            out["strain_perp"] = (f["a_perp"] - c0) / c0 * 100 if c0 else float("nan")
            out["relaxation"] = hrxrd.relaxation(f["a_par"], self.asub.value(), a0)
        return out

    def _analyse(self):
        r = self.results()
        if not r["lattice"]:
            self.result.setHtml("<i>Need at least one peak and a valid (hkl).</i>")
            return
        cub = self.system.currentText().startswith("cubic")
        html = ["<table cellpadding=3><tr><th></th><th>Qx</th><th>Qz</th>"
                f"<th>{'a∥' if cub else 'a'} (Å)</th><th>{'a⊥' if cub else 'c'} (Å)</th></tr>"]
        for k, (p, L) in enumerate(zip(r["peaks"], r["lattice"])):
            html.append(f"<tr><td>{'substrate' if k == 0 else 'film'}</td>"
                        f"<td>{p['qx']:.5f}</td><td>{p['qz']:.5f}</td>"
                        f"<td>{_fmt(L['a_par'], 4)}</td><td>{_fmt(L['a_perp'], 4)}</td></tr>")
        html.append("</table>")
        if "relaxation" in r:
            html.append(f"<p><b>Film strain</b>: ε∥ = {_fmt(r['strain_par'], 3)} %, "
                        f"ε⊥ = {_fmt(r['strain_perp'], 3)} %<br><b>Relaxation</b> R = "
                        f"{_fmt(r['relaxation'], 1)} % (0 % pseudomorphic, 100 % relaxed)</p>")
        html.append("<p style='color:#666;font-size:11px'>Q = (cos ω − cos(2θ−ω), "
                    "sin ω + sin(2θ−ω))/λ. Dashed: pseudomorphic line (substrate Qx); "
                    "dotted: relaxation line through the origin. R = (a∥,film − a<sub>sub"
                    "</sub>)/(a₀ − a<sub>sub</sub>).</p>")
        self.result.setHtml("".join(html))

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export RSM",
                                              f"{self.data.get('name', 'rsm')}.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["omega_deg", "two_theta_deg", "qx_inv_A", "qz_inv_A", "counts"])
            for row in zip(self.data["omega"], self.data["two_theta"], self.qx, self.qz,
                           self.I):
                w.writerow([f"{v:.6f}" for v in row[:4]] + [f"{row[4]:.0f}"])


def rsm_from_csv(path) -> dict:
    """Load an RSM CSV with omega / two_theta / counts columns (as exported here)."""
    raw = np.genfromtxt(path, delimiter=",", names=True)
    names = [n.lower() for n in raw.dtype.names]

    def col(*keys):
        for i, n in enumerate(names):
            if any(k in n for k in keys):
                return np.asarray(raw[raw.dtype.names[i]], dtype=float)
        raise ValueError(f"CSV needs a column containing one of {keys}")

    return {"omega": col("omega"), "two_theta": col("two_theta", "2theta", "tth"),
            "intensity": col("count", "intens"), "wavelength": 1.540598,
            "name": Path(path).stem}


# =============================================================================
# Thickness fringes
# =============================================================================

class ThicknessDialog(QDialog):
    """Film thickness from Pendellösung / Laue fringes around a chosen peak."""

    def __init__(self, pattern, peaks: list[tuple[str, float]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Thickness fringes — {pattern.name}")
        self.resize(840, 640)
        self.p = pattern
        self.result: dict = {}
        self.peak = QComboBox()
        for label, tt in peaks:
            self.peak.addItem(f"{label}  ({tt:.3f}°)", tt)
        self.window = QDoubleSpinBox()
        self.window.setRange(0.3, 15.0)
        self.window.setValue(2.5)
        self.window.setSuffix(" °")
        self.window.setToolTip("Half-width of the 2θ range searched for fringes.")
        self.peak.currentIndexChanged.connect(lambda _: self._run())
        self.window.valueChanged.connect(lambda _: self._run())
        top = QHBoxLayout()
        top.addWidget(QLabel("Peak"))
        top.addWidget(self.peak, 1)
        top.addWidget(QLabel("± window"))
        top.addWidget(self.window)
        self.canvas = MplCanvas(width=6.5, height=4.2)
        self.res = QLabel()
        self.res.setWordWrap(True)
        self.res.setTextFormat(Qt.TextFormat.RichText)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(NavigationToolbar(self.canvas, self))
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.res)
        lay.addLayout(_close_bar(self, _button(
            "Export figure…", lambda: _save_figure(self, self.canvas.figure, "fringes"))))
        self._run()

    def _run(self):
        if self.peak.count() == 0:
            self.res.setText("No peaks detected in this scan.")
            return
        c = float(self.peak.currentData())
        w = self.window.value()
        x, y = self.p.two_theta, self.p.intensity
        r = hrxrd.fringe_thickness(x, y, c, float(self.p.wavelength), window_deg=w)
        self.result = r
        fig = self.canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        sel = np.abs(x - c) <= w
        ax.semilogy(x[sel], np.clip(y[sel], 1, None), "-", lw=1.0, color="#1f77b4")
        for f in r.get("fringes", []):
            ax.axvline(f, color="#d62728", lw=0.6, ls=":")
        ax.axvline(c, color="k", lw=0.8)
        ax.set_xlabel("2θ (°)")
        ax.set_ylabel("Intensity (counts)")
        fig.tight_layout()
        self.canvas.draw_idle()
        t = r["thickness_nm"]
        if np.isfinite(t):
            side = " · ".join(f"{k} side {v:.1f} nm" for k, v in r["per_side_nm"].items())
            self.res.setText(
                f"<b>Thickness t = {t:.1f} ± {r['uncertainty_nm']:.1f} nm</b> from "
                f"{r['n_spacings']} fringe spacings ({side}).<br><span style='color:#666'>"
                "t = λ / (2 Δsinθ) between consecutive side maxima (red). This is the "
                "coherently diffracting thickness — the film thickness for a uniform, "
                "fully coherent layer.</span>")
        else:
            self.res.setText(f"<b>No thickness fringes found</b> — {r.get('reason', '')}. "
                             "Fringes need a smooth, uniform film; try a wider window, or "
                             "a slower scan with finer steps.")


# =============================================================================
# Williamson–Hall (2θ-ω)
# =============================================================================

class WilliamsonHallDialog(QDialog):
    """Size + microstrain from a family of peak widths (Kα1, instrument-corrected)."""

    def __init__(self, pattern, peaks, parent=None, instrument_fwhm_deg: float = 0.0):
        super().__init__(parent)
        from xrdlab.core.fitting import doublet_kwargs, fit_peak
        from xrdlab.core.processing import corrected_fwhm

        self.setWindowTitle(f"Williamson–Hall — {pattern.name}")
        self.resize(820, 680)
        self.wl = float(pattern.wavelength)
        self.result: dict = {}
        kw = doublet_kwargs(pattern)
        x = pattern.two_theta
        self.rows = []
        for label, pk in peaks:
            i = int(np.clip(np.searchsorted(x, pk.two_theta), 0, len(x) - 1))
            fit = fit_peak(x, pattern.intensity, i, **kw)
            if fit is None or fit.r_squared < 0.8:
                continue
            w = corrected_fwhm(fit.fwhm, instrument_fwhm_deg) if instrument_fwhm_deg \
                else fit.fwhm
            self.rows.append({"label": label, "two_theta": fit.center, "fwhm": w,
                              "phase": label.split(" (")[0]})
        self.table = QTableWidget(len(self.rows), 4)
        self.table.setHorizontalHeaderLabels(["Use", "Reflection", "2θ (°)", "FWHM Kα1 (°)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.phase = QComboBox()
        self.phase.addItems(sorted({r["phase"] for r in self.rows}))
        for i, r in enumerate(self.rows):
            use = QTableWidgetItem()
            use.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(i, 0, use)
            self.table.setItem(i, 1, _item(r["label"]))
            self.table.setItem(i, 2, _item(f"{r['two_theta']:.3f}"))
            self.table.setItem(i, 3, _item(f"{r['fwhm']:.4f}"))
        self.table.itemChanged.connect(lambda _: self._run())
        self.phase.currentTextChanged.connect(lambda _: self._select_phase())
        top = QHBoxLayout()
        top.addWidget(QLabel("Phase"))
        top.addWidget(self.phase, 1)
        top.addWidget(QLabel(f"Instrument correction {instrument_fwhm_deg:.4f}°"
                             if instrument_fwhm_deg else "No instrument correction "
                             "(Settings ▸ Instrument broadening…)"))
        self.canvas = MplCanvas(width=6, height=3.6)
        self.res = QLabel()
        self.res.setWordWrap(True)
        self.res.setTextFormat(Qt.TextFormat.RichText)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.res)
        lay.addLayout(_close_bar(self, _button(
            "Export figure…", lambda: _save_figure(self, self.canvas.figure,
                                                   "williamson_hall"))))
        self._select_phase()

    def _select_phase(self):
        ph = self.phase.currentText()
        self.table.blockSignals(True)
        for i, r in enumerate(self.rows):
            self.table.item(i, 0).setCheckState(
                Qt.CheckState.Checked if r["phase"] == ph else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._run()

    def _run(self):
        use = [r for i, r in enumerate(self.rows)
               if self.table.item(i, 0).checkState() == Qt.CheckState.Checked]
        fig = self.canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        if len(use) < 2:
            self.result = {}
            self.res.setText("Select at least two reflections of one phase (ideally "
                             "several orders of one family, e.g. 111 / 222 / 333).")
            self.canvas.draw_idle()
            return
        r = hrxrd.williamson_hall([u["fwhm"] for u in use], [u["two_theta"] for u in use],
                                  self.wl)
        self.result = r
        f = r["fit"]
        ax.plot(f.x, f.y, "o", color="#1f77b4")
        for u, xx, yy in zip(use, f.x, f.y):
            ax.annotate(u["label"], (xx, yy), xytext=(4, 4), textcoords="offset points",
                        fontsize=8)
        xs = np.linspace(0, f.x.max() * 1.05, 50)
        ax.plot(xs, f.slope * xs + f.intercept, "-", color="#d62728", lw=1)
        ax.set_xlabel("4 sin θ")
        ax.set_ylabel("β cos θ (rad)")
        fig.tight_layout()
        self.canvas.draw_idle()
        warn = "" if (f.intercept > 0 and f.slope >= 0) else (
            "<br><b style='color:#b00'>Negative intercept/slope: the widths aren't "
            "broadening-dominated (resolution-limited, or two points only), so D/ε are "
            "not meaningful.</b>")
        self.res.setText(
            f"<b>Coherence length D = {_fmt(r['size_nm'], 1)} nm</b>, "
            f"<b>microstrain ε = {_fmt(r['strain'] * 100, 4)} %</b> (R² {f.r_squared:.3f})"
            f"{warn}<br><span style='color:#666'>β cosθ = Kλ/D + 4ε sinθ, K = 0.9, β = "
            "Kα1 FWHM in 2θ. For an epitaxial film D is the vertical coherence length "
            "(≈ thickness if defect-free).</span>")


# =============================================================================
# φ scans
# =============================================================================

class PhiScanDialog(QDialog):
    """In-plane rotational symmetry from a φ scan (epitaxial relationship, twins)."""

    def __init__(self, pattern, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"φ scan — {pattern.name}")
        self.resize(840, 580)
        self.p = pattern
        self.result: dict = {}
        self.prom = QDoubleSpinBox()
        self.prom.setRange(0.5, 90.0)
        self.prom.setValue(10.0)
        self.prom.setSuffix(" % of max")
        self.prom.valueChanged.connect(lambda _: self._run())
        top = QHBoxLayout()
        top.addWidget(QLabel("Peak prominence"))
        top.addWidget(self.prom)
        top.addStretch(1)
        self.canvas = MplCanvas(width=6.5, height=3.6)
        self.res = QLabel()
        self.res.setWordWrap(True)
        self.res.setTextFormat(Qt.TextFormat.RichText)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.res)
        lay.addLayout(_close_bar(self, _button(
            "Export figure…", lambda: _save_figure(self, self.canvas.figure, "phi_scan"))))
        self._run()

    def _run(self):
        x, y = self.p.two_theta, self.p.intensity
        r = hrxrd.phi_symmetry(x, y, prominence_frac=self.prom.value() / 100.0)
        self.result = r
        fig = self.canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        ax.semilogy(x, np.clip(y, 1, None), "-", lw=1.0, color="#1f77b4")
        for p in r["peaks"]:
            ax.axvline(p, color="#d62728", lw=0.6, ls=":")
        ax.set_xlabel("φ (°)")
        ax.set_ylabel("Intensity (counts)")
        fig.tight_layout()
        self.canvas.draw_idle()
        pk = ", ".join(f"{p:.1f}°" for p in r["peaks"])
        full = "" if r.get("full_rotation") else \
            " <i>(partial rotation — n-fold assumes the observed spacing repeats)</i>"
        self.res.setText(
            f"<b>{r.get('n_peaks', len(r['peaks']))} peaks</b>, spacing "
            f"{_fmt(r['spacing'], 2)}° → <b>{r['n_fold']}-fold</b>{full}<br>Peaks: {pk}"
            "<br><span style='color:#666'>E.g. a {200} φ scan of a (111)-oriented cubic "
            "film shows 3 peaks per domain; 6 means two rotation-twin domains 60° apart. "
            "Compare with the substrate's φ positions for the in-plane epitaxial "
            "relationship.</span>")
