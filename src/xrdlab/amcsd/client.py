"""Fetch reference structures from the American Mineralogist Crystal Structure DB.

AMCSD (https://rruff.geo.arizona.edu/AMS/) is an open database of published mineral
structures. It has no JSON API — searches return HTML and CIFs download via
``download.php`` — so we search by element set, scrape the CIF ids, download each
candidate, and keep the one whose composition matches. Mirrors the COD path so both
feed the same phase database and Citations tab.
"""

from __future__ import annotations

import re

from xrdlab.cifutil import cif_citation
from xrdlab.mp.simulate import ReferencePattern, simulate_pattern

__all__ = ["AMCSDClient", "AMCSDError", "parse_cif_ids", "amcsd_url"]

_SEARCH = "https://rruff.geo.arizona.edu/AMS/result.php"
_DOWNLOAD = "https://rruff.geo.arizona.edu/AMS/download.php"
_UA = {"User-Agent": "XRDLab/0.1"}


class AMCSDError(RuntimeError):
    """Raised when an AMCSD search or download fails."""


def amcsd_url(amcsd_id: str) -> str:
    """Best-effort link to an AMCSD record's CIF."""
    amcsd_id = str(amcsd_id).replace("AMCSD-", "").strip()
    return f"{_DOWNLOAD}?id={amcsd_id}.cif&down=cif" if amcsd_id else ""


def parse_cif_ids(html: str) -> list[str]:
    """Extract unique AMCSD CIF ids from a result page (``download.php?id=NNN.cif``)."""
    ids = re.findall(r"download\.php\?id=(\d+)\.cif", html)
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


class AMCSDClient:
    """Minimal AMCSD search + CIF client."""

    def __init__(self, timeout: float = 25.0):
        self.timeout = timeout

    def _search_ids(self, formula: str) -> list[str]:
        import requests
        from pymatgen.core import Composition

        elements = " ".join(str(e) for e in Composition(formula).elements)
        try:
            resp = requests.get(
                _SEARCH, params={"chemistry": elements}, headers=_UA, timeout=self.timeout
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise AMCSDError(f"AMCSD search failed for {formula!r}: {exc}") from exc
        return parse_cif_ids(resp.text)

    def _cif(self, cif_id: str) -> str:
        import requests

        resp = requests.get(
            _DOWNLOAD, params={"id": f"{cif_id}.cif", "down": "cif"},
            headers=_UA, timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.text

    def formula_to_reference(
        self,
        formula: str,
        wavelength: str | float = "CuKa1",
        two_theta_range: tuple[float, float] = (5.0, 158.0),
    ) -> tuple[ReferencePattern, dict]:
        """Return a (ReferencePattern, citation) whose composition matches ``formula``."""
        from pymatgen.core import Composition, Structure

        target = Composition(formula).reduced_formula
        ids = self._search_ids(formula)
        if not ids:
            raise AMCSDError(f"No AMCSD entry for {formula!r}.")
        for cif_id in ids[:12]:  # cap downloads while hunting for a composition match
            try:
                text = self._cif(cif_id)
                structure = Structure.from_str(text, fmt="cif")
                if structure.composition.reduced_formula != target:
                    continue
                ref = simulate_pattern(
                    structure, wavelength=wavelength, two_theta_range=two_theta_range,
                    formula=target, material_id=f"AMCSD-{cif_id}",
                )
                return ref, cif_citation(text, f"AMCSD-{cif_id}", source="AMCSD")
            except Exception:  # noqa: BLE001 — skip unparseable candidates
                continue
        raise AMCSDError(f"No AMCSD entry matched composition {target}.")
