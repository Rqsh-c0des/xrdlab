"""Future machine-learning phase: peak labelling and phase identification.

Only interface stubs live here for now, so plotting/UI code can depend on the
seams before any model exists.
"""

from xrdlab.ml.labeling import PeakLabel, PeakLabeler, PhaseIdentifier, PhaseMatch
from xrdlab.ml.phase_db import PhaseCandidate, PhaseDatabase

__all__ = [
    "PeakLabel",
    "PeakLabeler",
    "PhaseMatch",
    "PhaseIdentifier",
    "PhaseDatabase",
    "PhaseCandidate",
]
