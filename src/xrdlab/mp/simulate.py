"""Simulate an XRD reference pattern from a crystal structure.

Thin wrapper over :class:`pymatgen.analysis.diffraction.xrd.XRDCalculator`.
``pymatgen`` is imported lazily so the rest of the app runs without it installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = ["ReferencePattern", "simulate_pattern", "RADIATION"]

# Common lab-source wavelengths accepted by pymatgen's XRDCalculator.
RADIATION = (
    "CuKa", "CuKa1", "CuKa2", "CuKb1",
    "MoKa", "MoKa1", "CoKa", "CoKa1", "CrKa", "FeKa", "AgKa",
)


@dataclass
class ReferencePattern:
    """A simulated stick pattern for phase-reference overlay."""

    two_theta: np.ndarray
    intensity: np.ndarray  # relative, 0–100
    hkls: list = field(default_factory=list)
    formula: str = ""
    material_id: str = ""
    wavelength: str = "CuKa1"
    d_spacings: np.ndarray | None = None  # Angstrom, wavelength-independent
    crystal_system: str = ""               # e.g. "cubic", "hexagonal"
    space_group: str = ""                  # e.g. "Fm-3m"
    space_group_number: int | None = None

    def __post_init__(self) -> None:
        self.two_theta = np.asarray(self.two_theta, dtype=float)
        self.intensity = np.asarray(self.intensity, dtype=float)
        if self.d_spacings is not None:
            self.d_spacings = np.asarray(self.d_spacings, dtype=float)


def simulate_pattern(
    structure,
    wavelength: str | float = "CuKa1",
    two_theta_range: tuple[float, float] = (10.0, 120.0),
    formula: str = "",
    material_id: str = "",
    min_intensity: float = 0.5,
) -> ReferencePattern:
    """Compute a reference XRD stick pattern from a pymatgen ``Structure``.

    Parameters
    ----------
    structure : pymatgen.core.Structure
    wavelength : str or float
        A key from :data:`RADIATION` (e.g. ``"CuKa1"``) or a numeric wavelength in
        Angstrom. Pass the measured pattern's wavelength so the reference lines up
        with the data.
    two_theta_range : (float, float)
        Angular window to compute reflections over (clip this to the data range to
        avoid drawing reflections outside the measured window).
    formula, material_id : str
        Carried onto the result for labelling.
    min_intensity : float
        Drop reflections weaker than this percent of the strongest (declutters the
        overlay). Set 0 to keep every reflection.

    Returns
    -------
    ReferencePattern
    """
    from pymatgen.analysis.diffraction.xrd import XRDCalculator
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    # Use the conventional standard cell so reflections carry conventional Miller
    # indices, and capture the crystal system / space group.
    crystal_system = space_group = ""
    space_group_number = None
    try:
        sga = SpacegroupAnalyzer(structure)
        structure = sga.get_conventional_standard_structure()
        crystal_system = sga.get_crystal_system()
        space_group = sga.get_space_group_symbol()
        space_group_number = sga.get_space_group_number()
    except Exception:  # noqa: BLE001 — symmetry analysis can fail on odd cells
        pass

    calc = XRDCalculator(wavelength=wavelength)
    pat = calc.get_pattern(structure, two_theta_range=two_theta_range)
    x = np.asarray(pat.x, dtype=float)
    y = np.asarray(pat.y, dtype=float)
    hkls = list(pat.hkls)
    d = np.asarray(getattr(pat, "d_hkls", np.full(x.shape, np.nan)), dtype=float)
    if min_intensity > 0 and y.size:
        keep = y >= min_intensity
        x, y, d = x[keep], y[keep], d[keep]
        hkls = [h for h, k in zip(hkls, keep) if k]
    if not formula:
        try:
            formula = structure.composition.reduced_formula
        except Exception:  # noqa: BLE001 — labelling only
            formula = ""
    return ReferencePattern(
        two_theta=x,
        intensity=y,
        hkls=hkls,
        formula=formula,
        material_id=material_id,
        wavelength=str(wavelength),
        d_spacings=d,
        crystal_system=crystal_system,
        space_group=space_group,
        space_group_number=space_group_number,
    )
