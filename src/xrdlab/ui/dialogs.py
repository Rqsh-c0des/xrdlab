"""Dialogs for XRDLab settings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xrdlab import config
from xrdlab.core.naming import label_for, parse_filename

from PySide6.QtWidgets import QTextBrowser

__all__ = [
    "FilenameParsingDialog",
    "PhaseDatabaseDialog",
    "PhaseReflectionsDialog",
    "PolymorphPickerDialog",
]


class PolymorphPickerDialog(QDialog):
    """Pick one structure (polymorph) among candidates for a formula."""

    def __init__(self, formula: str, rows: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Choose a structure for {formula}")
        self.setMinimumWidth(600)
        self.listw = QListWidget()
        for r in rows:
            self.listw.addItem(r)
        if rows:
            self.listw.setCurrentRow(0)
        self.listw.itemDoubleClicked.connect(lambda _=None: self.accept())
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"{len(rows)} candidate structures — pick the polymorph "
            "(space group / cell shown):"
        ))
        layout.addWidget(self.listw)
        layout.addWidget(buttons)

    def selected_index(self) -> int:
        return self.listw.currentRow()


class PhaseReflectionsDialog(QDialog):
    """Show a phase's reference reflection table (hkl / d / 2θ / intensity)."""

    def __init__(self, formula: str, db, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"{formula} — reference reflections")
        self.setMinimumSize(460, 520)
        entry = db._data.get(formula, {})
        cit = entry.get("citation") or {}
        rows = db.reflection_table(formula)
        system = entry.get("crystal_system", "")
        sg = entry.get("space_group", "")
        sym = " &middot; ".join(s for s in (system, sg) if s)

        parts = [
            "<style>table{border-collapse:collapse;} td,th{border:1px solid #8884;"
            "padding:2px 10px;text-align:right;} th{text-align:center;} a{color:#3b82f6;}</style>",
            f"<h2>{formula}</h2>",
            f"<p><b>Crystal system:</b> {sym or 'unknown'}</p>" if sym else "",
            f"<p style='color:#888'>{len(rows)} reflections &middot; 2θ at Cu Kα1 "
            f"(λ = 1.5406 Å) &middot; source: {entry.get('material_id','—')}</p>",
            "<table><tr><th>h k l</th><th>d (Å)</th><th>2θ (°)</th><th>I (%)</th></tr>",
        ]
        for hkl, d, tt, inten in rows:
            parts.append(
                f"<tr><td>{hkl or '—'}</td><td>{d:.4f}</td>"
                f"<td>{tt:.3f}</td><td>{inten:.1f}</td></tr>"
            )
        parts.append("</table>")
        if cit.get("formatted"):
            parts.append(f"<p style='color:#888;font-size:0.9em'>{cit['formatted']}</p>")

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml("".join(parts))
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        close.accepted.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(browser)
        layout.addWidget(close)


class FilenameParsingDialog(QDialog):
    """Edit the regex used to pull a label out of a data file's name.

    Shows a live preview so the user can confirm the pattern extracts the fields
    they expect before saving.
    """

    def __init__(self, example: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Filename parsing")
        self.setMinimumWidth(560)

        self.pattern = QLineEdit(config.get_filename_pattern())
        self.field = QLineEdit(config.get_filename_label_field())
        self.example = QLineEdit(example or "XRD_5292_GaN_ScN_260713_1551")

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(self.preview.textInteractionFlags())

        reset_btn = QPushButton("Reset to default")
        reset_btn.clicked.connect(self._reset)

        help_lbl = QLabel(
            "Use a Python regex with named groups, e.g. "
            "<code>(?P&lt;sample&gt;.+?)</code>. The <b>label field</b> names which "
            "group becomes the plot label. Underscores in the value display as “/”."
        )
        help_lbl.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Pattern (regex)", self.pattern)
        form.addRow("Label field", self.field)
        form.addRow("Example name", self.example)
        form.addRow("Preview", self.preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(help_lbl)
        layout.addLayout(form)
        layout.addWidget(reset_btn)
        layout.addWidget(buttons)

        for w in (self.pattern, self.field, self.example):
            w.textChanged.connect(self._update_preview)
        self._update_preview()

    def _update_preview(self) -> None:
        stem = self.example.text().strip()
        fields = parse_filename(stem, self.pattern.text())
        label = label_for(stem, self.pattern.text(), self.field.text().strip())
        if fields:
            parts = ", ".join(f"{k}={v}" for k, v in fields.items())
            self.preview.setText(f"Fields: {parts}\nLabel → “{label}”")
        else:
            self.preview.setText(
                f"No match — label falls back to the full name “{label}”."
            )

    def _reset(self) -> None:
        self.pattern.setText(config.DEFAULT_FILENAME_PATTERN)
        self.field.setText(config.DEFAULT_FILENAME_FIELD)

    def _save(self) -> None:
        config.set_filename_pattern(self.pattern.text())
        config.set_filename_label_field(self.field.text())
        self.accept()


class PhaseDatabaseDialog(QDialog):
    """View and grow the local phase database used for peak identification."""

    def __init__(self, db, parent: QWidget | None = None):
        super().__init__(parent)
        self._db = db
        self.setWindowTitle("Phase database")
        self.setMinimumWidth(460)

        intro = QLabel(
            "Phases here identify peaks in <b>any</b> dataset (matched by "
            "wavelength-independent d-spacings). Add the materials you expect to "
            "see; they persist across sessions. Adding requires a Materials Project "
            "API key."
        )
        intro.setWordWrap(True)

        self.listw = QListWidget()

        self.source = QComboBox()
        self.source.addItems(["Materials Project", "COD"])
        self.source.setToolTip(
            "Where to fetch structures + citations. Materials Project uses DFT "
            "structures (best for epitaxial-film references); COD needs no API key."
        )
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source:"))
        source_row.addWidget(self.source)
        source_row.addStretch(1)

        add_btn = QPushButton("Add formula(s)…")
        add_btn.clicked.connect(self._add)
        poly_btn = QPushButton("Choose polymorph…")
        poly_btn.setToolTip("Add one formula, choosing among its polymorphs by space group.")
        poly_btn.clicked.connect(self._add_polymorph)
        seed_btn = QPushButton("Seed common phases")
        seed_btn.clicked.connect(self._seed)
        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self._remove)
        refl_btn = QPushButton("Reflections…")
        refl_btn.clicked.connect(self._show_reflections)
        self.listw.itemDoubleClicked.connect(lambda _=None: self._show_reflections())
        import_btn = QPushButton("Import CIF…")
        import_btn.setToolTip(
            "Add a reference from a local CIF file (e.g. one you exported yourself "
            "from crystallography software under your own licence)."
        )
        import_btn.clicked.connect(self._import_cif)
        import_folder_btn = QPushButton("Import CIF folder…")
        import_folder_btn.setToolTip("Batch-import every .cif in a folder.")
        import_folder_btn.clicked.connect(self._import_cif_folder)

        btn_row = QHBoxLayout()
        btn_row.addWidget(add_btn)
        btn_row.addWidget(poly_btn)
        btn_row.addWidget(seed_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addWidget(refl_btn)

        btn_row2 = QHBoxLayout()
        btn_row2.addWidget(import_btn)
        btn_row2.addWidget(import_folder_btn)
        btn_row2.addStretch(1)

        self.status = QLabel("")
        self.status.setWordWrap(True)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        close.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.listw)
        layout.addLayout(source_row)
        layout.addLayout(btn_row)
        layout.addLayout(btn_row2)
        layout.addWidget(self.status)
        layout.addWidget(close)

        self._refresh()

    def _refresh(self) -> None:
        self.listw.clear()
        for formula in self._db.formulas():
            entry = self._db._data.get(formula, {})
            n = len(entry.get("reflections", []))
            mid = entry.get("material_id", "")
            sysm = entry.get("crystal_system", "") or "?"
            self.listw.addItem(f"{formula}   —   {sysm}   —   {n} refl   {mid}")
        self.setWindowTitle(f"Phase database ({len(self._db)} phases)")

    def _formula_of_row(self, text: str) -> str:
        return text.split("—")[0].strip()

    def _add_formulas(self, formulas: list[str]) -> None:
        from xrdlab import config
        from xrdlab.citations import enrich_citation

        source = self.source.currentText()
        mailto = config.get_crossref_mailto()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        added, failed = [], []
        try:
            if source == "COD":
                from xrdlab.cod.client import CODClient

                client = CODClient()
            elif source == "AMCSD":
                from xrdlab.amcsd.client import AMCSDClient

                client = AMCSDClient()
            else:
                from xrdlab.mp.client import MPClient

                client = MPClient()  # may raise if no API key
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Phase database", str(exc))
            return

        try:
            for f in formulas:
                try:
                    if source in ("COD", "AMCSD"):
                        ref, citation = client.formula_to_reference(f)
                    else:
                        ref = client.formula_to_reference(f, two_theta_range=(5.0, 158.0))
                        citation = client.get_provenance(ref.material_id)
                    citation = enrich_citation(citation, mailto)
                    self._db.add_reference(ref, citation=citation)
                    n = len(ref.d_spacings) if ref.d_spacings is not None else 0
                    added.append(f"{f} ({n})")
                except Exception as exc:  # noqa: BLE001 — per-formula failure
                    failed.append(f"{f}: {exc}")
        finally:
            QApplication.restoreOverrideCursor()

        self._refresh()
        self.status.setText(
            "  |  ".join((["Added: " + ", ".join(added)] if added else [])
                         + (["Failed: " + ", ".join(failed)] if failed else []))
        )

    def _add(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Add phases",
            "Formula(s), comma-separated (e.g. GaN, ScN, AlN):",
        )
        if ok and text.strip():
            self._add_formulas([f.strip() for f in text.split(",") if f.strip()])

    def _seed(self) -> None:
        from xrdlab.ml.phase_db import DEFAULT_SEED_PHASES

        self._add_formulas(DEFAULT_SEED_PHASES)

    def _polymorph_candidates(self, formula: str):
        """Return [(display, ('COD'|'MP', client, obj))] candidates for ``formula``."""
        source = self.source.currentText()
        cands = []
        if source == "COD":
            from pymatgen.core import Composition

            from xrdlab.cod.client import CODClient, _clean_cod_formula

            client = CODClient()
            for r in client.search(formula)[:40]:
                raw = r.get("formula") or r.get("cellformula") or ""
                try:
                    rf = Composition(_clean_cod_formula(raw)).reduced_formula
                except Exception:  # noqa: BLE001
                    rf = raw.strip()
                disp = (f"{rf}    sg {r.get('sg','?')}    "
                        f"a={r.get('a','?')} c={r.get('c','?')}    COD {r.get('file')}")
                cands.append((disp, ("COD", client, r)))
        elif source == "Materials Project":
            from xrdlab.mp.client import MPClient

            client = MPClient()
            for d in client.search_candidates(formula)[:40]:
                sg = getattr(getattr(d, "symmetry", None), "symbol", "?")
                eh = getattr(d, "energy_above_hull", None)
                tail = f"  Ehull={eh:.3f}" if isinstance(eh, (int, float)) else ""
                disp = f"{getattr(d,'formula_pretty',formula)}    sg {sg}    {d.material_id}{tail}"
                cands.append((disp, ("MP", client, d)))
        else:
            raise RuntimeError(
                "Polymorph choice is available for COD and Materials Project. "
                "AMCSD adds the best composition match."
            )
        return cands

    def _add_polymorph(self) -> None:
        from xrdlab import config
        from xrdlab.citations import enrich_citation

        formula, ok = QInputDialog.getText(self, "Add — choose polymorph", "Formula:")
        if not (ok and formula.strip()):
            return
        formula = formula.strip()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            cands = self._polymorph_candidates(formula)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Phase database", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        if not cands:
            self.status.setText(f"No candidate structures for {formula}.")
            return
        picker = PolymorphPickerDialog(formula, [c[0] for c in cands], self)
        if not picker.exec() or picker.selected_index() < 0:
            return
        kind, client, obj = cands[picker.selected_index()][1]

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if kind == "COD":
                ref, citation = client.reference_from_row(obj)
            else:
                from xrdlab.mp.simulate import simulate_pattern

                ref = simulate_pattern(
                    obj.structure, wavelength="CuKa1", two_theta_range=(5.0, 158.0),
                    formula=getattr(obj, "formula_pretty", formula),
                    material_id=str(obj.material_id),
                )
                citation = client.get_provenance(str(obj.material_id))
            citation = enrich_citation(citation, config.get_crossref_mailto())
            self._db.add_reference(ref, citation=citation)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Add failed", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh()
        self.status.setText(f"Added {formula} ({kind}).")

    def _remove(self) -> None:
        for item in self.listw.selectedItems():
            self._db.remove(self._formula_of_row(item.text()))
        self._refresh()

    def _show_reflections(self) -> None:
        item = self.listw.currentItem()
        if item is None:
            self.status.setText("Select a phase first.")
            return
        formula = self._formula_of_row(item.text())
        PhaseReflectionsDialog(formula, self._db, parent=self).exec()

    def _import_one_cif(self, path) -> str:
        """Add a single CIF to the database; returns the reduced formula."""
        from pymatgen.core import Structure

        from xrdlab.cifutil import cif_citation
        from xrdlab.mp.simulate import simulate_pattern

        path = Path(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        struct = Structure.from_str(text, fmt="cif")
        formula = struct.composition.reduced_formula
        ref = simulate_pattern(
            struct, wavelength="CuKa1", two_theta_range=(5.0, 158.0),
            formula=formula, material_id=path.stem,
        )
        self._db.add_reference(ref, citation=cif_citation(text, path.stem, source="CIF"))
        return formula

    def _import_cif(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import structure (CIF)", "", "CIF (*.cif);;All files (*)"
        )
        if not path:
            return
        try:
            formula = self._import_one_cif(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self._refresh()
        self.status.setText(f"Imported {formula} from {Path(path).name}.")

    def _import_cif_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Import folder of CIFs")
        if not folder:
            return
        cifs = sorted(Path(folder).glob("*.cif"))
        if not cifs:
            self.status.setText("No .cif files found in that folder.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        ok, failed = 0, []
        try:
            for p in cifs:
                try:
                    self._import_one_cif(p)
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    failed.append(p.name)
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh()
        msg = f"Imported {ok}/{len(cifs)} CIFs from {Path(folder).name}."
        if failed:
            msg += f"  Failed: {', '.join(failed[:5])}" + (" …" if len(failed) > 5 else "")
        self.status.setText(msg)


class PeakTableDialog(QDialog):
    """Read-only table of detected peaks: 2θ, d, intensity, FWHM, crystallite size.

    d-spacing is Bragg's law at the pattern's wavelength; the Scherrer size uses
    K=0.9 with no instrumental-broadening correction (so it is an upper bound).
    """

    _COLS = ["2θ (°)", "d (Å)", "Intensity", "FWHM (°)", "Fit FWHM (°)",
             "Size (nm)", "Phase"]

    def __init__(self, pattern, peaks, parent=None, fit_kwargs=None):
        super().__init__(parent)
        from PySide6.QtWidgets import (
            QAbstractItemView,
            QHeaderView,
            QTableWidget,
            QTableWidgetItem,
        )

        from xrdlab import config
        from xrdlab.core.fitting import doublet_kwargs

        self._fit_kwargs = doublet_kwargs(pattern) if fit_kwargs is None else fit_kwargs
        self.setWindowTitle(f"Peaks — {pattern.name or 'pattern'}")
        self.resize(660, 460)
        self._phase_col = len(self._COLS) - 1
        self._rows = self._build_rows(pattern, peaks)

        table = QTableWidget(len(self._rows), len(self._COLS))
        table.setHorizontalHeaderLabels(self._COLS)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSortingEnabled(True)
        for r, row in enumerate(self._rows):
            for c, val in enumerate(row):
                if c < self._phase_col and isinstance(val, float):
                    item = QTableWidgetItem()
                    item.setData(Qt.ItemDataRole.DisplayRole, val)  # numeric sort
                else:
                    item = QTableWidgetItem("" if val is None else str(val))
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        table.horizontalHeader().setSectionResizeMode(
            self._phase_col, QHeaderView.ResizeMode.Stretch
        )

        instr = config.get_instrument_fwhm()
        corr = (f"corrected for instrumental FWHM {instr:.3f}° (Settings ▸ Instrument…)"
                if instr else "NOT corrected for instrumental broadening")
        note = QLabel(
            f"{len(self._rows)} peaks · λ = {float(pattern.wavelength):.5f} Å · "
            f"Fit = pseudo-Voigt · Size = Scherrer (K=0.9), {corr}."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666; font-size: 11px;")

        export_btn = QPushButton("Export CSV…")
        export_btn.clicked.connect(self._export_csv)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        bar = QHBoxLayout()
        bar.addWidget(export_btn)
        bar.addStretch(1)
        bar.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(table)
        layout.addWidget(note)
        layout.addLayout(bar)

    def _build_rows(self, pattern, peaks):
        import numpy as np

        from xrdlab import config
        from xrdlab.core.fitting import fit_peak
        from xrdlab.core.processing import scherrer_size
        from xrdlab.ml.labeling import hkl_display, subscript_digits

        wl = float(pattern.wavelength)
        instr = config.get_instrument_fwhm()
        x = pattern.two_theta
        rows = []
        for pk in sorted(peaks, key=lambda p: p.two_theta):
            theta = np.radians(pk.two_theta / 2.0)
            d = wl / (2.0 * np.sin(theta)) if np.sin(theta) > 0 else float("nan")
            fwhm = pk.fwhm if pk.fwhm else float("nan")
            # A pseudo-Voigt fit gives a more accurate width; prefer it for the size.
            i = int(np.searchsorted(x, pk.two_theta))
            i = min(max(i, 0), len(x) - 1)
            fit = fit_peak(x, pattern.intensity, i, **self._fit_kwargs)
            fit_fwhm = fit.fwhm if (fit and fit.r_squared > 0.5) else float("nan")
            width = fit_fwhm if not np.isnan(fit_fwhm) else fwhm
            size = (scherrer_size(width, pk.two_theta, wl, instrument_fwhm_deg=instr)
                    if not np.isnan(width) else float("nan"))
            phase = ""
            if pk.label:
                h = hkl_display(pk.hkl)
                phase = f"{subscript_digits(str(pk.label))} ({h})" if h else \
                    subscript_digits(str(pk.label))
            rows.append([
                round(float(pk.two_theta), 3),
                round(float(d), 4) if not np.isnan(d) else None,
                round(float(pk.intensity), 1),
                round(float(fwhm), 4) if not np.isnan(fwhm) else None,
                round(float(fit_fwhm), 4) if not np.isnan(fit_fwhm) else None,
                round(float(size), 1) if not np.isnan(size) else None,
                phase,
            ])
        return rows

    def _export_csv(self):
        import csv

        path, _ = QFileDialog.getSaveFileName(
            self, "Export peak table", "peaks.csv", "CSV (*.csv);;All files (*)"
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(self._COLS)
                for row in self._rows:
                    w.writerow(["" if v is None else v for v in row])
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.setWindowTitle(f"Peaks — exported to {Path(path).name}")


def _hkl_ints(hkl):
    """Parse pk.hkl (tuple/list of ints, or a string with bars/minus) to ints."""
    if hkl is None:
        return None
    if isinstance(hkl, (list, tuple)):
        try:
            return tuple(int(round(float(v))) for v in hkl)
        except (TypeError, ValueError):
            return None
    if isinstance(hkl, str):
        toks = hkl.split() if " " in hkl else list(hkl)
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
    return None


class LatticeDialog(QDialog):
    """Lattice-parameter readout from assigned peaks (cubic or hexagonal)."""

    def __init__(self, pattern, peaks, parent=None):
        super().__init__(parent)
        import numpy as np
        from PySide6.QtWidgets import (
            QAbstractItemView,
            QHeaderView,
            QTableWidget,
            QTableWidgetItem,
        )

        from xrdlab.ml.labeling import hkl_display, subscript_digits

        self.setWindowTitle(f"Lattice / strain — {pattern.name or 'pattern'}")
        self.resize(560, 440)
        wl = float(pattern.wavelength)

        rows, dims, parsed = [], set(), []
        for pk in sorted(peaks, key=lambda p: p.two_theta):
            hi = _hkl_ints(pk.hkl)
            if not hi:
                continue
            theta = np.radians(pk.two_theta / 2.0)
            if np.sin(theta) <= 0:
                continue
            d = wl / (2.0 * np.sin(theta))
            parsed.append((pk, hi, d))
            dims.add(len(hi))
            rows.append((pk, hi, d))

        cols = ["Phase", "h k l", "2θ (°)", "d (Å)", "a (Å)"]
        table = QTableWidget(len(rows), len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for r, (pk, hi, d) in enumerate(rows):
            phase = subscript_digits(str(pk.label)) if pk.label else ""
            a_cubic = ""
            if len(hi) == 3:
                a_cubic = f"{d * np.sqrt(sum(v * v for v in hi)):.4f}"
            table.setItem(r, 0, QTableWidgetItem(phase))
            table.setItem(r, 1, QTableWidgetItem(hkl_display(pk.hkl)))
            table.setItem(r, 2, QTableWidgetItem(f"{pk.two_theta:.3f}"))
            table.setItem(r, 3, QTableWidgetItem(f"{d:.4f}"))
            table.setItem(r, 4, QTableWidgetItem(a_cubic))
        table.resizeColumnsToContents()
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        self._a_measured = None   # set by _summarize (cubic a or hexagonal a)
        self._a_label = "a"
        note = QLabel(self._summarize(parsed, dims, np))
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.RichText)

        # Strain vs a reference lattice parameter.
        self._a0 = QLineEdit()
        self._a0.setPlaceholderText("e.g. 4.5010")
        self._strain = QLabel("—")
        self._a0.textChanged.connect(self._update_strain)
        strain_form = QFormLayout()
        strain_form.addRow(f"Reference {self._a_label}₀ (Å)", self._a0)
        strain_form.addRow("In-plane/out-of-plane strain", self._strain)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(table)
        layout.addWidget(note)
        if self._a_measured:
            layout.addLayout(strain_form)
        layout.addWidget(buttons)

    def _update_strain(self, text):
        try:
            a0 = float(text)
        except (TypeError, ValueError):
            self._strain.setText("—")
            return
        if a0 <= 0 or not self._a_measured:
            self._strain.setText("—")
            return
        eps = (self._a_measured - a0) / a0 * 100.0
        self._strain.setText(
            f"{eps:+.3f}%  ({self._a_label} = {self._a_measured:.4f} Å vs {a0:.4f} Å)"
        )

    def _summarize(self, parsed, dims, np):
        if not parsed:
            return "No parseable (h k l) among the assigned peaks."
        if dims == {3}:  # cubic
            avals, xs = [], []
            for pk, hi, d in parsed:
                s = sum(v * v for v in hi)
                if s > 0:
                    avals.append(d * np.sqrt(s))
                    theta = np.radians(pk.two_theta / 2.0)
                    xs.append(np.cos(theta) ** 2 / np.sin(theta))  # Nelson-Riley
            avals = np.array(avals)
            self._a_measured = float(avals.mean())
            self._a_label = "a"
            out = (f"<b>Cubic</b> — a = {avals.mean():.4f} ± {avals.std():.4f} Å "
                   f"(from {len(avals)} reflections).")
            if len(avals) >= 2:
                _m, b = np.polyfit(np.array(xs), avals, 1)
                out += f"<br>Nelson-Riley extrapolated a₀ = {b:.4f} Å."
            out += ("<br><i>Spread across reflections reflects strain / peak-position "
                    "error.</i>")
            return out
        if dims == {4}:  # hexagonal (h k i l)
            A, y = [], []
            for pk, hi, d in parsed:
                h, k, _i, ll = hi
                A.append([(4.0 / 3.0) * (h * h + h * k + k * k), ll * ll])
                y.append(1.0 / d ** 2)
            A = np.array(A)
            y = np.array(y)
            try:
                (u, w), *_ = np.linalg.lstsq(A, y, rcond=None)
                a = 1.0 / np.sqrt(u) if u > 0 else float("nan")
                c = 1.0 / np.sqrt(w) if w > 0 else float("nan")
                if np.isfinite(c):  # c is the epitaxial out-of-plane parameter
                    self._a_measured = float(c)
                    self._a_label = "c"
                return (f"<b>Hexagonal</b> — a = {a:.4f} Å, c = {c:.4f} Å "
                        f"(c/a = {c / a:.4f}) from {len(parsed)} reflections."
                        "<br><i>Needs reflections with differing l for a good c.</i>")
            except Exception:  # noqa: BLE001
                return "Could not solve for hexagonal a, c (need more varied hkl)."
        return ("Mixed 3- and 4-index reflections — showing d-spacings only. "
                "Assign a single phase's reflections for a lattice fit.")


class RSMViewerDialog(QDialog):
    """Quick contour view of a reciprocal-space map from a CSV.

    Accepts a 3-column ``x, y, intensity`` list (auto-pivoted to a grid) or a plain
    numeric matrix (shown against row/column index).
    """

    def __init__(self, path, parent=None):
        super().__init__(parent)
        import numpy as np

        from xrdlab.ui.widgets import MplCanvas

        self.setWindowTitle(f"Reciprocal-space map — {Path(path).name}")
        self.resize(680, 560)
        raw = np.atleast_2d(
            np.genfromtxt(path, delimiter=None if _whitespace(path) else ",")
        )

        canvas = MplCanvas(width=6.4, height=5.0)
        ax = canvas.figure.add_subplot(111)
        if raw.shape[1] == 3:
            x, y, z = raw[:, 0], raw[:, 1], raw[:, 2]
            xu, yu = np.unique(x), np.unique(y)
            grid = np.full((yu.size, xu.size), np.nan)
            xi = {v: i for i, v in enumerate(xu)}
            yi = {v: i for i, v in enumerate(yu)}
            for xv, yv, zv in zip(x, y, z):
                grid[yi[yv], xi[xv]] = zv
            zpos = np.nanmax(grid) or 1.0
            cf = ax.contourf(xu, yu, np.log10(np.clip(grid, zpos * 1e-4, None)), 40,
                             cmap="viridis")
            canvas.figure.colorbar(cf, ax=ax, label="log₁₀ intensity")
            ax.set_xlabel("axis 1")
            ax.set_ylabel("axis 2")
        else:
            zpos = np.nanmax(raw) or 1.0
            im = ax.imshow(np.log10(np.clip(raw, zpos * 1e-4, None)), origin="lower",
                           aspect="auto", cmap="viridis")
            canvas.figure.colorbar(im, ax=ax, label="log₁₀ intensity")
        ax.set_title("Reciprocal-space map")
        canvas.figure.tight_layout()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(canvas)
        layout.addWidget(buttons)


def _whitespace(path) -> bool:
    """True if the file looks whitespace-delimited (no commas on the first data line)."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.strip() and not line.lstrip().startswith("#"):
                    return "," not in line
    except OSError:
        pass
    return False


class RockingCurveDialog(QDialog):
    """Plot a scan's dominant peak with its pseudo-Voigt fit and FWHM readout.

    For an ω (rocking) scan the FWHM — reported in ° and arcsec — is the standard
    measure of epitaxial mosaic / crystalline quality.
    """

    def __init__(self, pattern, parent=None):
        super().__init__(parent)
        import numpy as np

        from xrdlab.core.fitting import doublet_kwargs, fit_peak
        from xrdlab.core.processing import peak_fwhm
        from xrdlab.ui.widgets import MplCanvas

        self.setWindowTitle(f"Rocking curve — {pattern.name or 'scan'}")
        self.resize(620, 520)
        x = np.asarray(pattern.two_theta, dtype=float)
        y = np.asarray(pattern.intensity, dtype=float)
        i = int(np.argmax(y))
        data_fwhm, xl, xr, half = peak_fwhm(x, y, i)
        fit = fit_peak(x, y, i, **doublet_kwargs(pattern))

        span = max(1.0, 8.0 * (fit.fwhm if fit else (data_fwhm if data_fwhm == data_fwhm else 0.5)))
        sel = np.abs(x - x[i]) <= span
        canvas = MplCanvas(width=6.0, height=4.4)
        ax = canvas.figure.add_subplot(111)
        ax.plot(x[sel], y[sel], ".", ms=3, color="#1f77b4", label="data")
        if fit and fit.r_squared > 0.5:
            xf = np.linspace(x[sel].min(), x[sel].max(), 500)
            ax.plot(xf, fit.model(xf), "-", lw=1.4, color="#d62728",
                    label="pseudo-Voigt fit" + (" (Kα1+Kα2)" if fit.ka2_ratio else ""))
            lvl = fit.background + fit.amplitude / 2.0
            ax.hlines(lvl, fit.center - fit.fwhm / 2, fit.center + fit.fwhm / 2,
                      color="#444", lw=1.0)
            ax.annotate(f"FWHM {fit.fwhm:.4f}° = {fit.fwhm*3600:.0f}\"",
                        xy=(fit.center, lvl), xytext=(0, 8),
                        textcoords="offset points", ha="center", fontsize=9)
        elif data_fwhm == data_fwhm:
            ax.hlines(half, xl, xr, color="#444", lw=1.0)
            ax.annotate(f"FWHM {data_fwhm:.4f}° = {data_fwhm*3600:.0f}\"",
                        xy=((xl + xr) / 2, half), xytext=(0, 8),
                        textcoords="offset points", ha="center", fontsize=9)
        ax.set_xlabel("angle (°)")
        ax.set_ylabel("intensity")
        ax.legend(loc="upper right", fontsize=8)
        canvas.figure.tight_layout()

        lines = [f"Peak position: {x[i]:.4f}°"]
        if data_fwhm == data_fwhm:
            lines.append(f"FWHM (data): {data_fwhm:.4f}° = {data_fwhm*3600:.0f} arcsec")
        if fit and fit.r_squared > 0.5:
            lines.append(f"FWHM (fit): {fit.fwhm:.4f}° = {fit.fwhm*3600:.0f} arcsec"
                         f"   (η={fit.eta:.2f}, R²={fit.r_squared:.4f})")
        note = QLabel("   ·   ".join(lines))
        note.setWordWrap(True)
        note.setStyleSheet("color:#444; font-size:11px;")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(canvas)
        layout.addWidget(note)
        layout.addWidget(buttons)
