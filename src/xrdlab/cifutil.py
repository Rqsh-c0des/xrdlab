"""Shared helpers for reading citation metadata out of CIF text."""

from __future__ import annotations

import re

__all__ = ["cif_citation"]


def _one(text: str, tag: str) -> str:
    m = re.search(rf"{tag}\s+['\"]?([^'\"\n]+?)['\"]?\s*$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def cif_citation(text: str, source_id: str, source: str = "CIF") -> dict:
    """Best-effort citation dict from a CIF's ``_journal_*`` / ``_publ_*`` tags."""
    authors = re.findall(r"_publ_author_name\s+['\"]?([^'\"\n]+)", text)
    return {
        "source": source,
        "material_id": source_id,
        "authors": [a.strip().strip("'\"") for a in authors][:8],
        "title": _one(text, r"_publ_section_title"),
        "journal": _one(text, r"_journal_name_full"),
        "year": _one(text, r"_journal_year"),
        "doi": _one(text, r"_journal_paper_doi"),
        "references": [],
        "database_IDs": {},
    }
