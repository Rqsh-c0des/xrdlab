"""Figure export to publication vector formats."""

from __future__ import annotations

import os
from pathlib import Path

from matplotlib.figure import Figure

__all__ = ["EXPORT_FORMATS", "save_figure"]

EXPORT_FORMATS: tuple[str, ...] = ("pdf", "eps", "svg", "png")


def save_figure(
    fig: Figure,
    path: str | os.PathLike,
    dpi: int = 300,
    transparent: bool = False,
) -> Path:
    """Save ``fig`` to ``path``, inferring the format from the extension.

    Vector formats (pdf/eps/svg) keep editable text thanks to the rcParams set by
    :func:`xrdlab.plotting.style.apply_publication_style`. Raster (png) uses
    ``dpi``. Returns the resolved output path.
    """
    path = Path(path)
    fmt = path.suffix.lower().lstrip(".")
    if fmt not in EXPORT_FORMATS:
        raise ValueError(
            f"unsupported export format {fmt!r}; choose one of {EXPORT_FORMATS}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path,
        format=fmt,
        dpi=dpi,
        bbox_inches="tight",
        transparent=transparent,
    )
    return path
