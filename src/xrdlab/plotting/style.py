"""Shared matplotlib styling for publication figures.

Sets vector-friendly defaults so exported PDF/EPS/SVG keep selectable text and
clean thin spines, and defines the canonical Rietveld colour map.
"""

from __future__ import annotations

import matplotlib as mpl

__all__ = ["apply_publication_style", "RIETVELD_COLORS", "AXIS_LABELS"]

# Canonical Rietveld curve colours: observed=red, calculated=black,
# background=green, difference=blue (the conventional journal scheme).
RIETVELD_COLORS = {
    "obs": "#d62728",
    "calc": "#000000",
    "bkg": "#2ca02c",
    "diff": "#1f77b4",
    "ticks": "#7f7f7f",
}

AXIS_LABELS = {
    "x": r"2$\theta$ (degrees)",
    "y": "Intensity (arb. units)",
    "y_counts": "Intensity (counts)",
    "y_cps": "Intensity (cps)",
}


def apply_publication_style() -> None:
    """Apply publication-quality rcParams in-place.

    Idempotent; safe to call before building any figure. Fonts are embedded as
    editable text (``pdf.fonttype=42``, ``svg.fonttype='none'``) so figures can be
    re-typeset by a journal without re-rendering.
    """
    mpl.rcParams.update(
        {
            # Fonts — DejaVu Sans first: it has the subscript / combining-overbar
            # glyphs (Al₂O₃, 1̄) that Arial lacks, and it's publication-grade.
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.labelsize": 11,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "mathtext.default": "regular",
            # Vector-safe text embedding
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            # Spines / ticks — thin, inward, publication look
            "axes.linewidth": 0.8,
            "xtick.direction": "in",
            "ytick.direction": "in",
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.minor.visible": True,
            "ytick.minor.visible": True,
            "xtick.top": True,
            "ytick.right": True,
            "lines.linewidth": 1.0,
            # Figure
            "figure.dpi": 120,
            "savefig.dpi": 300,
            "figure.autolayout": False,
            "axes.grid": False,
            "legend.frameon": False,
        }
    )
