"""Overlay a Materials Project reference stick pattern onto an axes.

Draws PDF-card-style vertical reflection lines beneath the measured data and
optionally labels the strongest reflections with their (h k l).
"""

from __future__ import annotations

import numpy as np
from matplotlib.axes import Axes

from xrdlab.ml.labeling import format_hkl, subscript_digits
from xrdlab.mp.simulate import ReferencePattern

__all__ = ["overlay_reference"]


def _hkl_str(hkl) -> str:
    """Format an hkl triple with crystallographic overbars for negatives."""
    return format_hkl(hkl)


def overlay_reference(
    ax: Axes,
    ref: ReferencePattern,
    *,
    scale: float = 1.0,
    color: str = "#d62728",
    label_hkl: bool = True,
    label_threshold: float = 20.0,
    y_base: float = 0.0,
    linewidth: float = 0.9,
    tick_row: bool = False,
    row_base: float = 0.0,
) -> None:
    """Draw ``ref`` as scaled sticks on ``ax``.

    Parameters
    ----------
    ax : matplotlib Axes
        Axes already carrying the measured pattern (defines the y-scale).
    ref : ReferencePattern
        Has ``two_theta``, ``intensity`` (0–100 relative), ``hkls``, ``formula``.
    scale : float
        Fraction of the current y-range used by a 100-intensity stick.
    color : str
    label_hkl : bool
        Annotate reflections whose relative intensity exceeds ``label_threshold``.
    label_threshold : float
        Relative-intensity cutoff (0–100) for drawing an (h k l) label.
    y_base : float
        Baseline (data y) the sticks grow from — useful in waterfall stacks.
    linewidth : float
    """
    x = np.asarray(ref.two_theta, dtype=float)
    rel = np.asarray(ref.intensity, dtype=float)
    if rel.size and rel.max() > 0:
        rel = 100.0 * rel / rel.max()

    ax.plot([], [], color=color, lw=linewidth,
            label=subscript_digits(ref.formula))  # legend proxy (Al₂O₃)

    if tick_row:
        # PDF-card style: short ticks along the bottom (axes-fraction height) that
        # never touch the data. Every reflection is drawn AND labelled.
        trans = ax.get_xaxis_transform()  # x in data coords, y in axes fraction
        lo = row_base + 0.015
        heights = lo + 0.05 * rel / 100.0  # 0.015–0.065 of the axes height
        ax.vlines(x, row_base, heights, transform=trans, color=color,
                  lw=linewidth, zorder=3, clip_on=False)
        if label_hkl and ref.hkls is not None:
            # Stagger labels of closely-spaced reflections across 3 heights so the
            # rotated text never overlaps.
            span = float(x.max() - x.min()) if x.size > 1 else 1.0
            min_gap = 0.028 * span
            order = np.argsort(x)
            last_x, stagger = -1e9, 0
            for j in order:
                label = _first_hkl_label(ref.hkls[j])
                if not label:
                    continue
                stagger = (stagger + 1) % 3 if (x[j] - last_x) < min_gap else 0
                last_x = x[j]
                ax.annotate(
                    f"({label})", xy=(x[j], heights[j] + 0.03 * stagger),
                    xycoords=trans, xytext=(0, 1), textcoords="offset points",
                    ha="center", va="bottom", fontsize=5.5, color=color,
                    rotation=90, annotation_clip=False,
                )
        return

    y0, y1 = ax.get_ylim()
    span = (y1 - y0) * scale
    heights = y_base + span * rel / 100.0
    ax.vlines(x, y_base, heights, color=color, lw=linewidth, zorder=1)

    if label_hkl and ref.hkls is not None:
        for xi, hi, hk in zip(x, heights, ref.hkls):
            if _rel_of(hk, rel, x, xi) < label_threshold:
                continue
            label = _first_hkl_label(hk)
            if label:
                ax.annotate(
                    f"({label})", xy=(xi, hi), xytext=(0, 2),
                    textcoords="offset points", ha="center", va="bottom",
                    fontsize=7, color=color, rotation=90, annotation_clip=True,
                )


def _first_hkl_label(hk) -> str:
    """pymatgen returns a list of {'hkl': (h,k,l), ...}; take the first."""
    if isinstance(hk, (list, tuple)) and hk and isinstance(hk[0], dict):
        return _hkl_str(hk[0].get("hkl", ""))
    if isinstance(hk, dict):
        return _hkl_str(hk.get("hkl", ""))
    return _hkl_str(hk)


def _rel_of(hk, rel, x, xi) -> float:
    idx = int(np.argmin(np.abs(x - xi)))
    return float(rel[idx]) if rel.size else 0.0
