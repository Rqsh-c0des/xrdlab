"""Build literature cross-references for identified peaks.

Citations come from **openly-licensed provenance** — primarily Materials Project
(CC-BY 4.0), which links each structure to its source publication (BibTeX/DOI) and
ICSD id. Nothing here scrapes paywalled journals or textbooks; it formats the
bibliographic metadata that accompanies the reference structures.
"""

from __future__ import annotations

import html
import re

import numpy as np

__all__ = [
    "mp_url",
    "record_url",
    "extract_dois",
    "enrich_citation",
    "build_report_html",
    "build_bibtex",
]

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?:year\s*=\s*[{\"]?\s*)((?:19|20)\d{2})")


def mp_url(material_id: str) -> str:
    """Public Materials Project page for a material id."""
    if not material_id:
        return ""
    return f"https://next-gen.materialsproject.org/materials/{material_id}"


def record_url(material_id: str) -> tuple[str, str]:
    """Return (url, source-label) for a phase's database record."""
    if not material_id:
        return ("", "")
    if material_id.startswith("COD-"):
        from xrdlab.cod.client import cod_url

        return (cod_url(material_id), "COD")
    if material_id.startswith("AMCSD-"):
        from xrdlab.amcsd.client import amcsd_url

        return (amcsd_url(material_id), "AMCSD")
    if material_id.startswith("mp-"):
        return (mp_url(material_id), "Materials Project")
    return ("", material_id or "")


def enrich_citation(citation: dict | None, mailto: str | None = None) -> dict | None:
    """Attach a Crossref-formatted string to ``citation`` (best-effort, cached)."""
    if not citation:
        return citation
    dois = extract_dois(citation.get("references", []))
    if not dois and citation.get("doi"):
        dois = [citation["doi"]]
    for doi in dois:
        from xrdlab.crossref import format_doi

        formatted = format_doi(doi, mailto)
        if formatted:
            citation["formatted"] = formatted
            break
    return citation


def extract_dois(references: list[str]) -> list[str]:
    """Pull unique DOIs out of a list of BibTeX / reference strings."""
    dois: list[str] = []
    for ref in references or []:
        for m in _DOI_RE.findall(ref):
            doi = m.rstrip(".,;)}")
            if doi not in dois:
                dois.append(doi)
    return dois


def _bragg_d(two_theta: float, wavelength: float) -> float:
    theta = np.radians(two_theta / 2.0)
    s = np.sin(theta)
    return float(wavelength / (2.0 * s)) if s > 0 else float("nan")


def _phase_meta(entry: dict) -> dict:
    cit = (entry or {}).get("citation") or {}
    refs = cit.get("references") or []
    dois = extract_dois(refs)
    if not dois and cit.get("doi"):
        dois = [cit["doi"]]
    return {
        "material_id": (entry or {}).get("material_id", ""),
        "crystal_system": (entry or {}).get("crystal_system", ""),
        "space_group": (entry or {}).get("space_group", ""),
        "authors": cit.get("authors") or [],
        "references": refs,
        "dois": dois,
        "database_IDs": cit.get("database_IDs") or {},
        "formatted": cit.get("formatted", ""),
        "source": cit.get("source", ""),
        "title": cit.get("title", ""),
        "journal": cit.get("journal", ""),
        "year": cit.get("year", ""),
    }


def build_report_html(
    pattern_name: str,
    wavelength: float,
    labeled_peaks: list,
    phase_db,
) -> str:
    """HTML report cross-referencing identified peaks to their source phases.

    ``labeled_peaks`` are PeakLabel objects (``label`` = formula, ``hkl``,
    ``two_theta``, ``intensity``); ``phase_db`` supplies each phase's stored
    citation.
    """
    from xrdlab.ml.labeling import hkl_display

    identified = [p for p in labeled_peaks if p.label]
    by_phase: dict[str, list] = {}
    for pk in identified:
        by_phase.setdefault(pk.label, []).append(pk)

    parts = [
        "<style>body{font-family:sans-serif;} h2{margin-bottom:2px;} "
        "table{border-collapse:collapse;margin:4px 0 12px 0;} "
        "td,th{border:1px solid #8884;padding:2px 8px;text-align:right;} "
        "th{text-align:center;} .phase{margin-top:14px;} "
        ".muted{color:#888;} a{color:#3b82f6;}</style>",
        f"<h2>{html.escape(pattern_name or 'Sample')}</h2>",
        f"<p class='muted'>{len(identified)} of {len(labeled_peaks)} detected peaks "
        f"identified &middot; λ = {wavelength:.5g} Å</p>",
    ]

    if not by_phase:
        parts.append(
            "<p>No peaks identified yet. Add the sample's phases under "
            "<i>Settings ▸ Phase database…</i> (or overlay a Materials Project "
            "reference), then enable <i>Identify from phase database</i>.</p>"
        )

    for formula in sorted(by_phase):
        entry = phase_db._data.get(formula, {})
        meta = _phase_meta(entry)
        parts.append(f"<div class='phase'><h3>{html.escape(formula)}</h3>")
        sym = " · ".join(s for s in (meta["crystal_system"], meta["space_group"]) if s)
        if sym:
            parts.append(f"<div class='muted'>Crystal system: {html.escape(sym)}</div>")

        # Preferred: a Crossref-formatted one-liner; else assemble from fields.
        if meta["formatted"]:
            parts.append(f"<div>{html.escape(meta['formatted'])}</div>")
        else:
            if meta["authors"]:
                parts.append(f"<div class='muted'>{html.escape(', '.join(meta['authors'][:6]))}</div>")
            bits = [b for b in (meta["title"], meta["journal"], str(meta["year"])) if b]
            if bits:
                parts.append(f"<div>{html.escape('. '.join(bits))}</div>")

        links = []
        rec_url, rec_label = record_url(meta["material_id"])
        if rec_url:
            links.append(
                f"<a href='{rec_url}'>{html.escape(meta['material_id'])} ({rec_label})</a>"
            )
        for doi in meta["dois"]:
            links.append(f"<a href='https://doi.org/{doi}'>doi:{html.escape(doi)}</a>")
        for db, ids in meta["database_IDs"].items():
            if ids and db != "COD":
                links.append(f"{html.escape(str(db))}: {html.escape(', '.join(map(str, ids)))}")
        parts.append(
            "<div>" + " &middot; ".join(links) + "</div>" if links else
            "<div class='muted'>No stored citation — re-add this phase to fetch its "
            "provenance.</div>"
        )

        rows = ["<table><tr><th>2θ (°)</th><th>d (Å)</th><th>hkl</th><th>Intensity</th></tr>"]
        for pk in sorted(by_phase[formula], key=lambda p: p.two_theta):
            rows.append(
                f"<tr><td>{pk.two_theta:.3f}</td><td>{_bragg_d(pk.two_theta, wavelength):.4f}</td>"
                f"<td>{html.escape(hkl_display(pk.hkl))}</td><td>{pk.intensity:,.0f}</td></tr>"
            )
        rows.append("</table></div>")
        parts.append("".join(rows))

    unidentified = [p for p in labeled_peaks if not p.label]
    if unidentified:
        angles = ", ".join(f"{p.two_theta:.2f}°" for p in sorted(unidentified, key=lambda p: p.two_theta))
        parts.append(f"<p class='muted'><b>Unidentified peaks:</b> {angles}</p>")

    parts.append(
        "<hr><p class='muted' style='font-size:0.85em'>Citations from Materials "
        "Project provenance (CC-BY 4.0). Verify each reference before citing; this "
        "is provenance for the reference <i>structure</i>, not a claim about your "
        "specific sample.</p>"
    )
    return "".join(parts)


def build_bibtex(labeled_peaks: list, phase_db) -> str:
    """Concatenate stored BibTeX for every phase referenced by the peaks."""
    formulas = sorted({p.label for p in labeled_peaks if p.label})
    blocks: list[str] = []
    for formula in formulas:
        entry = phase_db._data.get(formula, {})
        meta = _phase_meta(entry)
        native = [r.strip() for r in meta["references"] if r.strip().startswith("@")]
        if native:
            blocks.extend(native)
            continue
        # Synthesize an entry from structured fields (COD) or the DB record (MP).
        mid = meta["material_id"] or formula
        doi = meta["dois"][0] if meta["dois"] else ""
        url, source = record_url(mid)
        fields = [f"  title = {{{meta['title'] or formula + ' crystal structure'}}}"]
        if meta["authors"]:
            fields.append(f"  author = {{{' and '.join(meta['authors'])}}}")
        if meta["journal"]:
            fields.append(f"  journal = {{{meta['journal']}}}")
        if meta["year"]:
            fields.append(f"  year = {{{meta['year']}}}")
        fields.append(f"  note = {{Structure: {source} {mid}}}")
        if url:
            fields.append(f"  url = {{{url}}}")
        if doi:
            fields.append(f"  doi = {{{doi}}}")
        kind = "article" if meta["journal"] else "misc"
        key = f"{formula}_{str(mid).replace('-', '')}"
        blocks.append(f"@{kind}{{{key},\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(blocks)
