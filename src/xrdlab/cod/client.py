"""Fetch reference structures (and citations) from the Crystallography Open Database.

COD is an open database of crystal structures (CIF files), each carrying its source
publication. We search by element set, download the CIF, build a pymatgen
``Structure``, and simulate a reference pattern — mirroring the Materials Project
path so both feed the same phase database and Citations tab.
"""

from __future__ import annotations

import re

from xrdlab.mp.simulate import ReferencePattern, simulate_pattern

__all__ = ["CODClient", "CODError", "cod_url"]

_SEARCH = "https://www.crystallography.net/cod/result"
_CIF = "https://www.crystallography.net/cod/{codid}.cif"
_UA = {"User-Agent": "XRDLab/0.1"}


class CODError(RuntimeError):
    """Raised when a COD search or download fails."""


def cod_url(codid: str) -> str:
    """Public COD entry page for a numeric COD id."""
    codid = str(codid).replace("COD-", "").strip()
    return f"https://www.crystallography.net/cod/{codid}.html" if codid else ""


def _clean_cod_formula(formula: str) -> str:
    """COD formulas look like ``- N1 Sc1 -``; strip the framing dashes."""
    return re.sub(r"[-]", " ", formula or "").strip()


def _authors(row: dict) -> list[str]:
    raw = row.get("authors") or row.get("author") or ""
    if isinstance(raw, list):
        return [str(a) for a in raw]
    # COD packs authors as a single ';'-separated string.
    return [a.strip() for a in re.split(r"[;]", str(raw)) if a.strip()]


class CODClient:
    """Minimal COD search + CIF client."""

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout

    def search(self, formula: str) -> list[dict]:
        """Return COD entries whose reduced formula matches ``formula``."""
        import requests
        from pymatgen.core import Composition

        comp = Composition(formula)
        elements = [str(e) for e in comp.elements]
        params = {"format": "json", "nel": len(elements)}
        for i, el in enumerate(elements[:8], start=1):
            params[f"el{i}"] = el
        try:
            resp = requests.get(_SEARCH, params=params, headers=_UA, timeout=self.timeout)
            resp.raise_for_status()
            rows = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise CODError(f"COD search failed for {formula!r}: {exc}") from exc

        if not isinstance(rows, list):
            return []
        target = comp.reduced_formula
        matches = []
        for row in rows:
            raw = row.get("formula") or row.get("cellformula") or ""
            try:
                if Composition(_clean_cod_formula(raw)).reduced_formula == target:
                    matches.append(row)
            except Exception:  # noqa: BLE001 — skip unparseable formulae
                continue
        return matches or rows

    def get_structure(self, codid: str):
        """Download and parse the CIF for a COD id into a pymatgen ``Structure``."""
        import requests
        from pymatgen.core import Structure

        codid = str(codid).replace("COD-", "").strip()
        try:
            resp = requests.get(_CIF.format(codid=codid), headers=_UA, timeout=self.timeout)
            resp.raise_for_status()
            return Structure.from_str(resp.text, fmt="cif")
        except Exception as exc:  # noqa: BLE001
            raise CODError(f"COD CIF {codid} could not be read: {exc}") from exc

    def formula_to_reference(
        self,
        formula: str,
        wavelength: str | float = "CuKa1",
        two_theta_range: tuple[float, float] = (5.0, 158.0),
    ) -> tuple[ReferencePattern, dict]:
        """Return a (ReferencePattern, citation) pair for ``formula`` from COD."""
        from pymatgen.core import Composition

        rows = self.search(formula)
        if not rows:
            raise CODError(f"No COD entry for {formula!r}.")
        row = rows[0]
        codid = str(row.get("file") or row.get("cod_id") or "").strip()
        structure = self.get_structure(codid)
        ref = simulate_pattern(
            structure,
            wavelength=wavelength,
            two_theta_range=two_theta_range,
            formula=Composition(formula).reduced_formula,
            material_id=f"COD-{codid}",
        )
        citation = self._citation(row, codid)
        return ref, citation

    def reference_from_row(
        self,
        row: dict,
        wavelength: str | float = "CuKa1",
        two_theta_range: tuple[float, float] = (5.0, 158.0),
    ) -> tuple[ReferencePattern, dict]:
        """Build a (reference, citation) for a specific COD search row (polymorph)."""
        from pymatgen.core import Composition

        codid = str(row.get("file") or "").strip()
        structure = self.get_structure(codid)
        raw = row.get("formula") or row.get("cellformula") or ""
        try:
            formula = Composition(_clean_cod_formula(raw)).reduced_formula
        except Exception:  # noqa: BLE001
            formula = raw
        ref = simulate_pattern(
            structure, wavelength=wavelength, two_theta_range=two_theta_range,
            formula=formula, material_id=f"COD-{codid}",
        )
        return ref, self._citation(row, codid)

    @staticmethod
    def _citation(row: dict, codid: str) -> dict:
        return {
            "source": "COD",
            "material_id": f"COD-{codid}",
            "authors": _authors(row),
            "title": row.get("title", ""),
            "journal": row.get("journal", ""),
            "year": str(row.get("year", "") or ""),
            "volume": str(row.get("volume", "") or ""),
            "chemname": row.get("chemname", "") or "",
            "doi": row.get("doi", "") or "",
            "references": [],
            "database_IDs": {"COD": [codid]},
        }
