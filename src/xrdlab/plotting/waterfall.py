"""Stacked waterfall plot of multiple diffraction patterns.

Curves are offset vertically so peaks never overlap, making 2θ shifts between
samples easy to read.
"""

from __future__ import annotations

from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from xrdlab.core.pattern import Pattern
from xrdlab.core.processing import normalize
from xrdlab.plotting.style import AXIS_LABELS, apply_publication_style

__all__ = ["plot_waterfall"]


def plot_waterfall(
    patterns: Sequence[Pattern],
    *,
    ax: Axes | None = None,
    gap: float = 1.0,
    normalize_each: bool = True,
    labels: Sequence[str] | None = None,
    label_side: str = "right",
    colors: Sequence | None = None,
    linewidth: float = 1.0,
    yscale: str = "linear",
    peak_labels: Sequence | None = None,
) -> tuple[Figure, Axes]:
    """Draw a vertically-offset stack of patterns.

    Parameters
    ----------
    patterns : sequence of Pattern
        Drawn bottom-to-top in the given order.
    ax : matplotlib Axes, optional
        Target axes; a new figure is created when omitted.
    gap : float
        Vertical offset between successive curves. If ``normalize_each`` is True
        the unit is "fraction of the normalized peak" (1.0 = one full curve
        height); otherwise it is in raw intensity units of each curve's max.
    normalize_each : bool
        Scale every curve to a peak of 1 before offsetting so the stack is even.
    labels : sequence of str, optional
        Per-curve labels; defaults to each pattern's ``name``.
    label_side : {"right", "left", "none"}
        Where to annotate each curve.
    colors : sequence, optional
        Per-curve colours; defaults to the matplotlib cycle.
    linewidth : float
    yscale : {"linear", "log"}
        On ``log`` the stack is offset multiplicatively (each curve is pushed up by
        ``gap`` decades) so weak peaks stay visible.

    Returns
    -------
    (figure, axes)
    """
    apply_publication_style()
    if ax is None:
        fig, ax = plt.subplots(figsize=(6.0, 1.2 + 1.0 * len(patterns)))
    else:
        fig = ax.figure

    if labels is None:
        labels = [p.name or f"Pattern {i + 1}" for i, p in enumerate(patterns)]

    log = yscale == "log"
    offset = 0.0
    xmin, xmax = np.inf, -np.inf
    from xrdlab.core.processing import decimate_for_display

    for i, pattern in enumerate(patterns):
        x = pattern.two_theta
        y = np.asarray(pattern.intensity, dtype=float)
        if normalize_each:
            y = normalize(y, mode="max")
        x, y = decimate_for_display(x, y, max_points=4000)  # display only

        if log:
            # Multiplicative offset: each curve spans ~4 decades (floor 1e-4 of its
            # peak), so gap=1 leaves roughly one clear curve-height between stacks.
            floor = np.nanmax(y) * 1e-4 if normalize_each else max(np.nanmin(y[y > 0], initial=1.0), 1.0)
            yplot = np.clip(y, floor, None) * (10.0 ** (gap * 4.5 * i))
            y_label = yplot[-1] if label_side == "right" else yplot[0]
        else:
            step = gap if normalize_each else gap * np.nanmax(y)
            yplot = y + offset
            y_label = yplot[-1] if label_side == "right" else yplot[0]
            offset += step

        color = None if colors is None else colors[i % len(colors)]
        line = ax.plot(x, yplot, lw=linewidth, color=color)[0]

        # Per-curve peak labels (phase / hkl), placed on this curve's offset.
        if peak_labels is not None and i < len(peak_labels):
            for tt, text in peak_labels[i]:
                yv = float(np.interp(tt, x, yplot))
                ax.annotate(
                    text, xy=(tt, yv), xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=5.5, rotation=90,
                    color=line.get_color(), annotation_clip=True,
                )

        if label_side in ("right", "left"):
            at_right = label_side == "right"
            ax.annotate(
                labels[i],
                xy=(x[-1] if at_right else x[0], y_label),
                xytext=(4 if at_right else -4, 0),
                textcoords="offset points",
                va="bottom",
                ha="left" if at_right else "right",
                color=line.get_color(),
                fontsize=9,
                annotation_clip=False,
            )

        xmin, xmax = min(xmin, x[0]), max(xmax, x[-1])

    if log:
        ax.set_yscale("log")
    ax.set_xlim(xmin, xmax)
    ax.set_xlabel(AXIS_LABELS["x"])
    ax.set_ylabel(f"{AXIS_LABELS['y']} — {yscale} scale")
    ax.set_yticks([])  # intensity is arbitrary / offset
    ax.margins(y=0.02)
    return fig, ax
