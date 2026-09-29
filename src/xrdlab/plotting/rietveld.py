"""The classic Rietveld refinement figure.

Two stacked panels sharing the 2θ axis:

* top: observed (red dots), calculated (black line), background (green line),
  and a row of reflection tick marks;
* bottom: the difference curve, obs − calc (blue line), centred on zero.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec

from xrdlab.core.rietveld_io import RietveldData
from xrdlab.plotting.style import AXIS_LABELS, RIETVELD_COLORS, apply_publication_style

__all__ = ["plot_rietveld"]


def plot_rietveld(
    data: RietveldData,
    *,
    fig: Figure | None = None,
    title: str | None = None,
    show_ticks: bool = True,
    obs_markersize: float = 2.5,
) -> Figure:
    """Render the observed/calculated/background/difference figure.

    Parameters
    ----------
    data : RietveldData
        Provides ``two_theta``, ``yobs``, ``ycalc``, ``ybkg``, optional
        ``reflections`` (2θ tick positions), and a ``diff`` property.
    fig : matplotlib Figure, optional
        Target figure; a new one is created when omitted.
    title : str, optional
    show_ticks : bool
        Draw the reflection tick-mark row (only if ``data.reflections`` is set).
    obs_markersize : float
        Marker size for the observed red dots.

    Returns
    -------
    matplotlib Figure
    """
    apply_publication_style()
    if fig is None:
        fig = plt.figure(figsize=(6.5, 4.8))

    have_ticks = show_ticks and data.reflections is not None
    if have_ticks:
        gs = GridSpec(
            3, 1, height_ratios=[4.0, 0.4, 1.0], hspace=0.05, figure=fig
        )
        ax_main = fig.add_subplot(gs[0])
        ax_tick = fig.add_subplot(gs[1], sharex=ax_main)
        ax_diff = fig.add_subplot(gs[2], sharex=ax_main)
    else:
        gs = GridSpec(2, 1, height_ratios=[4.0, 1.0], hspace=0.05, figure=fig)
        ax_main = fig.add_subplot(gs[0])
        ax_tick = None
        ax_diff = fig.add_subplot(gs[1], sharex=ax_main)

    x = data.two_theta

    # --- top panel ---
    ax_main.plot(
        x, data.yobs, ls="none", marker="o", markersize=obs_markersize,
        markerfacecolor="none", markeredgewidth=0.6,
        color=RIETVELD_COLORS["obs"], label="Observed",
    )
    ax_main.plot(x, data.ycalc, lw=1.0, color=RIETVELD_COLORS["calc"], label="Calculated")
    ax_main.plot(x, data.ybkg, lw=0.9, color=RIETVELD_COLORS["bkg"], label="Background")
    ax_main.set_ylabel(AXIS_LABELS["y_counts"])
    ax_main.legend(loc="upper right", handlelength=1.6)
    ax_main.tick_params(labelbottom=False)
    if title:
        ax_main.set_title(title)

    # --- reflection ticks ---
    if have_ticks and ax_tick is not None:
        refl = np.asarray(data.reflections, dtype=float)
        refl = refl[np.isfinite(refl)]
        ax_tick.vlines(refl, 0, 1, lw=0.8, color=RIETVELD_COLORS["ticks"])
        ax_tick.set_yticks([])
        ax_tick.set_ylim(0, 1)
        # Hide the panel's own axis ticks so only the reflection markers show.
        ax_tick.tick_params(
            axis="both", which="both", bottom=False, top=False,
            left=False, right=False, labelbottom=False,
        )
        ax_tick.minorticks_off()
        for spine in ("left", "right", "top", "bottom"):
            ax_tick.spines[spine].set_visible(False)

    # --- difference panel ---
    ax_diff.axhline(0, lw=0.6, color=RIETVELD_COLORS["ticks"])
    ax_diff.plot(x, data.diff, lw=0.8, color=RIETVELD_COLORS["diff"], label="Difference")
    ax_diff.set_xlabel(AXIS_LABELS["x"])
    ax_diff.set_ylabel(r"$\Delta$")
    ax_diff.set_xlim(x[0], x[-1])

    return fig
