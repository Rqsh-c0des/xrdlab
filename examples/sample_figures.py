"""Scripted, no-GUI demo of the XRDLab plotting core.

Renders a stacked waterfall of the ScN/GaN test scans and a synthetic Rietveld
figure, exporting both to vector + raster formats under ``examples/out/``.

Run::

    python examples/sample_figures.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from xrdlab.core.pattern import Pattern
from xrdlab.core.rietveld_io import RietveldData
from xrdlab.core.xrdml import read_xrdml_single
from xrdlab.plotting.export import save_figure
from xrdlab.plotting.rietveld import plot_rietveld
from xrdlab.plotting.style import apply_publication_style
from xrdlab.plotting.waterfall import plot_waterfall

OUT = Path(__file__).parent / "out"
DOWNLOADS = Path.home() / "Downloads"
SAMPLE_FILES = [
    DOWNLOADS / "XRD_5289_Al2O3_ScN_260619_1610.xrdml",
    DOWNLOADS / "XRD_5292_GaN_ScN_260713_1551.xrdml",
]


def _load_patterns() -> list[Pattern]:
    patterns = []
    for path in SAMPLE_FILES:
        if path.exists():
            patterns.append(read_xrdml_single(path))
    if not patterns:  # fall back to synthetic data so the demo always runs
        x = np.linspace(15, 120, 2000)
        for i, shift in enumerate((0.0, 0.4)):
            y = 200 + 8000 * np.exp(-((x - (36 + shift)) ** 2) / 0.05)
            y += 5000 * np.exp(-((x - (43 + shift)) ** 2) / 0.06)
            patterns.append(Pattern(x, y, name=f"synthetic {i + 1}"))
    return patterns


def _synthetic_rietveld() -> RietveldData:
    x = np.linspace(15, 90, 3000)
    bkg = 120 + 0.4 * (x - 15)
    peaks = [(28.4, 9000, 0.05), (33.0, 4200, 0.05), (47.3, 5200, 0.06),
             (56.1, 3000, 0.07), (69.1, 1800, 0.08)]
    calc = bkg.copy()
    for pos, amp, w in peaks:
        calc += amp * np.exp(-((x - pos) ** 2) / w)
    rng = np.random.default_rng(0)
    obs = calc + rng.normal(0, np.sqrt(np.clip(calc, 1, None)))
    return RietveldData(
        two_theta=x, yobs=obs, ycalc=calc, ybkg=bkg,
        reflections=np.array([p[0] for p in peaks]), name="Synthetic Rietveld",
    )


def main() -> None:
    apply_publication_style()
    OUT.mkdir(parents=True, exist_ok=True)

    fig_w, _ = plot_waterfall(_load_patterns(), gap=1.1)
    for ext in ("pdf", "svg", "png"):
        save_figure(fig_w, OUT / f"waterfall.{ext}")

    fig_r = plot_rietveld(_synthetic_rietveld())
    for ext in ("pdf", "svg", "png"):
        save_figure(fig_r, OUT / f"rietveld.{ext}")

    print(f"Wrote figures to {OUT}")


if __name__ == "__main__":
    main()
