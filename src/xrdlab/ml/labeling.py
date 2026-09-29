"""Interface seams for the future ML phase (no models yet).

These Protocols let plotting/UI code call an eventual peak-labeller or phase
identifier without knowing its implementation. A trivial, dependency-free
:class:`ProminencePeakLabeler` is provided so the plumbing can be exercised today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

import numpy as np

from xrdlab.core.pattern import Pattern

__all__ = [
    "PeakLabel",
    "PhaseMatch",
    "PeakLabeler",
    "PhaseIdentifier",
    "ProminencePeakLabeler",
    "format_hkl",
    "hkl_display",
    "subscript_digits",
    "subscriptify",
    "flatten_reflections",
    "assign_peaks",
]


@dataclass
class PeakLabel:
    """A labelled peak position."""

    two_theta: float
    intensity: float
    label: str = ""
    hkl: tuple[int, int, int] | None = None
    confidence: float = 1.0
    fwhm: float | None = None  # full width at half maximum in °2θ (from data)


@dataclass
class PhaseMatch:
    """A candidate phase identification for a whole pattern."""

    formula: str
    score: float
    material_id: str = ""
    matched_peaks: list[PeakLabel] = field(default_factory=list)


@runtime_checkable
class PeakLabeler(Protocol):
    """Anything that turns a pattern into labelled peaks."""

    def label(self, pattern: Pattern) -> list[PeakLabel]:
        ...


@runtime_checkable
class PhaseIdentifier(Protocol):
    """Anything that proposes candidate phases for a pattern."""

    def identify(self, pattern: Pattern, top_k: int = 5) -> list[PhaseMatch]:
        ...


_OVERLINE = "̅"  # combining overline, renders a crystallographic bar
_SUB_DIGIT = {str(i): "₀₁₂₃₄₅₆₇₈₉"[i] for i in range(10)}
_SUB_ALL = {**_SUB_DIGIT, "+": "₊", "-": "₋", "(": "₍", ")": "₎",
            "a": "ₐ", "e": "ₑ", "x": "ₓ", "n": "ₙ"}


def subscript_digits(s: str) -> str:
    """Subscript the digits in a chemical formula (``Al2O3`` -> ``Al₂O₃``)."""
    return "".join(_SUB_DIGIT.get(c, c) for c in s)


def subscriptify(text: str) -> str:
    """Convert ``_2`` / ``_{23}`` markup to Unicode subscripts (manual labels)."""
    import re

    def _grp(m):
        return "".join(_SUB_ALL.get(c, c) for c in m.group(1))

    text = re.sub(r"_\{([^}]*)\}", _grp, text)
    return re.sub(r"_(\d+|.)", _grp, text)


def _bar(v: int) -> str:
    """A Miller index with a crystallographic overbar for negatives (1̄, not -1)."""
    if v < 0:
        return "".join(c + _OVERLINE for c in str(-v))
    return str(v)


def format_hkl(hkl) -> str:
    """Format an (h k l) triple, negatives shown with an overbar (e.g. ``1 0 1̄``)."""
    try:
        vals = [int(round(float(v))) for v in hkl]
    except (TypeError, ValueError):
        return str(hkl)
    if all(0 <= v <= 9 for v in vals):
        return "".join(str(v) for v in vals)
    return " ".join(_bar(v) for v in vals)


def hkl_display(hkl) -> str:
    """Display an hkl that may be a tuple (references) or a string (database).

    Converts any ``-N`` in a stored string to an overbar so older entries also
    render with the crystallographic bar.
    """
    if hkl is None:
        return ""
    if isinstance(hkl, str):
        import re

        return re.sub(
            r"-(\d+)", lambda m: "".join(c + _OVERLINE for c in m.group(1)), hkl
        )
    return format_hkl(hkl)


def _extract_hkl(entry) -> tuple | None:
    """Pull an (h,k,l) tuple out of pymatgen's per-reflection hkl structure."""
    if isinstance(entry, (list, tuple)) and entry and isinstance(entry[0], dict):
        return tuple(entry[0].get("hkl", ()))
    if isinstance(entry, dict):
        return tuple(entry.get("hkl", ()))
    if isinstance(entry, (list, tuple)) and entry:
        return tuple(entry)
    return None


def flatten_reflections(references) -> list[tuple]:
    """Flatten reference patterns to ``(two_theta, formula, hkl, rel_intensity)``."""
    out: list[tuple] = []
    for ref in references:
        hkls = list(ref.hkls) if ref.hkls else [None] * len(ref.two_theta)
        for tt, inten, hk in zip(ref.two_theta, ref.intensity, hkls):
            out.append((float(tt), ref.formula, _extract_hkl(hk), float(inten)))
    return out


def assign_peaks(
    peaks: list[PeakLabel], references, tol_deg: float = 0.5
) -> list[PeakLabel]:
    """Assign each peak the nearest reference reflection within ``tol_deg``.

    Given the sample's expected phases (as simulated reference patterns), label
    each detected peak with the closest reflection's formula and (h k l). Peaks
    with no reflection inside the tolerance are left unlabelled. Mutates and
    returns ``peaks``.
    """
    reflections = flatten_reflections(references)
    for pk in peaks:
        best = None
        best_d = tol_deg
        for tt, formula, hkl, _inten in reflections:
            d = abs(tt - pk.two_theta)
            if d <= best_d:
                best_d = d
                best = (formula, hkl)
        if best is not None:
            formula, hkl = best
            pk.label = formula
            pk.hkl = hkl
            pk.confidence = max(0.0, 1.0 - best_d / tol_deg) if tol_deg else 1.0
    return peaks


class ProminencePeakLabeler:
    """Baseline non-ML labeller using scipy peak prominence.

    Serves as a reference implementation of the :class:`PeakLabeler` protocol
    until a trained model replaces it.
    """

    def __init__(self, min_prominence_frac: float = 0.02):
        self.min_prominence_frac = min_prominence_frac

    def label(self, pattern: Pattern) -> list[PeakLabel]:
        from scipy.signal import find_peaks

        y = np.asarray(pattern.intensity, dtype=float)
        if y.size == 0:
            return []
        prominence = self.min_prominence_frac * (np.nanmax(y) - np.nanmin(y))
        idx, _ = find_peaks(y, prominence=max(prominence, 1e-9))
        return [
            PeakLabel(two_theta=float(pattern.two_theta[i]), intensity=float(y[i]))
            for i in idx
        ]
