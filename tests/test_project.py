"""Round-trip tests for the .xrdlab project (de)serialization (no GUI needed)."""

from __future__ import annotations

import numpy as np
import pytest

from xrdlab.core.pattern import Pattern
from xrdlab.core.project import (
    decode_keyed,
    deserialize_pattern,
    deserialize_reference,
    encode_keyed,
    load_project,
    save_project,
    serialize_pattern,
    serialize_reference,
)
from xrdlab.mp.simulate import ReferencePattern


def test_pattern_round_trip():
    p = Pattern(
        two_theta=np.linspace(10, 120, 500),
        intensity=np.random.rand(500) * 1000,
        wavelength=1.5406,
        name="GaN/ScN",
        meta={"source_stem": "XRD_5292_GaN_ScN", "counts": 3},
    )
    d = serialize_pattern(p, checked=False)
    assert d["checked"] is False
    q = deserialize_pattern(d)
    assert q.name == p.name
    assert q.wavelength == pytest.approx(p.wavelength)
    assert q.meta["source_stem"] == "XRD_5292_GaN_ScN"
    np.testing.assert_allclose(q.two_theta, p.two_theta)
    np.testing.assert_allclose(q.intensity, p.intensity)


def test_reference_round_trip():
    r = ReferencePattern(
        two_theta=[34.5, 72.5], intensity=[100.0, 20.0],
        hkls=[[{"hkl": (0, 0, 0, 2), "multiplicity": 2}],
              [{"hkl": (0, 0, 0, 4), "multiplicity": 2}]],
        formula="GaN", material_id="mp-804", wavelength="CuKa1",
        d_spacings=[2.6, 1.3], crystal_system="hexagonal",
        space_group="P6_3mc", space_group_number=186,
    )
    q = deserialize_reference(serialize_reference(r))
    assert q.formula == "GaN"
    assert q.crystal_system == "hexagonal"
    assert q.space_group_number == 186
    assert q.hkls[0][0]["hkl"] == [0, 0, 0, 2]  # tuple -> list after JSON
    np.testing.assert_allclose(q.two_theta, [34.5, 72.5])
    np.testing.assert_allclose(q.d_spacings, [2.6, 1.3])


def test_reference_no_dspacings():
    r = ReferencePattern(two_theta=[30.0], intensity=[100.0], formula="X")
    q = deserialize_reference(serialize_reference(r))
    assert q.d_spacings is None


def test_keyed_dict_round_trip():
    """Peak overrides / label offsets have float and tuple keys."""
    overrides = {34.5: ("GaN", [0, 0, 0, 2], 34.5, 100.0), 41.7: None}
    offsets = {("manual", 0): (3.0, 7.0), ("peak", 34.5): (0.0, 4.0)}
    assert decode_keyed(encode_keyed(overrides)) == {
        34.5: ["GaN", [0, 0, 0, 2], 34.5, 100.0], 41.7: None
    }
    assert decode_keyed(encode_keyed(offsets)) == {
        ("manual", 0): [3.0, 7.0], ("peak", 34.5): [0.0, 4.0]
    }


def test_save_load_file(tmp_path):
    path = tmp_path / "session.xrdlab"
    save_project(path, {"title": "T", "patterns": [], "controls": {"wf_gap": 1.5}})
    data = load_project(path)
    assert data["xrdlab_project"] == 1
    assert data["title"] == "T"
    assert data["controls"]["wf_gap"] == 1.5


def test_kind_follows_extension(tmp_path):
    """.xrdov files are overlays, .xrdlab files are projects; both load the same way."""
    ov, pj = tmp_path / "series.xrdov", tmp_path / "series.xrdlab"
    save_project(ov, {"patterns": []})
    save_project(pj, {"patterns": []})
    assert load_project(ov)["kind"] == "overlay"
    assert load_project(pj)["kind"] == "project"


def test_load_rejects_foreign_json(tmp_path):
    path = tmp_path / "not_a_project.json"
    path.write_text('{"hello": "world"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Not an XRDLab project"):
        load_project(path)


def test_load_rejects_newer_version(tmp_path):
    path = tmp_path / "future.xrdlab"
    path.write_text('{"xrdlab_project": 999}', encoding="utf-8")
    with pytest.raises(ValueError, match="newer XRDLab"):
        load_project(path)
