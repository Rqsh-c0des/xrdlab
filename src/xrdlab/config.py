"""Persistent app configuration (currently just the Materials Project API key).

Stored as JSON at ``~/.xrdlab/config.json`` so non-GUI code (e.g. the MP client)
can read it without importing Qt. The key resolution order is
``explicit argument -> saved config -> MP_API_KEY env / .env``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

__all__ = [
    "config_path",
    "get_saved_api_key",
    "set_api_key",
    "resolve_api_key",
    "mask_key",
    "get_filename_pattern",
    "set_filename_pattern",
    "get_filename_label_field",
    "set_filename_label_field",
    "get_crossref_mailto",
    "set_crossref_mailto",
    "get_value",
    "set_value",
    "get_instrument_fwhm",
    "set_instrument_fwhm",
    "add_recent_project",
    "get_recent_projects",
    "DEFAULT_FILENAME_PATTERN",
    "DEFAULT_FILENAME_FIELD",
]

CONFIG_DIR = Path.home() / ".xrdlab"
CONFIG_PATH = CONFIG_DIR / "config.json"
_KEY = "mp_api_key"
_FN_PATTERN = "filename_pattern"
_FN_FIELD = "filename_label_field"
_CROSSREF_MAILTO = "crossref_mailto"

# Default matches e.g. "XRD_5292_GaN_ScN_260713_1551":
#   type=XRD  id=5292  sample=GaN_ScN  date=260713  time=1551
DEFAULT_FILENAME_PATTERN = (
    r"(?P<type>[A-Za-z]+)_(?P<id>\d+)_(?P<sample>.+?)_"
    r"(?P<date>\d{6})_(?P<time>\d{3,6})"
)
DEFAULT_FILENAME_FIELD = "sample"


def config_path() -> Path:
    """Location of the on-disk config file."""
    return CONFIG_PATH


def _load() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Best-effort: restrict to the current user (no-op on some Windows setups).
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def get_saved_api_key() -> str:
    """Return the API key saved in the config file (``""`` if none)."""
    return str(_load().get(_KEY, "") or "")


def set_api_key(key: str | None) -> None:
    """Persist ``key`` to the config file; an empty/None value clears it."""
    data = _load()
    key = (key or "").strip()
    if key:
        data[_KEY] = key
    else:
        data.pop(_KEY, None)
    _save(data)


def resolve_api_key(explicit: str | None = None) -> str:
    """Resolve the effective API key by precedence; ``""`` if none available.

    Order: explicit argument -> saved config -> ``MP_API_KEY`` (env or ``.env``).
    """
    if explicit and explicit.strip():
        return explicit.strip()
    saved = get_saved_api_key()
    if saved:
        return saved
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # noqa: BLE001 — dotenv is optional
        pass
    return os.environ.get("MP_API_KEY", "").strip()


def get_filename_pattern() -> str:
    """Regex used to parse metadata out of a loaded file's name."""
    return str(_load().get(_FN_PATTERN) or DEFAULT_FILENAME_PATTERN)


def set_filename_pattern(pattern: str | None) -> None:
    """Persist the filename-parsing regex; empty/None restores the default."""
    data = _load()
    pattern = (pattern or "").strip()
    if pattern:
        data[_FN_PATTERN] = pattern
    else:
        data.pop(_FN_PATTERN, None)
    _save(data)


def get_filename_label_field() -> str:
    """Which named group from the filename regex is used as the display label."""
    return str(_load().get(_FN_FIELD) or DEFAULT_FILENAME_FIELD)


def set_filename_label_field(field: str | None) -> None:
    """Persist the label field name; empty/None restores the default."""
    data = _load()
    field = (field or "").strip()
    if field:
        data[_FN_FIELD] = field
    else:
        data.pop(_FN_FIELD, None)
    _save(data)


def get_crossref_mailto() -> str:
    """Optional contact email for the Crossref polite pool (``""`` if unset)."""
    return str(_load().get(_CROSSREF_MAILTO, "") or "")


def set_crossref_mailto(email: str | None) -> None:
    """Persist the Crossref contact email; empty/None clears it."""
    data = _load()
    email = (email or "").strip()
    if email:
        data[_CROSSREF_MAILTO] = email
    else:
        data.pop(_CROSSREF_MAILTO, None)
    _save(data)


def get_value(key: str, default=None):
    """Read an arbitrary persisted setting (window geometry, last dir, …)."""
    return _load().get(key, default)


def set_value(key: str, value) -> None:
    """Persist an arbitrary setting; ``None`` removes it."""
    data = _load()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    _save(data)


def get_instrument_fwhm() -> float:
    """Instrumental broadening (°2θ FWHM) subtracted from Scherrer sizes; 0 = off."""
    try:
        return float(_load().get("instrument_fwhm", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def set_instrument_fwhm(value: float | None) -> None:
    set_value("instrument_fwhm", None if not value else float(value))


def get_recent_projects() -> list:
    """Most-recently-opened project paths, newest first (max 8)."""
    v = _load().get("recent_projects", [])
    return [str(p) for p in v] if isinstance(v, list) else []


def add_recent_project(path: str) -> None:
    """Record ``path`` as the most-recent project (deduped, capped at 8)."""
    path = str(path)
    recent = [p for p in get_recent_projects() if p != path]
    recent.insert(0, path)
    set_value("recent_projects", recent[:8])


def mask_key(key: str) -> str:
    """Return a display-safe masked form of ``key`` (never the full value)."""
    if not key:
        return "not set"
    if len(key) <= 6:
        return "•" * len(key)
    return f"{key[:3]}…{key[-3:]} ({len(key)} chars)"
