"""Tests for peak FWHM measurement and Scherrer crystallite size."""

from __future__ import annotations

import numpy as np
import pytest

from xrdlab.core.processing import peak_fwhm, scherrer_size

GAUSS_K = 2.0 * np.sqrt(2.0 * np.log(2.0))  # FWHM / sigma for a Gaussian


def _gaussian(x, center, sigma, height=100.0, base=0.0):
    return base + height * np.exp(-((x - center) ** 2) / (2.0 * sigma**2))


def test_fwhm_matches_gaussian():
    x = np.linspace(30, 40, 4001)
    sigma = 0.15
    y = _gaussian(x, 35.0, sigma, base=5.0)
    i = int(np.argmin(np.abs(x - 35.0)))
    fwhm, xl, xr, level = peak_fwhm(x, y, i)
    assert fwhm == pytest.approx(GAUSS_K * sigma, rel=1e-2)
    assert xl < 35.0 < xr
    assert level == pytest.approx(5.0 + 0.5 * 100.0, rel=1e-3)


def test_fwhm_on_sloped_background():
    """A linear background under the peak must not distort the width."""
    x = np.linspace(30, 40, 4001)
    sigma = 0.2
    y = _gaussian(x, 35.0, sigma) + 3.0 * (x - 30.0)
    i = int(np.argmin(np.abs(x - 35.0)))
    fwhm = peak_fwhm(x, y, i)[0]
    assert fwhm == pytest.approx(GAUSS_K * sigma, rel=2e-2)


def test_fwhm_robust_to_counting_noise():
    """A broad peak with Poisson noise: a noisy point near the apex must not
    truncate the width (the old strict-descent walk returned ~1/20 of it)."""
    rng = np.random.default_rng(3)
    x = np.linspace(70, 75, 400)  # 0.0125° steps, like the Empyrean scans
    sigma = 0.12
    y = rng.poisson(_gaussian(x, 72.6, sigma, height=2000, base=70)).astype(float)
    i = int(np.argmax(y))
    fwhm = peak_fwhm(x, y, i)[0]
    assert fwhm == pytest.approx(GAUSS_K * sigma, rel=0.15)


def test_fwhm_edge_returns_nan():
    x = np.linspace(30, 40, 101)
    y = np.linspace(1, 2, 101)
    assert np.isnan(peak_fwhm(x, y, 0)[0])
    assert np.isnan(peak_fwhm(x, y, len(x) - 1)[0])


def test_fwhm_monotonic_no_peak():
    x = np.linspace(30, 40, 201)
    y = np.linspace(0, 10, 201)  # no local max
    assert np.isnan(peak_fwhm(x, y, 100)[0])


def test_scherrer_size_reasonable():
    # 0.1° FWHM at 2θ=35°, Cu Kα1 → ~80 nm.
    size = scherrer_size(0.1, 35.0, 1.5406)
    assert 70 < size < 95


def test_scherrer_narrower_peak_bigger_size():
    a = scherrer_size(0.05, 35.0, 1.5406)
    b = scherrer_size(0.10, 35.0, 1.5406)
    assert a > b  # narrower peak → larger crystallites


def test_scherrer_invalid_fwhm_nan():
    assert np.isnan(scherrer_size(0.0, 35.0, 1.5406))
    assert np.isnan(scherrer_size(float("nan"), 35.0, 1.5406))
