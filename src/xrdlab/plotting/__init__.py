"""Publication-quality figure builders for XRDLab."""

from xrdlab.plotting.export import EXPORT_FORMATS, save_figure
from xrdlab.plotting.overlay import overlay_reference
from xrdlab.plotting.rietveld import plot_rietveld
from xrdlab.plotting.style import RIETVELD_COLORS, apply_publication_style
from xrdlab.plotting.waterfall import plot_waterfall

__all__ = [
    "apply_publication_style",
    "RIETVELD_COLORS",
    "save_figure",
    "EXPORT_FORMATS",
    "plot_waterfall",
    "plot_rietveld",
    "overlay_reference",
]
