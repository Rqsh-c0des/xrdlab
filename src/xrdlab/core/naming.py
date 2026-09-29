"""Parse metadata (sample, date, id…) out of a data file's name.

The parsing regex is user-configurable (see :mod:`xrdlab.config`) so different lab
naming conventions can be supported without code changes.
"""

from __future__ import annotations

import re

from xrdlab import config

__all__ = ["parse_filename", "label_for", "canonical_formula"]

# Built-in fallback for growth-temperature series, e.g. "XRD_5304_ScN_Al2O3_700C" or
# "XRD_5306_ScN-Al2O3_600C": type_id_<film/substrate>_<temp>C. Tried only when the
# user's configured pattern doesn't match.
_TEMP_SERIES = re.compile(
    r"^(?P<type>[A-Za-z]+)_(?P<id>\d+)_(?P<sample>.+?)_(?P<temp>\d+(?:\.\d+)?)\s*[Cc]$"
)

_ELEMENTS = set(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La "
    "Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po "
    "At Rn Fr Ra Ac Th Pa U Np Pu".split()
)
_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def _is_formula(token: str) -> bool:
    """True if ``token`` is element symbols (correct case) + optional counts."""
    parts = re.findall(r"[A-Z][a-z]?|\d+(?:\.\d+)?|.", token)
    return bool(parts) and all(
        p in _ELEMENTS or re.fullmatch(r"\d+(?:\.\d+)?", p) for p in parts
    )


def canonical_formula(token: str) -> str:
    """Fix the capitalisation of a formula typed in any case (``AL2O3`` → ``Al2O3``).

    Returns ``token`` unchanged if it's already a valid formula or can't be read as
    one (so ordinary words pass through untouched).
    """
    if _is_formula(token):
        return token
    low, out, i = token.lower(), [], 0
    while i < len(low):
        if low[i].isdigit() or low[i] == ".":
            j = i
            while j < len(low) and (low[j].isdigit() or low[j] == "."):
                j += 1
            out.append(low[i:j])
            i = j
            continue
        two, one = low[i:i + 2].capitalize(), low[i].upper()
        if len(low) > i + 1 and low[i + 1].isalpha() and two in _ELEMENTS:
            out.append(two)
            i += 2
        elif one in _ELEMENTS:
            out.append(one)
            i += 1
        else:
            return token  # not a formula — leave it alone
    return "".join(out)


def _temp_series_label(stem: str) -> str:
    m = _TEMP_SERIES.match(stem)
    if not m:
        return ""
    parts = [p for p in re.split(r"[_\-/]+", m.group("sample")) if p]
    mats = "/".join(canonical_formula(p).translate(_SUB) if _is_formula(canonical_formula(p))
                    else p for p in parts)
    temp = m.group("temp")
    return f"{mats} {temp} °C"


def parse_filename(stem: str, pattern: str | None = None) -> dict[str, str]:
    """Return the named-group fields matched in ``stem`` (empty dict if no match).

    ``pattern`` defaults to the saved filename regex. A malformed regex yields an
    empty dict rather than raising.
    """
    pattern = pattern or config.get_filename_pattern()
    try:
        match = re.search(pattern, stem)
    except re.error:
        return {}
    if not match:
        return {}
    return {k: v for k, v in match.groupdict().items() if v is not None}


def label_for(stem: str, pattern: str | None = None, field: str | None = None) -> str:
    """Derive a display label from ``stem`` using the configured field.

    Falls back to the full ``stem`` when the regex doesn't match or the field is
    absent. Underscores in the extracted value become ``/`` (so ``GaN_ScN`` reads
    as ``GaN/ScN``).
    """
    fields = parse_filename(stem, pattern)
    field = field or config.get_filename_label_field()
    value = fields.get(field, "").strip()
    if not value:
        return _temp_series_label(stem) or stem
    return value.replace("_", "/")
