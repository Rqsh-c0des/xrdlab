"""Signal-processing helpers for diffraction patterns.

All functions are pure: they take arrays (or a :class:`Pattern`) and return new
arrays / patterns, never mutating the input. Display-only transforms (smoothing,
scaling) must never be baked into data destined for export.
"""

from __future__ import annotations

import numpy as np

from xrdlab.core.pattern import Pattern

# NOTE: scipy is imported lazily inside the functions that need it (background
# estimation, smoothing). Keeping it out of module import means launching the app —
# which only needs ``normalize`` (pure numpy) from here — never pays scipy's ~1s+
# (much more on a cold/AV-scanned disk) load until you actually run those tools.

__all__ = [
    "to_cps",
    "normalize",
    "scale",
    "background_als",
    "background_poly",
    "subtract_background",
    "strip_kalpha2",
    "smooth_savgol",
    "peak_fwhm",
    "scherrer_size",
    "corrected_fwhm",
    "decimate_for_display",
]


def decimate_for_display(x, y, max_points: int = 6000):
    """Down-sample ``(x, y)`` for fast plotting while preserving peak shape.

    Splits the data into ``max_points`` blocks and keeps, per block, the points of
    minimum *and* maximum y (so no peak or valley is skipped). Returns the original
    arrays unchanged when they already fit. This is **display only** — never feed the
    result to fitting/FWHM/export, which must use the full-resolution data.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = x.size
    if n <= max_points or n < 4:
        return x, y
    nblocks = max_points // 2
    edges = np.linspace(0, n, nblocks + 1, dtype=int)
    keep = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        seg = y[a:b]
        lo = a + int(np.argmin(seg))
        hi = a + int(np.argmax(seg))
        keep.extend((lo, hi) if lo != hi else (lo,))
    idx = np.unique(np.array(keep, dtype=int))
    return x[idx], y[idx]


def to_cps(pattern: Pattern) -> Pattern:
    """Return a copy with intensity in counts-per-second.

    Divides by ``meta['counting_time']`` when present; otherwise returns an
    unchanged copy.
    """
    t = pattern.meta.get("counting_time")
    if not t:
        return pattern.copy()
    out = pattern.with_intensity(pattern.intensity / float(t))
    out.meta["intensity_unit"] = "cps"
    return out


def normalize(y: np.ndarray, mode: str = "max") -> np.ndarray:
    """Normalize an intensity array.

    Parameters
    ----------
    y : ndarray
    mode : {"max", "area"}
        ``max`` scales the peak to 1; ``area`` scales the integral to 1.
    """
    y = np.asarray(y, dtype=float)
    if mode == "max":
        peak = np.nanmax(y)
        return y / peak if peak else y.copy()
    if mode == "area":
        area = (getattr(np, "trapezoid", None) or np.trapz)(y)
        return y / area if area else y.copy()
    raise ValueError(f"unknown normalize mode: {mode!r}")


def scale(y: np.ndarray, mode: str = "linear") -> np.ndarray:
    """Apply a display scaling: ``linear``, ``sqrt`` or ``log``.

    ``sqrt`` and ``log`` clip negatives to zero first. ``log`` uses ``log10`` of
    ``y + 1`` so zero counts map to zero.
    """
    y = np.asarray(y, dtype=float)
    if mode == "linear":
        return y.copy()
    if mode == "sqrt":
        return np.sqrt(np.clip(y, 0, None))
    if mode == "log":
        return np.log10(np.clip(y, 0, None) + 1.0)
    raise ValueError(f"unknown scale mode: {mode!r}")


def background_als(
    y: np.ndarray, lam: float = 1e5, p: float = 0.01, niter: int = 10
) -> np.ndarray:
    """Asymmetric least-squares (Eilers) baseline estimate.

    Parameters
    ----------
    y : ndarray
    lam : float
        Smoothness. Larger -> stiffer baseline (1e2..1e9 typical).
    p : float
        Asymmetry (0<p<1). Smaller -> baseline hugs the valleys.
    niter : int
        Number of reweighting iterations.
    """
    from scipy import sparse
    from scipy.sparse.linalg import spsolve

    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 3:
        return np.zeros_like(y)
    d = sparse.eye(n, format="csc")
    d = d[1:] - d[:-1]  # first difference
    d = d[1:] - d[:-1]  # second difference
    dtd = lam * (d.transpose() @ d)
    w = np.ones(n)
    z = y.copy()
    for _ in range(niter):
        wdiag = sparse.spdiags(w, 0, n, n)
        z = spsolve((wdiag + dtd).tocsc(), w * y)
        w = p * (y > z) + (1.0 - p) * (y < z)
    return z


def background_poly(x: np.ndarray, y: np.ndarray, degree: int = 3) -> np.ndarray:
    """Polynomial baseline of the given ``degree`` fit to ``(x, y)``."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    coeffs = np.polyfit(x, y, degree)
    return np.polyval(coeffs, x)


def subtract_background(pattern: Pattern, method: str = "als", **kw) -> Pattern:
    """Return a copy with the estimated background removed.

    method : {"als", "poly"}
        Extra keyword args pass through to :func:`background_als` /
        :func:`background_poly`.
    """
    if method == "als":
        bkg = background_als(pattern.intensity, **kw)
    elif method == "poly":
        bkg = background_poly(pattern.two_theta, pattern.intensity, **kw)
    else:
        raise ValueError(f"unknown background method: {method!r}")
    out = pattern.with_intensity(pattern.intensity - bkg)
    out.meta["background_method"] = method
    return out


def strip_kalpha2(
    x: np.ndarray,
    y: np.ndarray,
    wl_ka1: float,
    wl_ka2: float,
    ratio: float = 0.5,
) -> np.ndarray:
    """Rachinger Kα2 stripping.

    Removes the Kα2 contribution assuming an intensity ratio ``ratio`` (Kα2/Kα1)
    and the Bragg-law angular offset between the two wavelengths. Returns the
    Kα1-only intensity on the original ``x`` grid.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    theta = np.radians(x / 2.0)
    # 2θ shift of the Kα2 line: differentiate Bragg law, dλ/λ = cotθ dθ.
    dtheta_deg = np.degrees(np.tan(theta) * (wl_ka2 - wl_ka1) / wl_ka1) * 2.0
    stripped = y.copy()
    # Sequential subtraction from low angle upward (Rachinger).
    for i in range(len(x)):
        x2 = x[i] + dtheta_deg[i]
        contrib = ratio * stripped[i]
        # distribute the Kα2 satellite onto the two nearest bins at x2
        j = np.searchsorted(x, x2)
        if 0 < j < len(x):
            frac = (x2 - x[j - 1]) / (x[j] - x[j - 1])
            stripped[j - 1] -= contrib * (1 - frac)
            stripped[j] -= contrib * frac
    return np.clip(stripped, 0, None)


def _half_crossing(x, y, i, step, stop, level) -> float:
    """Interpolated x where y first crosses ``level`` going from i toward ``stop``."""
    j = i
    while j != stop:
        nj = j + step
        if (y[j] - level) * (y[nj] - level) <= 0 and y[nj] != y[j]:
            t = (level - y[j]) / (y[nj] - y[j])
            return float(x[j] + t * (x[nj] - x[j]))
        j = nj
    return float("nan")


def peak_fwhm(x, y, index: int, max_half_width: float | None = 5.0):
    """Full width at half maximum of the peak at ``index`` (in x units, i.e. °2θ).

    The half-maximum level is taken above a *local* baseline: the descent from the
    apex is followed to the flanking valley on each side, and a straight baseline is
    drawn between those two valleys (so a peak on a sloped background is handled).
    The search is capped at ``max_half_width`` degrees per side so a neighbouring
    peak isn't mistaken for the valley.

    Returns
    -------
    (fwhm, x_left, x_right, half_level) : tuple of float
        ``(nan, nan, nan, nan)`` when the peak can't be bracketed (runs into a data
        edge, or is not a real maximum above its baseline).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = x.size
    i = int(index)
    nan4 = (float("nan"),) * 4
    if not (0 < i < n - 1):
        return nan4

    def valley(step: int) -> int:
        # Walk outward tracking the lowest point, and stop only once the signal has
        # clearly risen again — by more than counting noise (3·√counts) or 2 % of the
        # peak height. Stopping at the first uptick (as a strict descent would) lets
        # a single noisy point truncate the width of a broad, noisy peak.
        j = jmin = i
        while 0 <= j + step < n:
            j += step
            if max_half_width is not None and abs(x[j] - x[i]) > max_half_width:
                break
            if y[j] < y[jmin]:
                jmin = j
            else:
                floor = float(y[jmin])
                tol = max(3.0 * np.sqrt(max(floor, 0.0)), 0.02 * (float(y[i]) - floor))
                if y[j] > floor + tol:
                    break
        return jmin

    lv, rv = valley(-1), valley(1)
    if lv == i or rv == i:
        return nan4
    base_i = float(np.interp(x[i], [x[lv], x[rv]], [y[lv], y[rv]]))
    peak = float(y[i])
    if peak <= base_i:
        return nan4
    level = base_i + 0.5 * (peak - base_i)
    xl = _half_crossing(x, y, i, -1, lv, level)
    xr = _half_crossing(x, y, i, 1, rv, level)
    if np.isnan(xl) or np.isnan(xr) or xr <= xl:
        return nan4
    return (xr - xl, xl, xr, level)


def corrected_fwhm(fwhm_deg: float, instrument_fwhm_deg: float) -> float:
    """Sample broadening with instrumental broadening removed (Gaussian quadrature).

    ``β_sample = sqrt(β_measured² − β_instr²)``. Returns ``nan`` if the measured
    width is at or below the instrument's (i.e. resolution-limited).
    """
    if not fwhm_deg or fwhm_deg <= 0 or np.isnan(fwhm_deg):
        return float("nan")
    instr = instrument_fwhm_deg or 0.0
    diff = fwhm_deg**2 - instr**2
    return float(np.sqrt(diff)) if diff > 0 else float("nan")


def scherrer_size(
    fwhm_deg: float, two_theta_deg: float, wavelength_a: float,
    shape_factor: float = 0.9, instrument_fwhm_deg: float = 0.0,
) -> float:
    """Scherrer crystallite size in **nm** from a peak's FWHM.

    ``τ = K·λ / (β·cosθ)`` with β the FWHM in radians and θ half the peak 2θ.
    When ``instrument_fwhm_deg`` is given, β is first corrected for instrumental
    broadening (Gaussian: ``sqrt(β²−β_instr²)``) so the size is quantitative;
    otherwise it's an **upper-bound** estimate. Returns ``nan`` for a non-positive
    or fully resolution-limited width.
    """
    if not fwhm_deg or fwhm_deg <= 0 or np.isnan(fwhm_deg):
        return float("nan")
    if instrument_fwhm_deg:
        fwhm_deg = corrected_fwhm(fwhm_deg, instrument_fwhm_deg)
        if np.isnan(fwhm_deg):
            return float("nan")
    beta = np.radians(fwhm_deg)
    theta = np.radians(two_theta_deg / 2.0)
    denom = beta * np.cos(theta)
    if denom == 0:
        return float("nan")
    tau_angstrom = shape_factor * wavelength_a / denom
    return float(tau_angstrom / 10.0)  # Å → nm


def smooth_savgol(y: np.ndarray, window: int = 11, poly: int = 3) -> np.ndarray:
    """Savitzky–Golay smoothing (display only).

    ``window`` is forced odd and larger than ``poly``; short arrays are returned
    unchanged.
    """
    from scipy.signal import savgol_filter

    y = np.asarray(y, dtype=float)
    if window % 2 == 0:
        window += 1
    if len(y) <= window or window <= poly:
        return y.copy()
    return savgol_filter(y, window_length=window, polyorder=poly)
