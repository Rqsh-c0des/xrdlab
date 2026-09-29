"""Filename → label parsing, including the growth-temperature series convention."""

from __future__ import annotations

import pytest

from xrdlab import config
from xrdlab.core.naming import canonical_formula, label_for

DEFAULT = config.DEFAULT_FILENAME_PATTERN
FIELD = config.DEFAULT_FILENAME_FIELD


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("XRD_5306_ScN-Al2O3_600C", "ScN/Al₂O₃ 600 °C"),   # hyphen separator
        ("XRD_5305_ScN_Al2O3_650C", "ScN/Al₂O₃ 650 °C"),
        ("XRD_5304_ScN_Al2O3_700C", "ScN/Al₂O₃ 700 °C"),
        ("XRD_5303_ScN_AL2O3_750C", "ScN/Al₂O₃ 750 °C"),   # mis-cased formula
    ],
)
def test_temperature_series_labels(stem, expected):
    assert label_for(stem, DEFAULT, FIELD) == expected


def test_date_time_convention_unchanged():
    assert label_for("XRD_5292_GaN_ScN_260713_1551", DEFAULT, FIELD) == "GaN/ScN"


def test_unmatched_name_falls_back_to_stem():
    assert label_for("random_file", DEFAULT, FIELD) == "random_file"


@pytest.mark.parametrize(
    "token, expected",
    [("AL2O3", "Al2O3"), ("scn", "ScN"), ("GaN", "GaN"), ("Al2O3", "Al2O3"),
     ("Sample", "Sample")],  # a plain word passes through untouched
)
def test_canonical_formula(token, expected):
    assert canonical_formula(token) == expected
