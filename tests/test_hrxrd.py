"""HRXRD analysis: known-answer tests on synthetic data, plus XRDML reading of
rocking curves, φ scans and reciprocal-space maps."""

from __future__ import annotations

import numpy as np
import pytest

from xrdlab.core import hrxrd
from xrdlab.core.fitting import doublet_kwargs
from xrdlab.core.xrdml import is_area_measurement, read_xrdml, read_xrdml_area

import xrdml_synth as synth

WL = 1.540598


# -- reading ---------------------------------------------------------------------

def test_rocking_curve_reads_omega_axis(tmp_path):
    p = read_xrdml(synth.rocking_curve(tmp_path / "rc.xrdml"))[0]
    assert hrxrd.axis_of(p) == "Omega"
    assert p.two_theta.min() == pytest.approx(16.285) and p.two_theta.max() == pytest.approx(18.285)
    assert hrxrd.fixed_two_theta(p) == pytest.approx(34.57)
    assert p.meta["kalpha1_only"] is True
    assert doublet_kwargs(p) == {}  # monochromator → no Kα2 to model


def test_rocking_curve_without_monochromator_uses_constant_offset(tmp_path):
    p = read_xrdml(synth.rocking_curve(tmp_path / "rc.xrdml", monochromator=False))[0]
    kw = doublet_kwargs(p)
    # Δω = θ(Kα2) − θ(Kα1) at 2θ = 34.57°: ≈ 0.043°
    assert kw["ka2_offset"] == pytest.approx(0.0432, abs=0.002)


def test_phi_scan_reads_phi_axis(tmp_path):
    p = read_xrdml(synth.phi_scan(tmp_path / "phi.xrdml"))[0]
    assert hrxrd.axis_of(p) == "Phi"
    assert p.two_theta.max() > 350


def test_area_map_detected_and_read(tmp_path):
    f = synth.area_map(tmp_path / "rsm.xrdml", peaks=[(-0.3, 0.6, 0.002, 1e4)])
    assert is_area_measurement(f)
    m = read_xrdml_area(f)
    assert m["n_scans"] == 41 and m["omega"].size == 41 * 301
    assert m["kalpha1_only"] is True


def test_real_coupled_scan_is_not_an_area_map(tmp_path):
    f = synth.write_xrdml(tmp_path / "gonio.xrdml", [synth._scan(
        "Gonio", {"2Theta": np.linspace(15, 120, 500), "Omega": np.linspace(7.5, 60, 500)},
        np.full(500, 100))])
    assert not is_area_measurement(f)
    assert hrxrd.axis_of(read_xrdml(f)[0]) == "2Theta"


# -- rocking curves / dislocations ---------------------------------------------

def test_rocking_curve_fwhm(tmp_path):
    p = read_xrdml(synth.rocking_curve(tmp_path / "rc.xrdml", fwhm=0.08))[0]
    m = hrxrd.rocking_curve_metrics(p.two_theta, p.intensity)
    assert m["fwhm"] == pytest.approx(0.08, rel=0.03)
    assert m["fwhm_arcsec"] == pytest.approx(288, rel=0.03)
    assert m["peak"] == pytest.approx(17.285, abs=0.002)


def test_doublet_rocking_curve_reports_ka1_width(tmp_path):
    """Kα2 at +Δω broadens an unmonochromated RC; the doublet fit recovers Kα1."""
    x = np.linspace(16.3, 18.3, 1601)
    off = 0.0432
    y = 20 + synth.pv(x, 17.285, 0.05, 5e4) + synth.pv(x, 17.285 + off, 0.05, 2.5e4)
    single = hrxrd.rocking_curve_metrics(x, y)
    dbl = hrxrd.rocking_curve_metrics(x, y, fit_kwargs={"ka2_offset": off,
                                                        "ka2_ratio": 0.5})
    assert dbl["fwhm_fit"] == pytest.approx(0.05, rel=0.03)
    assert single["fwhm_fit"] > 0.07


def test_dunn_kogh_density():
    # β = 300″ on GaN (0002), b = c = 5.185 Å  → ~5.6e8 cm⁻²
    rho = hrxrd.dislocation_density(300 / 3600, hrxrd.burgers_vectors("GaN (wurtzite)")["screw"])
    assert rho == pytest.approx(np.radians(300 / 3600) ** 2 / (4.35 * (5.185e-8) ** 2))
    assert 1e8 < rho < 1e9


def test_burgers_vectors():
    b = hrxrd.burgers_vectors("GaN (wurtzite)")
    assert b["screw"] == 5.185 and b["edge"] == 3.189
    assert hrxrd.burgers_vectors("ScN (rock-salt)")["edge"] == pytest.approx(4.501 / np.sqrt(2))


def test_tilt_twist_recovers_known_values():
    tilt, twist = 0.06, 0.18
    chi = np.array([0.0, 43.2, 61.96, 75.0, 90.0])
    beta = np.sqrt((tilt * np.cos(np.radians(chi))) ** 2 + (twist * np.sin(np.radians(chi))) ** 2)
    r = hrxrd.tilt_twist(beta, chi)
    assert r["tilt"] == pytest.approx(tilt, rel=1e-6)
    assert r["twist"] == pytest.approx(twist, rel=1e-6)


def test_tilt_only_from_symmetric():
    r = hrxrd.tilt_twist([0.05, 0.05], [0, 0])
    assert r["tilt"] == pytest.approx(0.05) and np.isnan(r["twist"])


def test_williamson_hall_omega():
    tilt_rad, L = np.radians(0.05), 200.0  # L∥ in Å
    tt = np.array([34.57, 72.9, 126.0])  # GaN 0002/0004/0006
    s = np.sin(np.radians(tt / 2)) / WL
    beta = (tilt_rad * s + 0.9 / (2 * L)) / s  # rad
    r = hrxrd.williamson_hall_omega(np.degrees(beta), tt, WL)
    assert r["tilt_deg"] == pytest.approx(0.05, rel=1e-6)
    assert r["L_par_nm"] == pytest.approx(20.0, rel=1e-6)


def test_williamson_hall_size_strain():
    D, eps = 500.0, 2e-3  # Å, dimensionless
    tt = np.array([34.4, 72.5, 116.9])
    th = np.radians(tt / 2)
    beta = (0.9 * WL / D + 4 * eps * np.sin(th)) / np.cos(th)
    r = hrxrd.williamson_hall(np.degrees(beta), tt, WL)
    assert r["size_nm"] == pytest.approx(50.0, rel=1e-6)
    assert r["strain"] == pytest.approx(eps, rel=1e-6)


# -- thickness fringes ------------------------------------------------------------

def _laue_scan(t_nm, *, peak=8e4, bg=20.0, n=8001, seed=5):
    """Poisson-noisy Laue-fringe 2θ scan of a (111) ScN film with a *whole* number
    of planes (a fractional count gives an unphysical spike at the Bragg angle)."""
    d = 2.598  # ScN (111) spacing, Å
    N = round(t_nm * 10 / d)
    tt = np.linspace(28.0, 41.0, n)
    phase = np.pi * (2 * np.sin(np.radians(tt / 2)) / WL) * d
    lau = np.sin(N * phase) ** 2 / np.maximum(np.sin(phase) ** 2, 1e-12) / N**2
    y = np.random.default_rng(seed).poisson(bg + peak * lau).astype(float)
    return tt, y, N * d / 10.0


@pytest.mark.parametrize("t_nm", [10.0, 25.0, 60.0, 150.0])
def test_fringe_thickness(t_nm):
    tt, y, t_true = _laue_scan(t_nm)
    r = hrxrd.fringe_thickness(tt, y, float(tt[np.argmax(y)]), WL, window_deg=2.5)
    assert r["thickness_nm"] == pytest.approx(t_true, rel=0.03)


def test_fringe_thickness_weak_signal_error_bar_is_honest():
    tt, y, t_true = _laue_scan(40.0, peak=1e4, bg=60.0)
    r = hrxrd.fringe_thickness(tt, y, float(tt[np.argmax(y)]), WL)
    assert abs(r["thickness_nm"] - t_true) <= 3 * r["uncertainty_nm"] + 0.02 * t_true


def test_fringe_thickness_none_on_smooth_peak():
    tt = np.linspace(30, 40, 4001)
    y = 20 + synth.pv(tt, 35, 0.2, 1e4)
    assert np.isnan(hrxrd.fringe_thickness(tt, y, 35.0, WL)["thickness_nm"])


# -- reciprocal-space maps --------------------------------------------------------

def test_rsm_q_symmetric_reflection():
    # Symmetric: ω = θ → Qx = 0, Qz = 2 sinθ / λ = 1/d
    qx, qz = hrxrd.rsm_to_q(17.285, 34.57, WL)
    assert qx == pytest.approx(0.0, abs=1e-12)
    assert qz == pytest.approx(2 * np.sin(np.radians(17.285)) / WL)


def test_rsm_peaks_lattice_and_relaxation(tmp_path):
    """GaN(10-15)-like asymmetric map: substrate + partially relaxed film."""
    a_sub, c_sub = 3.112, 4.982     # AlN template (hexagonal)
    a0, c0 = 3.189, 5.185           # bulk GaN
    a_film, c_film = 3.150, 5.200   # partially relaxed film
    hkl = (1, 0, -1, 5)
    g = np.sqrt(4 / 3)
    sub = (-g / a_sub, 5 / c_sub)
    film = (-g / a_film, 5 / c_film)
    # Choose angles that cover both peaks: invert Q → (ω, 2θ) for the midpoint.
    qxm, qzm = (sub[0] + film[0]) / 2, (sub[1] + film[1]) / 2
    Q = np.hypot(qxm, qzm)
    tt = 2 * np.degrees(np.arcsin(Q * WL / 2))
    om = tt / 2 + np.degrees(np.arctan2(-qxm, qzm))  # Qx = -Q·sin(ω-θ)
    f = synth.area_map(tmp_path / "rsm.xrdml", tt_center=tt, tt_span=9.0,
                       off_center=om - tt / 2, off_span=2.0, n_scans=61,
                       peaks=[(*sub, 0.0015, 4e4), (*film, 0.002, 1e4)])
    m = read_xrdml_area(f)
    qx, qz = hrxrd.rsm_to_q(m["omega"], m["two_theta"], m["wavelength"])
    peaks = hrxrd.rsm_peaks(qx, qz, m["intensity"], n=2)
    assert len(peaks) == 2
    s, fl = peaks[0], peaks[1]  # strongest first = substrate
    assert s["qx"] == pytest.approx(sub[0], abs=4e-4) and s["qz"] == pytest.approx(sub[1], abs=4e-4)
    lf = hrxrd.lattice_from_q(fl["qx"], fl["qz"], hkl, "hexagonal (0001)")
    assert lf["a_par"] == pytest.approx(a_film, abs=0.01)
    assert lf["a_perp"] == pytest.approx(c_film, abs=0.01)
    R = hrxrd.relaxation(lf["a_par"], a_sub, a0)
    assert R == pytest.approx((a_film - a_sub) / (a0 - a_sub) * 100, abs=12)


def test_lattice_from_q_cubic():
    a, hkl = 5.431, (2, 2, 4)
    qx, qz = -np.hypot(2, 2) / a, 4 / a
    r = hrxrd.lattice_from_q(qx, qz, hkl, "cubic (001)")
    assert r["a_par"] == pytest.approx(a) and r["a_perp"] == pytest.approx(a)


# -- φ scans ----------------------------------------------------------------------

@pytest.mark.parametrize("n", [2, 3, 4, 6, 12])
def test_phi_symmetry(tmp_path, n):
    p = read_xrdml(synth.phi_scan(tmp_path / "phi.xrdml", n_fold=n))[0]
    r = hrxrd.phi_symmetry(p.two_theta, p.intensity)
    assert r["n_fold"] == n and r["n_peaks"] == n
