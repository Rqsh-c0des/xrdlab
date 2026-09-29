"""A local, growable phase database for peak identification.

Each phase is stored as a set of **d-spacings** (Angstrom) with relative
intensities and (h k l). Because d-spacings are wavelength-independent, a phase
added once can identify peaks in *any* future dataset regardless of the radiation
used — the peak's 2θ is converted to d via that dataset's own wavelength before
matching.

The database is a JSON file at ``~/.xrdlab/phase_db.json`` and grows automatically
whenever a Materials Project reference is overlaid, or explicitly via the phase
database dialog.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from xrdlab.ml.labeling import PeakLabel, format_hkl

__all__ = ["PhaseDatabase", "PhaseCandidate", "DEFAULT_SEED_PHASES"]

_DB_PATH = Path.home() / ".xrdlab" / "phase_db.json"

# A useful starting set for nitride-semiconductor / common-substrate work.
DEFAULT_SEED_PHASES = ["GaN", "ScN", "AlN", "InN", "Si", "Al2O3", "SiC", "GaAs"]


@dataclass
class PhaseCandidate:
    """A possible phase assignment for a peak."""

    formula: str
    hkl: str | None
    d: float
    two_theta: float
    delta_deg: float
    intensity: float
    material_id: str = ""


def _bragg_two_theta(d: float, wavelength: float) -> float | None:
    """2θ (deg) of a d-spacing at ``wavelength``; None if physically unreachable."""
    ratio = wavelength / (2.0 * d)
    if not -1.0 <= ratio <= 1.0:
        return None
    return float(np.degrees(2.0 * np.arcsin(ratio)))


class PhaseDatabase:
    """Load/save and query a local set of reference phases (by d-spacing)."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else _DB_PATH
        self._data: dict = self._load()

    # -- persistence ---------------------------------------------------------
    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=1), encoding="utf-8")

    # -- mutation ------------------------------------------------------------
    def formulas(self) -> list[str]:
        return sorted(self._data.keys())

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, formula: str) -> bool:
        return formula in self._data

    def remove(self, formula: str) -> None:
        self._data.pop(formula, None)
        self._save()

    def clear(self) -> None:
        self._data = {}
        self._save()

    def add_reference(self, ref, citation: dict | None = None) -> None:
        """Add/replace a phase from a :class:`ReferencePattern` (needs d-spacings).

        ``citation`` (from :meth:`MPClient.get_provenance`) is stored for the
        Citations tab; if omitted, any existing citation for the phase is kept.
        """
        if ref.d_spacings is None or not ref.formula:
            return
        reflections = []
        hkls = list(ref.hkls) if ref.hkls else [None] * len(ref.d_spacings)
        for d, inten, hk in zip(ref.d_spacings, ref.intensity, hkls):
            if not np.isfinite(d):
                continue
            reflections.append([round(float(d), 5), round(float(inten), 3), _hkl_of(hk)])
        entry = {
            "material_id": ref.material_id,
            "reflections": reflections,
            "crystal_system": getattr(ref, "crystal_system", ""),
            "space_group": getattr(ref, "space_group", ""),
        }
        if citation:
            entry["citation"] = citation
        elif "citation" in self._data.get(ref.formula, {}):
            entry["citation"] = self._data[ref.formula]["citation"]
        self._data[ref.formula] = entry
        self._save()

    def symmetry_of(self, formula: str) -> tuple[str, str]:
        """Return (crystal_system, space_group) stored for ``formula``."""
        e = self._data.get(formula, {})
        return e.get("crystal_system", ""), e.get("space_group", "")

    def add_formula(self, formula: str, client, wavelength: str = "CuKa1") -> int:
        """Fetch ``formula`` from Materials Project (with provenance) and store it.

        Returns the number of reflections stored.
        """
        ref = client.formula_to_reference(
            formula, wavelength=wavelength, two_theta_range=(5.0, 158.0)
        )
        citation = client.get_provenance(ref.material_id)
        self.add_reference(ref, citation=citation)
        return len(ref.d_spacings) if ref.d_spacings is not None else 0

    def citation_of(self, formula: str) -> dict | None:
        return self._data.get(formula, {}).get("citation")

    def reflection_table(
        self, formula: str, wavelength: float = 1.5405980
    ) -> list[tuple]:
        """Return ``(hkl, d, two_theta, intensity)`` rows for a phase, 2θ-sorted.

        2θ is computed at ``wavelength`` (default Cu Kα1) from the stored,
        wavelength-independent d-spacings — the reference-angle table for a phase.
        """
        entry = self._data.get(formula, {})
        rows = []
        for d, inten, hkl in entry.get("reflections", []):
            ratio = wavelength / (2.0 * d)
            if -1.0 <= ratio <= 1.0:
                tt = float(np.degrees(2.0 * np.arcsin(ratio)))
                rows.append((hkl, float(d), tt, float(inten)))
        rows.sort(key=lambda r: r[2])
        return rows

    # -- identification ------------------------------------------------------
    def identify(
        self, two_theta: float, wavelength: float, tol_deg: float = 0.5
    ) -> list[PhaseCandidate]:
        """Candidate phases whose reflection is within ``tol_deg`` of ``two_theta``.

        Sorted best-first by angular closeness, then reflection intensity.
        """
        out: list[PhaseCandidate] = []
        for formula, entry in self._data.items():
            for d, inten, hkl in entry["reflections"]:
                tt = _bragg_two_theta(d, wavelength)
                if tt is None:
                    continue
                delta = abs(tt - two_theta)
                if delta <= tol_deg:
                    out.append(
                        PhaseCandidate(
                            formula=formula,
                            hkl=hkl or None,
                            d=d, two_theta=tt, delta_deg=delta, intensity=inten,
                            material_id=entry.get("material_id", ""),
                        )
                    )
        out.sort(key=lambda c: (c.delta_deg, -c.intensity))
        return out

    def identify_peaks(
        self, peaks: list[PeakLabel], wavelength: float, tol_deg: float = 0.5
    ) -> dict[int, list[PhaseCandidate]]:
        """Return {peak index: ranked candidates} and label each peak in place.

        Only peaks without an existing label are assigned; a peak that already
        carries a label (e.g. from an overlaid reference) is left untouched but
        still gets its candidate list returned.
        """
        result: dict[int, list[PhaseCandidate]] = {}
        for i, pk in enumerate(peaks):
            cands = self.identify(pk.two_theta, wavelength, tol_deg)
            result[i] = cands
            if cands and not pk.label:
                best = cands[0]
                pk.label = best.formula
                pk.hkl = best.hkl
                pk.confidence = max(0.0, 1.0 - best.delta_deg / tol_deg) if tol_deg else 1.0
        return result


def _hkl_of(hk) -> str:
    """Serialise a pymatgen hkl entry to a compact string for JSON storage."""
    from xrdlab.ml.labeling import _extract_hkl

    tup = _extract_hkl(hk)
    return format_hkl(tup) if tup else ""
