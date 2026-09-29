"""High-resolution XRD analysis for epitaxial films (pure numpy; no GUI).

Everything here takes plain numbers/arrays so it can be tested and scripted.
Angles are in degrees at the interface and converted internally.

Implemented
-----------
* Scan-axis helpers — which angle a pattern's x-data is (2θ, ω, φ, χ).
* Rocking curves (ω scans): FWHM (fit or data, ° and arcsec), peak, line shape.
* Threading-dislocation density from rocking-curve widths (Dunn & Kogh mosaic
  model, ρ = β² / (4.35 b²)), with Burgers-vector presets for common materials.
* Mosaic **tilt / twist** from symmetric + skew-symmetric (χ-inclined) rocking
  curves:  β(χ)² = (β_tilt cos χ)² + (β_twist sin χ)².
* Williamson–Hall for ω scans (Metzger / Moram & Vickers): β_ω sinθ/λ vs sinθ/λ
  → slope = tilt, intercept y₀ → lateral coherence length L∥ = 0.9 / (2 y₀).
* Williamson–Hall for 2θ-ω scans: β cosθ = Kλ/D + 4ε sinθ → vertical coherence
  length (size) D and microstrain ε.
* Film thickness from Pendellösung / Laue thickness fringes.
* Reciprocal-space maps: (ω, 2θ) → (Qx, Qz), peak finding, in-/out-of-plane lattice
  parameters, strain and degree of relaxation.
* φ-scan symmetry (n-fold rotational symmetry, twin/domain count).

Q is expressed without the 2π factor (Å⁻¹, |Q| = 1/d), the usual RSM convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "axis_of", "axis_label", "is_two_theta", "fixed_two_theta",
    "MATERIALS", "burgers_vectors", "dislocation_density",
    "rocking_curve_metrics", "tilt_twist", "williamson_hall_omega",
    "williamson_hall", "fringe_thickness", "rsm_to_q", "rsm_grid", "rsm_peaks",
    "lattice_from_q", "relaxation", "phi_symmetry", "LinearFit",
]

_trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz")

# -- scan axes -----------------------------------------------------------------

_AXIS_LABEL = {
    "2Theta": "2θ (°)", "Omega": "ω (°)", "Phi": "φ (°)", "Chi": "χ (°)",
    "Z": "z (mm)", "X": "x (mm)", "Y": "y (mm)", "index": "point",
}


def axis_of(pattern) -> str:
    """Which angle the pattern's x-data is: '2Theta', 'Omega', 'Phi', 'Chi', …"""
    meta = getattr(pattern, "meta", {}) or {}
    return str(meta.get("x_axis") or "2Theta")


def axis_label(axis: str) -> str:
    return _AXIS_LABEL.get(axis, axis)


def is_two_theta(pattern) -> bool:
    return axis_of(pattern) == "2Theta"


def fixed_two_theta(pattern) -> float | None:
    """The detector 2θ held fixed during a non-2θ scan (e.g. a rocking curve)."""
    meta = getattr(pattern, "meta", {}) or {}
    v = (meta.get("fixed_positions") or {}).get("2Theta")
    return float(v) if v is not None else None


# -- materials / Burgers vectors ----------------------------------------------

# Lattice constants (Å) at room temperature, standard literature values.
MATERIALS: dict[str, dict] = {
    "GaN (wurtzite)": {"system": "hexagonal", "a": 3.189, "c": 5.185},
    "AlN (wurtzite)": {"system": "hexagonal", "a": 3.112, "c": 4.982},
    "InN (wurtzite)": {"system": "hexagonal", "a": 3.545, "c": 5.703},
    "ZnO (wurtzite)": {"system": "hexagonal", "a": 3.250, "c": 5.207},
    "ScN (rock-salt)": {"system": "cubic", "a": 4.501},
    "TiN (rock-salt)": {"system": "cubic", "a": 4.240},
    "Si": {"system": "cubic", "a": 5.431},
    "Ge": {"system": "cubic", "a": 5.658},
    "GaAs": {"system": "cubic", "a": 5.653},
    "InP": {"system": "cubic", "a": 5.869},
    "Al2O3 (sapphire)": {"system": "hexagonal", "a": 4.759, "c": 12.991},
    "SiC (4H)": {"system": "hexagonal", "a": 3.073, "c": 10.053},
}


def burgers_vectors(material: str) -> dict[str, float]:
    """Burgers-vector magnitudes (Å) by dislocation type.

    Hexagonal: screw b = c ⟨0001⟩, edge b = a ⅓⟨11̄20⟩, mixed b = √(a²+c²).
    Cubic (fcc-based): perfect ½⟨110⟩, b = a/√2 (same magnitude for all types).
    """
    m = MATERIALS[material]
    a = m["a"]
    if m["system"] == "hexagonal":
        c = m["c"]
        return {"screw": c, "edge": a, "mixed": float(np.hypot(a, c))}
    b = a / np.sqrt(2.0)
    return {"screw": b, "edge": b, "mixed": b}


def dislocation_density(fwhm_deg: float, b_angstrom: float) -> float:
    """Threading-dislocation density (cm⁻²) from a rocking-curve width.

    Dunn & Kogh (1957) mosaic-block model: ρ = β² / (4.35 b²), β the rocking-curve
    FWHM in radians. Use the symmetric (e.g. (0002)) width with the screw b for
    screw-type TDs, and the twist width (or a large-χ skew-symmetric reflection)
    with the edge b for edge-type TDs. It's an upper-bound estimate: instrumental
    broadening, curvature and finite size all add to β.
    """
    if not fwhm_deg or fwhm_deg <= 0 or not b_angstrom or b_angstrom <= 0:
        return float("nan")
    beta = np.radians(fwhm_deg)
    b_cm = b_angstrom * 1e-8
    return float(beta**2 / (4.35 * b_cm**2))


# -- rocking curves --------------------------------------------------------------

def rocking_curve_metrics(x, y, *, fit_kwargs: dict | None = None,
                          profile: str = "pseudo-Voigt",
                          instrument_fwhm_deg: float = 0.0) -> dict:
    """Measure the dominant peak of an ω scan.

    Returns position, data FWHM, fitted FWHM (Kα1 if the doublet is modelled),
    η, R², integrated intensity, and — if ``instrument_fwhm_deg`` is given — the
    instrument-corrected width (Gaussian quadrature). All widths in degrees plus
    ``*_arcsec`` twins.
    """
    from xrdlab.core.fitting import fit_peak
    from xrdlab.core.processing import corrected_fwhm, peak_fwhm

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    i = int(np.argmax(y))
    data_fwhm = peak_fwhm(x, y, i)[0]
    fit = fit_peak(x, y, i, profile=profile, **(fit_kwargs or {}))
    ok = fit is not None and fit.r_squared > 0.8
    width = fit.fwhm if ok else data_fwhm
    out = {
        "peak": float(fit.center if ok else x[i]),
        "peak_counts": float(y[i]),
        "fwhm_data": float(data_fwhm),
        "fwhm_fit": float(fit.fwhm) if ok else float("nan"),
        "fwhm": float(width),
        "eta": float(fit.eta) if ok else float("nan"),
        "r_squared": float(fit.r_squared) if fit else float("nan"),
        "area": float(fit.area) if ok else float(_trapz(y - np.min(y), x)),
        "fit": fit if ok else None,
        "doublet": bool(ok and fit.ka2_ratio),
    }
    out["fwhm_corrected"] = (corrected_fwhm(width, instrument_fwhm_deg)
                             if instrument_fwhm_deg else float(width))
    for k in ("fwhm_data", "fwhm_fit", "fwhm", "fwhm_corrected"):
        out[k + "_arcsec"] = out[k] * 3600.0 if np.isfinite(out[k]) else float("nan")
    return out


@dataclass
class LinearFit:
    slope: float
    intercept: float
    r_squared: float
    x: np.ndarray = field(repr=False)
    y: np.ndarray = field(repr=False)


def _linfit(x, y) -> LinearFit:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m, b = np.polyfit(x, y, 1)
    pred = m * x + b
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1.0
    return LinearFit(float(m), float(b), 1.0 - float(np.sum((y - pred) ** 2)) / ss_tot, x, y)


def tilt_twist(fwhm_deg, chi_deg) -> dict:
    """Mosaic tilt and twist from rocking curves at inclinations χ.

    Fits β(χ)² = (β_tilt cos χ)² + (β_twist sin χ)² by linear least squares on
    (cos²χ, sin²χ). χ = 0 for symmetric reflections (e.g. (0002)); χ is the angle
    between the reflecting plane and the surface for skew-symmetric ones (e.g.
    (101̄1) in GaN ≈ 61.96°). Needs χ spread to separate twist; with only symmetric
    data, twist is returned as nan. Widths in degrees.
    """
    b = np.asarray(fwhm_deg, dtype=float)
    chi = np.radians(np.asarray(chi_deg, dtype=float))
    ok = np.isfinite(b) & np.isfinite(chi) & (b > 0)
    b, chi = b[ok], chi[ok]
    if b.size == 0:
        return {"tilt": float("nan"), "twist": float("nan"), "n": 0}
    c2, s2 = np.cos(chi) ** 2, np.sin(chi) ** 2
    if b.size < 2 or np.ptp(s2) < 0.05:
        # Only (near-)symmetric data: tilt ≈ mean symmetric width, no twist.
        tilt = float(np.sqrt(np.mean(b**2 / np.maximum(c2, 1e-6))))
        return {"tilt": tilt, "twist": float("nan"), "n": int(b.size)}
    A = np.column_stack([c2, s2])
    from scipy.optimize import nnls

    (t2, w2), _ = nnls(A, b**2)
    pred = A @ np.array([t2, w2])
    ss_tot = float(np.sum((b**2 - np.mean(b**2)) ** 2)) or 1.0
    return {"tilt": float(np.sqrt(t2)), "twist": float(np.sqrt(w2)), "n": int(b.size),
            "r_squared": 1.0 - float(np.sum((b**2 - pred) ** 2)) / ss_tot}


def williamson_hall_omega(fwhm_deg, two_theta_deg, wavelength: float) -> dict:
    """Williamson–Hall for rocking curves of symmetric reflection orders.

    y = β_ω sinθ / λ,  x = sinθ / λ  →  slope = tilt (rad), intercept y₀ →
    lateral coherence length L∥ = 0.9 / (2 y₀) (Metzger et al. 1998; Moram &
    Vickers, Rep. Prog. Phys. 72, 036502, 2009). Needs ≥ 2 orders (0002/0004/0006).
    """
    beta = np.radians(np.asarray(fwhm_deg, dtype=float))
    th = np.radians(np.asarray(two_theta_deg, dtype=float) / 2.0)
    x = np.sin(th) / wavelength
    y = beta * np.sin(th) / wavelength
    if x.size < 2:
        return {"tilt_deg": float("nan"), "L_par_nm": float("nan"), "fit": None}
    f = _linfit(x, y)
    L = 0.9 / (2.0 * f.intercept) / 10.0 if f.intercept > 0 else float("nan")  # Å→nm
    return {"tilt_deg": float(np.degrees(f.slope)), "L_par_nm": L, "fit": f}


def williamson_hall(fwhm_deg, two_theta_deg, wavelength: float, K: float = 0.9) -> dict:
    """Classic Williamson–Hall on 2θ-ω peak widths (use one reflection family).

    β cosθ = Kλ/D + 4ε sinθ  (β in rad of 2θ). Returns D (nm, vertical coherence
    length / crystallite size), microstrain ε, and the fit. A negative slope or
    intercept means the data aren't broadening-dominated (e.g. resolution-limited).
    """
    beta = np.radians(np.asarray(fwhm_deg, dtype=float))
    th = np.radians(np.asarray(two_theta_deg, dtype=float) / 2.0)
    if beta.size < 2:
        return {"size_nm": float("nan"), "strain": float("nan"), "fit": None}
    f = _linfit(4.0 * np.sin(th), beta * np.cos(th))
    D = K * wavelength / f.intercept / 10.0 if f.intercept > 0 else float("nan")
    return {"size_nm": D, "strain": f.slope, "fit": f}


# Side maxima of sin²(z)/z² (roots of tan z = z) in units of π: the k-th Laue
# subsidiary maximum sits at z_k·(fringe period) from the Bragg peak.
_LAUE_MAXIMA = {1: 1.4303, 2: 2.4590, 3: 3.4709, 4: 4.4774, 5: 5.4815, 6: 6.4844,
                7: 7.4865, 8: 8.4881, 9: 9.4894, 10: 10.4904}

# -- thickness fringes -----------------------------------------------------------

def fringe_thickness(x, y, center_2theta: float, wavelength: float, *,
                     exclude_deg: float | None = None, window_deg: float = 3.0,
                     min_fringes: int = 2) -> dict:
    """Film thickness from Pendellösung / Laue thickness fringes around a Bragg peak.

    Side maxima n and n+1 obey 2t(sinθₙ₊₁ − sinθₙ)/λ = 1, so t = λ / (2 Δsinθ). The
    fringe maxima are found in the smoothed log-intensity on each side of the peak
    (excluding the central maximum, ±``exclude_deg``); consecutive spacings are
    combined (a skipped fringe counts as two spacings). Returns thickness (nm),
    the fringe positions used, and the spread between the two sides.
    """
    from scipy.signal import find_peaks

    from xrdlab.core.processing import peak_fwhm

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    sel = np.abs(x - center_2theta) <= window_deg
    xs, yr = x[sel], y[sel]
    if xs.size < 20:
        return {"thickness_nm": float("nan"), "fringes": [], "reason": "too few points"}
    step = float(np.median(np.diff(xs))) or 1e-4
    L = np.log10(np.clip(yr, 1.0, None))

    def smooth(v, k):
        k = max(1, int(k)) | 1
        return v if k <= 1 else np.convolve(v, np.ones(k) / k, mode="same")

    # Expected fringe period from the central maximum: for a Laue function the
    # FWHM ≈ 0.886 × the fringe spacing (extra broadening only makes it larger).
    i0 = int(np.argmin(np.abs(xs - center_2theta)))
    fw = peak_fwhm(xs, 10 ** smooth(L, 3), i0)[0]
    p_guess = fw / 0.886 if np.isfinite(fw) and fw > 0 else 0.2
    if exclude_deg is None:
        exclude_deg = 0.75 * fw if np.isfinite(fw) else 0.1
    if window_deg < 5.0 * p_guess:  # thin film: widely spaced fringes need room
        window_deg = 5.0 * p_guess
        sel = np.abs(x - center_2theta) <= window_deg
        xs, yr = x[sel], y[sel]
        L = np.log10(np.clip(yr, 1.0, None))
    # Refine the period by autocorrelation of the detrended log-intensity with the
    # central peak masked out; counting-noise wiggles have no preferred period.
    resid = L - smooth(L, 3 * p_guess / step)
    resid[np.abs(xs - center_2theta) <= exclude_deg] = 0.0
    resid = smooth(resid, p_guess / step / 8)
    r0 = resid - resid.mean()
    ac = np.correlate(r0, r0, mode="full")[r0.size - 1:]
    period = p_guess
    lo, hi = max(2, int(0.3 * p_guess / step)), int(1.6 * p_guess / step)
    if ac[0] > 0 and hi > lo + 2 and hi < ac.size - 1:
        seg = ac[lo:hi + 1]
        inner = np.where((seg[1:-1] > seg[:-2]) & (seg[1:-1] >= seg[2:]))[0] + 1
        if inner.size:  # a genuine periodicity is an interior maximum, not the edge
            j = lo + int(inner[np.argmax(seg[inner])])
            if ac[j] / ac[0] > 0.1:
                period = j * step
    def track(P):
        """Follow the fringe comb outward from the peak, one period at a time.

        Side maxima of a Laue function sit near ±(n + ½)·P (the first at ≈1.43 P).
        A maximum counts only if it rises above the valley before it by more than
        3σ of Poisson noise in the smoothed log-intensity, σ ≈ 0.434 / √(counts·k).
        Two consecutive misses end the walk (fringes have decayed into the noise).
        """
        kpts = max(1, int(P / step / 6)) | 1
        Ls = smooth(L, kpts)
        found: dict[int, list[tuple[int, float]]] = {-1: [], 1: []}
        for side in (-1, 1):
            prev, expected, misses = center_2theta, center_2theta + side * 1.43 * P, 0
            order = 1
            while misses < 2 and abs(expected - center_2theta) < window_deg - 0.3 * P:
                lo_x, hi_x = expected - 0.35 * P, expected + 0.35 * P
                m = np.where((xs >= lo_x) & (xs <= hi_x))[0]
                if m.size < 3:
                    break
                j = int(m[np.argmax(Ls[m])])
                a, b = sorted((int(np.argmin(np.abs(xs - prev))), j))
                valley = float(np.min(Ls[a:b + 1])) if b > a else Ls[j]
                sig = 3.0 * 0.434 / np.sqrt(max(10 ** Ls[j], 1.0) * kpts)
                interior = m[0] < j < m[-1]
                if interior and Ls[j] - valley >= sig and abs(xs[j] - center_2theta) > exclude_deg:
                    found[side].append((order, float(xs[j])))
                    prev, expected, misses = float(xs[j]), float(xs[j]) + side * P, 0
                else:
                    expected, misses = expected + side * P, misses + 1
                order += 1
        return found

    def z(k):  # position of the k-th Laue side maximum, in fringe periods
        return _LAUE_MAXIMA.get(k, k + 0.5)

    found = track(period)
    for _ in range(2):  # refine the period from what was found, then re-track
        per = [abs(xb - xa) / (z(kb) - z(ka)) for sd in (-1, 1)
               for (ka, xa), (kb, xb) in zip(found[sd], found[sd][1:])]
        if len(per) < 2:
            break
        period = float(np.median(per))
        found = track(period)
    fringes = sorted(x_ for sd in (-1, 1) for _k, x_ in found[sd])
    spacings = []
    for side in (-1, 1):
        # Δsinθ per fringe period, using the exact side-maximum positions (order-
        # aware, so a skipped fringe and the wider first spacings are handled).
        for (ka, a), (kb, b) in zip(found[side], found[side][1:]):
            ds = abs(np.sin(np.radians(b / 2.0)) - np.sin(np.radians(a / 2.0)))
            spacings.append((ds / (z(kb) - z(ka)), side))
    if len(spacings) < min_fringes:
        return {"thickness_nm": float("nan"), "fringes": fringes, "period_deg": period,
                "reason": "no regular thickness fringes found"}
    dsin = np.array([v for v, _ in spacings])
    t = wavelength / (2.0 * float(np.mean(dsin))) / 10.0  # Å → nm
    per_side = {}
    for side in (-1, 1):
        vals = [v for v, sd in spacings if sd == side]
        if vals:
            per_side["low" if side < 0 else "high"] = wavelength / (2 * np.mean(vals)) / 10
    spread = (abs(per_side["low"] - per_side["high"]) if len(per_side) == 2
              else float("nan"))
    return {"thickness_nm": t, "fringes": fringes, "n_spacings": int(dsin.size),
            "period_deg": period,
            "per_side_nm": per_side, "spread_nm": spread,
            "uncertainty_nm": t * float(np.std(dsin) / np.mean(dsin)) / np.sqrt(dsin.size)}


# -- reciprocal-space maps ---------------------------------------------------------

def rsm_to_q(omega_deg, two_theta_deg, wavelength: float):
    """(ω, 2θ) → (Qx, Qz) in Å⁻¹ (no 2π):  Qx = (cos ω − cos(2θ−ω))/λ,
    Qz = (sin ω + sin(2θ−ω))/λ. Qx < 0 for the grazing-incidence geometry."""
    w = np.radians(np.asarray(omega_deg, dtype=float))
    tt = np.radians(np.asarray(two_theta_deg, dtype=float))
    qx = (np.cos(w) - np.cos(tt - w)) / wavelength
    qz = (np.sin(w) + np.sin(tt - w)) / wavelength
    return qx, qz


def rsm_grid(qx, qz, intensity, bins: int = 200):
    """Bin scattered map points onto a regular (Qx, Qz) grid (mean intensity).

    Returns (qx_centers, qz_centers, grid[nz, nx]) with NaN where no data fell.
    """
    qx = np.asarray(qx, dtype=float)
    qz = np.asarray(qz, dtype=float)
    I = np.asarray(intensity, dtype=float)
    xe = np.linspace(qx.min(), qx.max(), bins + 1)
    ze = np.linspace(qz.min(), qz.max(), bins + 1)
    s, _, _ = np.histogram2d(qz, qx, bins=[ze, xe], weights=I)
    n, _, _ = np.histogram2d(qz, qx, bins=[ze, xe])
    with np.errstate(invalid="ignore", divide="ignore"):
        g = s / n
    return 0.5 * (xe[:-1] + xe[1:]), 0.5 * (ze[:-1] + ze[1:]), g


def rsm_peaks(qx, qz, intensity, n: int = 2, bins: int = 160,
              min_separation_cells: float = 3.0) -> list[dict]:
    """The ``n`` strongest *distinct* maxima of a map (e.g. substrate + film).

    Candidates are local maxima of a lightly smoothed log-intensity grid, ranked by
    height. A candidate is accepted only if it (1) stands clearly above the map
    background and (2) is separated from every accepted peak by a real dip — the
    intensity along the straight line between them falls below half its own — so
    the shoulder of one peak is never reported as a second peak. Positions are then
    refined to the intensity-weighted centroid of the raw points nearby.
    """
    qx = np.asarray(qx, dtype=float)
    qz = np.asarray(qz, dtype=float)
    I = np.asarray(intensity, dtype=float)
    xc, zc, g = rsm_grid(qx, qz, I, bins=bins)
    dx, dz = abs(xc[1] - xc[0]), abs(zc[1] - zc[0])
    floor = np.nanmin(g) if np.isfinite(g).any() else 1.0
    L = np.log10(np.clip(np.nan_to_num(g, nan=floor), 1.0, None))
    ker = np.ones(3) / 3.0
    L = np.apply_along_axis(lambda r: np.convolve(r, ker, mode="same"), 0, L)
    L = np.apply_along_axis(lambda r: np.convolve(r, ker, mode="same"), 1, L)

    bg = float(np.median(I))
    thresh = max(bg + 10.0 * np.sqrt(max(bg, 1.0)), 0.01 * float(I.max()))

    def local(px, pz, r=1.5):
        return (np.abs(qx - px) <= r * dx) & (np.abs(qz - pz) <= r * dz)

    def level(px, pz):
        m = local(px, pz)
        return float(np.median(I[m])) if m.any() else 0.0

    def dip_between(p, q) -> float:
        vals = []
        for t in np.linspace(0.1, 0.9, 17):
            v = level(p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
            vals.append(v)
        return min(vals) if vals else 0.0

    from scipy.ndimage import maximum_filter

    # Local maxima of the smoothed grid (empty cells are fine — the smoothed value
    # interpolates across them; each candidate is judged on the raw points nearby).
    is_max = (L == maximum_filter(L, size=5)) & (L > np.log10(max(thresh, 1.0)) - 0.5)
    cand = np.argwhere(is_max)
    cand = cand[np.argsort(L[is_max])[::-1]][:400]
    out: list[dict] = []
    for iz, ix in cand:
        px, pz = xc[ix], zc[iz]
        m = local(px, pz, r=2.5)
        if not m.any():
            continue
        w = I[m]
        px, pz = float(np.sum(qx[m] * w) / w.sum()), float(np.sum(qz[m] * w) / w.sum())
        h = level(px, pz)
        if h < thresh:
            continue
        if any(np.hypot((px - p["qx"]) / dx, (pz - p["qz"]) / dz) < min_separation_cells
               or dip_between((px, pz), (p["qx"], p["qz"])) > 0.5 * h for p in out):
            continue
        out.append({"qx": px, "qz": pz, "intensity": h})
        if len(out) >= n:
            break
    # Final position: background-subtracted centroid of the points above half
    # maximum within the peak's own basin — unbiased for a symmetric peak and far
    # less sensitive to sparse sampling than the few points of one grid cell.
    for k, p in enumerate(out):
        others = [o for j, o in enumerate(out) if j != k]
        for _ in range(3):
            r = np.hypot((qx - p["qx"]) / dx, (qz - p["qz"]) / dz)
            m = r < 12.0
            for o in others:  # keep points closer to this peak than to any other
                m &= r < np.hypot((qx - o["qx"]) / dx, (qz - o["qz"]) / dz)
            if not m.any():
                break
            top = float(np.max(I[m]))
            sel = m & (I - bg >= 0.5 * (top - bg))
            if sel.sum() < 3:
                break
            wgt = I[sel] - bg
            p["qx"] = float(np.sum(qx[sel] * wgt) / wgt.sum())
            p["qz"] = float(np.sum(qz[sel] * wgt) / wgt.sum())
    return sorted(out, key=lambda p: -p["intensity"])


def lattice_from_q(qx: float, qz: float, hkl, system: str) -> dict:
    """In-plane / out-of-plane lattice parameters from a map peak.

    ``system``:
      * "cubic (001)"      — (h k l) with l ∥ growth: a∥ = √(h²+k²)/|Qx|, a⊥ = l/Qz
      * "hexagonal (0001)" — (h k i l): a = √(4/3·(h²+hk+k²))/|Qx|, c = l/Qz
    Symmetric reflections (h = k = 0) give only the out-of-plane parameter.
    """
    h = [int(v) for v in hkl]
    out = {"d_par": 1.0 / abs(qx) if qx else float("inf"),
           "d_perp": 1.0 / qz if qz else float("inf")}
    if system.startswith("cubic"):
        hh, kk, ll = h[:3]
        g = np.hypot(hh, kk)
        out["a_par"] = g / abs(qx) if g and qx else float("nan")
        out["a_perp"] = ll / qz if ll and qz else float("nan")
    else:
        if len(h) == 4:
            hh, kk, _ii, ll = h
        else:
            hh, kk, ll = h
        g = np.sqrt(4.0 / 3.0 * (hh * hh + hh * kk + kk * kk))
        out["a_par"] = g / abs(qx) if g and qx else float("nan")   # a
        out["a_perp"] = ll / qz if ll and qz else float("nan")     # c
    return out


def relaxation(a_par_film: float, a_sub: float, a_bulk_film: float) -> float:
    """Degree of relaxation (%): 0 = fully strained (pseudomorphic), 100 = relaxed.

    R = (a∥,film − a_sub) / (a_bulk,film − a_sub) × 100, all in-plane parameters
    expressed in the same (film) cell.
    """
    den = a_bulk_film - a_sub
    return float((a_par_film - a_sub) / den * 100.0) if den else float("nan")


# -- φ scans ---------------------------------------------------------------------

def phi_symmetry(phi_deg, y, prominence_frac: float = 0.1) -> dict:
    """Peaks in a φ (in-plane rotation) scan and the implied n-fold symmetry.

    Returns peak positions, mean spacing, n-fold (360/spacing, rounded) and whether
    the count is a multiple of that (extra domains → rotational twins).
    """
    from scipy.signal import find_peaks

    phi = np.asarray(phi_deg, dtype=float)
    y = np.asarray(y, dtype=float)
    prom = prominence_frac * (np.nanmax(y) - np.nanmin(y))
    idx, _ = find_peaks(y, prominence=max(prom, 1e-9))
    pos = np.sort(phi[idx])
    if pos.size < 2:
        return {"peaks": pos.tolist(), "n_fold": pos.size or 0, "spacing": float("nan")}
    span = float(phi.max() - phi.min())
    d = np.diff(pos)
    if span >= 350:  # full rotation: include the wrap-around gap
        d = np.append(d, 360.0 - (pos[-1] - pos[0]))
    spacing = float(np.median(d))
    nfold = int(round(360.0 / spacing)) if spacing > 0 else 0
    return {"peaks": pos.tolist(), "n_peaks": int(pos.size), "spacing": spacing,
            "n_fold": nfold, "full_rotation": span >= 350,
            "intensities": y[idx][np.argsort(phi[idx])].tolist()}
