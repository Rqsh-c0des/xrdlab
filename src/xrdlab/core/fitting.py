"""Single-peak profile fitting (pseudo-Voigt) for accurate 2θ / FWHM / area.

With lab Cu radiation every reflection is really a Kα1 + Kα2 doublet (Kα2 at half
the intensity, a Bragg-law step higher in 2θ). When the doublet is unresolved — e.g.
a ScN film peak ~0.18° wide with a ~0.09° split — a single-peak fit overstates the
width, so :func:`fit_peak` fits the doublet with a shared shape and reports the
**Kα1** FWHM. Kept separate from ``processing`` so scipy.optimize is only imported
when a fit is actually requested.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from xrdlab.core.processing import peak_fwhm

__all__ = ["PeakFit", "fit_peak", "pseudo_voigt", "ka2_position", "doublet_kwargs"]


def doublet_kwargs(pattern, *, ka2_stripped: bool = False) -> dict:
    """``fit_peak`` keyword args to model the Kα doublet for ``pattern``, or ``{}``.

    * No doublet when the optics are Kα1-only (hybrid / Ge monochromator — the usual
      HRXRD setup), when Kα2 was already stripped, or the file doesn't record Kα2.
    * 2θ-based scans: Kα2 is Bragg-placed at a higher 2θ.
    * ω rocking curves: Kα2 is a constant offset Δω = θ(Kα2) − θ(Kα1) at the fixed
      2θ; φ/χ scans don't split the doublet.
    """
    meta = getattr(pattern, "meta", {}) or {}
    k2, ratio = meta.get("kAlpha2"), meta.get("ratioKAlpha2KAlpha1")
    if ka2_stripped or meta.get("kalpha1_only") or not (k2 and ratio and pattern.wavelength):
        return {}
    axis = str(meta.get("x_axis") or "").lower()
    if not axis:  # older data without x_axis: fall back to the scan axis
        axis = "omega" if str(meta.get("scan_axis") or "").lower() == "omega" else "2theta"
    if axis == "2theta":
        return {"wavelength": float(pattern.wavelength), "ka2_wavelength": float(k2),
                "ka2_ratio": float(ratio)}
    if axis == "omega":
        tt = (meta.get("fixed_positions") or {}).get("2Theta")
        if not tt:
            return {}
        th1 = np.radians(tt / 2.0)
        s2 = float(k2) / float(pattern.wavelength) * np.sin(th1)
        if abs(s2) >= 1:
            return {}
        return {"ka2_offset": float(np.degrees(np.arcsin(s2) - th1)),
                "ka2_ratio": float(ratio)}
    return {}


@dataclass
class PeakFit:
    """Result of a single-peak (optionally Kα-doublet) fit."""

    center: float          # fitted Kα1 2θ (°)
    fwhm: float            # fitted Kα1 full width at half maximum (°2θ)
    amplitude: float       # Kα1 peak height above background
    eta: float             # Lorentzian fraction (0 = Gaussian, 1 = Lorentzian)
    background: float      # background level at the peak centre
    area: float            # integrated Kα1 area above background
    r_squared: float       # goodness of fit (1 = perfect)
    success: bool = True
    slope: float = 0.0     # linear background slope (counts / °)
    ka2_ratio: float = 0.0  # Kα2/Kα1 intensity ratio used (0 = single peak)
    ka_ratio_wl: float = 1.0  # λ(Kα2)/λ(Kα1) used to place the Kα2 component
    ka2_offset: float = 0.0   # constant Kα2 offset (°) — rocking curves (ω scans)

    def model(self, x):
        """Evaluate the fitted profile (both doublet components + background)."""
        x = np.asarray(x, dtype=float)
        y = self.background + self.slope * (x - self.center) + \
            _pv(x, self.center, self.fwhm, self.amplitude, self.eta)
        if self.ka2_ratio > 0:
            pos = (self.center + self.ka2_offset) if self.ka2_offset else                 ka2_position(self.center, self.ka_ratio_wl)
            y = y + _pv(x, pos, self.fwhm, self.amplitude * self.ka2_ratio, self.eta)
        return y


def _pv(x, center, fwhm, amplitude, eta):
    sigma = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    gauss = np.exp(-((x - center) ** 2) / (2.0 * sigma**2))
    gamma = fwhm / 2.0
    lorentz = gamma**2 / ((x - center) ** 2 + gamma**2)
    eta = min(max(eta, 0.0), 1.0)
    return amplitude * (eta * lorentz + (1.0 - eta) * gauss)


def pseudo_voigt(x, center, fwhm, amplitude, eta, background):
    """Pseudo-Voigt profile: η·Lorentzian + (1−η)·Gaussian, plus a flat background."""
    return background + _pv(np.asarray(x, dtype=float), center, fwhm, amplitude, eta)


def ka2_position(two_theta_ka1, wl_ratio):
    """2θ of the Kα2 line given the Kα1 2θ and λ(Kα2)/λ(Kα1) (Bragg's law)."""
    s = np.clip(wl_ratio * np.sin(np.radians(np.asarray(two_theta_ka1) / 2.0)), -1.0, 1.0)
    return 2.0 * np.degrees(np.arcsin(s))


def fit_peak(
    x, y, index: int, window: float | None = None, *,
    wavelength: float | None = None, ka2_wavelength: float | None = None,
    ka2_ratio: float = 0.5, ka2_offset: float | None = None,
    profile: str = "pseudo-Voigt",
) -> PeakFit | None:
    """Fit a pseudo-Voigt (+ linear background) to the peak at ``index``.

    ``window`` is the ± fit range in degrees; by default it adapts to the peak
    (8 × its measured width, 0.5°–10°) so narrow substrate lines aren't swamped by
    neighbouring features. Pass ``wavelength`` and ``ka2_wavelength`` (Å) to fit the
    Kα1/Kα2 doublet — the reported FWHM is then the Kα1 width. Returns ``None`` if
    there aren't enough points or the fit doesn't converge.
    """
    from scipy.optimize import curve_fit

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    i = int(index)
    if not (0 <= i < x.size):
        return None
    fwhm0 = peak_fwhm(x, y, i)[0]
    if window is None:
        window = float(np.clip(8.0 * fwhm0, 0.5, 10.0)) if np.isfinite(fwhm0) else 2.0
    sel = np.abs(x - x[i]) <= window
    xf, yf = x[sel], y[sel]
    if xf.size < 8:
        return None

    base0 = float(np.min(yf))
    amp0 = float(y[i] - base0)
    if amp0 <= 0:
        return None
    if not np.isfinite(fwhm0) or fwhm0 <= 0:
        fwhm0 = max((xf[-1] - xf[0]) / 6.0, 1e-3)
    x0 = float(x[i])

    offset = float(ka2_offset) if ka2_offset else 0.0
    doublet = bool((wavelength and ka2_wavelength) or offset) and ka2_ratio > 0
    wl_ratio = float(ka2_wavelength / wavelength) if (doublet and not offset) else 1.0
    r2 = float(ka2_ratio) if doublet else 0.0
    # Fixed line shape: pin η (0 = Gaussian, 1 = Lorentzian).
    eta_fix = {"gaussian": 0.0, "lorentzian": 1.0}.get(profile.lower())

    def model(xx, c, w, a, eta, bg, slope):
        if eta_fix is not None:
            eta = eta_fix
        out = bg + slope * (xx - x0) + _pv(xx, c, w, a, eta)
        if doublet:
            pos = c + offset if offset else ka2_position(c, wl_ratio)
            out = out + _pv(xx, pos, w, a * r2, eta)
        return out

    span = float(xf[-1] - xf[0])
    p0 = [x0, fwhm0 * (0.8 if doublet else 1.0), amp0, 0.5, base0, 0.0]
    bounds = (
        [xf.min(), 1e-4, 0.0, 0.0, -abs(amp0), -np.inf],
        [xf.max(), span, amp0 * 5 + 1.0, 1.0, float(np.max(yf)), np.inf],
    )
    try:
        popt, _ = curve_fit(model, xf, yf, p0=p0, bounds=bounds, maxfev=20000)
    except Exception:  # noqa: BLE001 — non-convergence, singular Jacobian, etc.
        return None

    c, w, a, eta, bg, slope = (float(v) for v in popt)
    if eta_fix is not None:
        eta = eta_fix
    resid = yf - model(xf, *popt)
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((yf - np.mean(yf)) ** 2)) or 1.0
    # Pseudo-Voigt area = amp·[η·π·γ + (1−η)·σ·√(2π)]  (Kα1 component).
    sigma = w / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    area = a * (eta * np.pi * (w / 2.0) + (1.0 - eta) * sigma * np.sqrt(2.0 * np.pi))
    return PeakFit(
        center=c, fwhm=w, amplitude=a, eta=eta,
        background=bg + slope * (c - x0), area=float(area),
        r_squared=1.0 - ss_res / ss_tot, slope=slope,
        ka2_ratio=r2, ka_ratio_wl=wl_ratio, ka2_offset=offset if doublet else 0.0,
    )
