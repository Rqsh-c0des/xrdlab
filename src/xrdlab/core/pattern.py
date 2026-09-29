"""The core diffraction-pattern data model."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = ["Pattern"]

CU_KALPHA1 = 1.5405980  # Angstrom


@dataclass
class Pattern:
    """A single 1-D diffraction scan.

    Parameters
    ----------
    two_theta : ndarray
        Scattering angle 2θ in degrees (1-D, monotonically increasing).
    intensity : ndarray
        Measured intensity (counts or cps), same length as ``two_theta``.
    wavelength : float
        Source wavelength in Angstrom (default Cu Kα1).
    name : str
        Human-readable label (used in legends / the UI list).
    meta : dict
        Free-form provenance (source file, counting time, Kα2/Kβ, comments…).
    """

    two_theta: np.ndarray
    intensity: np.ndarray
    wavelength: float = CU_KALPHA1
    name: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.two_theta = np.asarray(self.two_theta, dtype=float)
        self.intensity = np.asarray(self.intensity, dtype=float)
        if self.two_theta.shape != self.intensity.shape:
            raise ValueError(
                "two_theta and intensity must have the same shape "
                f"({self.two_theta.shape} vs {self.intensity.shape})"
            )

    def __len__(self) -> int:
        return int(self.two_theta.size)

    @property
    def two_theta_range(self) -> tuple[float, float]:
        """(min, max) of the 2θ axis."""
        if self.two_theta.size == 0:
            return (0.0, 0.0)
        return (float(self.two_theta.min()), float(self.two_theta.max()))

    def copy(self) -> "Pattern":
        """Deep copy (arrays and meta are copied)."""
        return Pattern(
            two_theta=self.two_theta.copy(),
            intensity=self.intensity.copy(),
            wavelength=self.wavelength,
            name=self.name,
            meta=dict(self.meta),
        )

    def with_intensity(self, new_intensity: np.ndarray) -> "Pattern":
        """Return a copy with a replaced intensity array (same x / name / meta)."""
        return Pattern(
            two_theta=self.two_theta.copy(),
            intensity=np.asarray(new_intensity, dtype=float),
            wavelength=self.wavelength,
            name=self.name,
            meta=dict(self.meta),
        )
