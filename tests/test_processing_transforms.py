"""Tests for the display/analysis transforms surfaced in the Processing panel."""

from __future__ import annotations

import numpy as np

from xrdlab.core.processing import (
    background_als,
    smooth_savgol,
    strip_kalpha2,
)


def _peak(x, c, s, h):
    return h * np.exp(-((x - c) ** 2) / (2 * s**2))


def test_background_als_removes_slope():
    x = np.linspace(20, 80, 2000)
    y = _peak(x, 50, 0.2, 1000) + 5 * (x - 20) + 50  # ramp + offset background
    bg = background_als(y)
    resid = y - bg
    # away from the peak the residual should be near zero (background removed)
    off = np.abs(x - 50) > 3
    assert np.median(resid[off]) < 20
    # the peak survives
    assert resid[np.argmin(np.abs(x - 50))] > 800


def test_smooth_preserves_length_and_reduces_noise():
    rng = np.random.default_rng(0)
    x = np.linspace(20, 80, 1500)
    clean = _peak(x, 50, 0.3, 1000)
    noisy = clean + rng.normal(0, 20, x.size)
    sm = smooth_savgol(noisy, window=11, poly=3)
    assert sm.shape == noisy.shape
    assert np.std(sm - clean) < np.std(noisy - clean)


def test_strip_kalpha2_preserves_length_and_lowers_total():
    x = np.linspace(20, 80, 3000)
    y = _peak(x, 50, 0.1, 1000)
    out = strip_kalpha2(x, y, 1.5406, 1.5444, ratio=0.5)
    assert out.shape == y.shape
    assert out.sum() < y.sum()          # the Kα2 satellite contribution removed
    assert out.min() >= 0.0             # clipped non-negative
