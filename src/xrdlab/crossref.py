"""Format DOIs into human-readable citations via the Crossref REST API.

Crossref is free and open (no key). We use the "polite pool" by sending a
``User-Agent`` with an optional contact email, cache results locally, and fail
soft (return ``""``) so the app works offline.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

__all__ = ["format_work", "fetch_work", "format_doi"]

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    """Strip HTML tags (Crossref titles often carry <sub>/<i>…) and tidy spaces."""
    return re.sub(r"\s+", " ", _TAG_RE.sub("", text or "")).strip()

_CACHE = Path.home() / ".xrdlab" / "crossref_cache.json"
_API = "https://api.crossref.org/works/"


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_cache(data: dict) -> None:
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(json.dumps(data), encoding="utf-8")


def format_work(msg: dict) -> str:
    """Format a Crossref ``message`` object as ``Authors (Year). Title. Journal…``."""
    if not msg:
        return ""
    names = []
    for a in msg.get("author", []) or []:
        family = a.get("family", "")
        given = a.get("given", "")
        if family:
            names.append(f"{family}{', ' + given[0] + '.' if given else ''}")
    author_str = ", ".join(names[:6]) + (" et al." if len(names) > 6 else "")

    title = _clean((msg.get("title") or [""])[0])
    journal = _clean((msg.get("container-title") or [""])[0])
    year = ""
    parts = msg.get("issued", {}).get("date-parts") or [[None]]
    if parts and parts[0] and parts[0][0]:
        year = str(parts[0][0])
    volume = msg.get("volume", "")
    page = msg.get("page", "")
    doi = msg.get("DOI", "")

    out = []
    if author_str:
        out.append(author_str)
    if year:
        out.append(f"({year})")
    if title:
        out.append(title.rstrip(".") + ".")
    tail = journal
    if volume:
        tail += f", {volume}"
    if page:
        tail += f", {page}"
    if tail:
        out.append(tail.rstrip(".") + ".")
    text = " ".join(out).strip()
    if doi:
        text += f" doi:{doi}"
    return text


def fetch_work(doi: str, mailto: str | None = None, timeout: float = 8.0) -> dict | None:
    """Fetch (and cache) the Crossref ``message`` for ``doi``; None on any failure."""
    doi = (doi or "").strip()
    if not doi:
        return None
    cache = _load_cache()
    if doi in cache:
        return cache[doi]
    try:
        import requests

        ua = f"XRDLab/0.1 (mailto:{mailto})" if mailto else "XRDLab/0.1"
        resp = requests.get(_API + doi, headers={"User-Agent": ua}, timeout=timeout)
        if resp.status_code != 200:
            return None
        msg = resp.json().get("message")
    except Exception:  # noqa: BLE001 — Crossref is best-effort
        return None
    if msg:
        cache[doi] = msg
        _save_cache(cache)
    return msg


def format_doi(doi: str, mailto: str | None = None) -> str:
    """Fetch and format a DOI in one call (``""`` if unavailable)."""
    return format_work(fetch_work(doi, mailto) or {})
