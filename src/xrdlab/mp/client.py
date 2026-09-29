"""Materials Project client: formula -> crystal structure, with local caching.

Follows the MP large-download guidance: use the official ``mp-api`` client,
request only the fields we need, and cache results locally so repeat lookups are
offline. Our queries are small and targeted (one formula at a time), so this stays
well within rate limits.

The API key is read from the ``MP_API_KEY`` environment variable (or a ``.env``
file). It is never hard-coded.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from xrdlab import config
from xrdlab.mp.simulate import ReferencePattern, simulate_pattern

__all__ = ["MPClient", "MPClientError"]

_DEFAULT_CACHE = Path.home() / ".xrdlab_cache" / "structures"


class MPClientError(RuntimeError):
    """Raised for missing API keys or failed Materials Project lookups."""


def _load_api_key(explicit: str | None) -> str:
    key = config.resolve_api_key(explicit)
    if not key:
        raise MPClientError(
            "No Materials Project API key. Set one in the app "
            "(Materials Project panel ▸ Set API key…), or via MP_API_KEY in your "
            "environment / a .env file. Get or rotate a key at "
            "https://next-gen.materialsproject.org/api."
        )
    return key


class MPClient:
    """Fetch and cache Materials Project structures for reference overlays."""

    #: Only the fields we actually use — keeps payloads small per MP guidance.
    FIELDS = ["material_id", "formula_pretty", "structure", "symmetry",
              "energy_above_hull"]

    def __init__(self, api_key: str | None = None, cache_dir: str | os.PathLike | None = None):
        self._api_key = _load_api_key(api_key)
        self.cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- structure retrieval -------------------------------------------------
    def _cache_path(self, formula: str) -> Path:
        safe = formula.replace(" ", "").replace("/", "_")
        return self.cache_dir / f"{safe}.json"

    def get_structure(self, formula: str):
        """Return the most stable pymatgen ``Structure`` for ``formula``.

        Cached to ``cache_dir``; a second call for the same formula works offline.
        """
        from pymatgen.core import Structure

        cache = self._cache_path(formula)
        if cache.exists():
            payload = json.loads(cache.read_text())
            return Structure.from_dict(payload["structure"])

        doc = self._query_most_stable(formula)
        structure = doc["structure"]
        cache.write_text(
            json.dumps(
                {
                    "formula": formula,
                    "material_id": doc["material_id"],
                    "structure": structure.as_dict(),
                }
            )
        )
        return structure

    def search_candidates(self, formula: str) -> list:
        """Return all MP summary docs for ``formula`` (polymorphs), most stable first."""
        from mp_api.client import MPRester

        with MPRester(self._api_key) as mpr:
            docs = mpr.materials.summary.search(formula=formula, fields=self.FIELDS)
        docs.sort(key=lambda d: getattr(d, "energy_above_hull", 0.0) or 0.0)
        return docs

    def _query_most_stable(self, formula: str) -> dict:
        from mp_api.client import MPRester

        with MPRester(self._api_key) as mpr:
            docs = mpr.materials.summary.search(formula=formula, fields=self.FIELDS)
        if not docs:
            raise MPClientError(f"No Materials Project entry for formula {formula!r}.")
        # Prefer the ground state (lowest energy above hull).
        docs.sort(key=lambda d: getattr(d, "energy_above_hull", 0.0) or 0.0)
        best = docs[0]
        return {
            "structure": best.structure,
            "material_id": str(best.material_id),
            "formula_pretty": getattr(best, "formula_pretty", formula),
        }

    # -- provenance / citations ---------------------------------------------
    def get_provenance(self, material_id: str) -> dict:
        """Best-effort literature provenance for a material id.

        Returns ``{references, authors, database_IDs, material_id}`` from Materials
        Project (CC-BY 4.0). Any failure yields ``{}`` so callers can proceed
        without a citation.
        """
        if not material_id:
            return {}
        try:
            from mp_api.client import MPRester

            with MPRester(self._api_key) as mpr:
                doc = mpr.materials.provenance.get_data_by_id(material_id)
        except Exception:  # noqa: BLE001 — provenance is optional
            return {}

        def _get(obj, name, default):
            return getattr(obj, name, None) or default

        authors_raw = _get(doc, "authors", [])
        authors = [
            a.get("name") if isinstance(a, dict) else str(a) for a in authors_raw
        ]
        db_ids_raw = _get(doc, "database_IDs", {}) or {}
        try:
            db_ids = {str(k): list(v) for k, v in dict(db_ids_raw).items()}
        except Exception:  # noqa: BLE001
            db_ids = {}
        return {
            "references": list(_get(doc, "references", [])),
            "authors": authors,
            "database_IDs": db_ids,
            "material_id": material_id,
        }

    # -- convenience ---------------------------------------------------------
    def formula_to_reference(
        self,
        formula: str,
        wavelength: str | float = "CuKa1",
        two_theta_range: tuple[float, float] = (10.0, 120.0),
    ) -> ReferencePattern:
        """Fetch the structure and simulate its reference pattern in one call."""
        structure = self.get_structure(formula)
        mid = ""
        cache = self._cache_path(formula)
        if cache.exists():
            mid = json.loads(cache.read_text()).get("material_id", "")
        return simulate_pattern(
            structure,
            wavelength=wavelength,
            two_theta_range=two_theta_range,
            formula=formula,
            material_id=mid,
        )
