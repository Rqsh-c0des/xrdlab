"""Parser tests against the real Panalytical ScN/GaN scans."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from xrdlab.core.pattern import Pattern
from xrdlab.core.xrdml import read_xrdml, read_xrdml_single

DATA = Path(__file__).parent / "data"
FILES = [
    DATA / "XRD_5289_Al2O3_ScN_260619_1610.xrdml",
    DATA / "XRD_5292_GaN_ScN_260713_1551.xrdml",
]
# Real lab measurements are kept out of the public repository (unpublished data);
# these tests run where the files exist and skip elsewhere. The synthetic-file
# tests in test_hrxrd.py cover the XRDML format on every machine.
pytestmark = pytest.mark.skipif(not all(f.exists() for f in FILES),
                                reason="real measurement files not present")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_reads_single_pattern(path: Path):
    pattern = read_xrdml_single(path)
    assert isinstance(pattern, Pattern)
    # x-axis reconstructed to the same length as the counts list
    assert len(pattern.two_theta) == len(pattern.intensity)
    assert len(pattern) > 100
    # 2theta window: a sane powder range (these scans run ~10-15 up to ~120 deg)
    lo, hi = pattern.two_theta_range
    assert 5.0 <= lo <= 20.0
    assert 80.0 <= hi <= 130.0
    # Cu K-alpha1
    assert pattern.wavelength == pytest.approx(1.5405980, abs=1e-4)
    # monotonic increasing axis, finite intensities
    assert np.all(np.diff(pattern.two_theta) > 0)
    assert np.all(np.isfinite(pattern.intensity))


def test_read_xrdml_returns_list():
    patterns = read_xrdml(FILES[0])
    assert isinstance(patterns, list)
    assert len(patterns) >= 1
    assert all(isinstance(p, Pattern) for p in patterns)


def test_counts_are_positive_and_have_peaks():
    pattern = read_xrdml_single(FILES[1])
    assert pattern.intensity.min() >= 0
    # a real scan has a strong maximum well above the baseline
    assert pattern.intensity.max() > 10 * np.median(pattern.intensity)
