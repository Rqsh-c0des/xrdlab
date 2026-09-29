"""Save / load a whole working session as a portable ``.xrdlab`` project file.

A project bundles everything needed to resume where you left off: the loaded
patterns (data included, so the file is self-contained), overlaid references,
waterfall guides, manual labels, peak overrides, cleared/moved labels, the figure
title, and every control setting. It is plain JSON so it stays inspectable and
forward-compatible.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np

from xrdlab.core.pattern import Pattern
from xrdlab.mp.simulate import ReferencePattern

__all__ = [
    "PROJECT_VERSION",
    "PROJECT_EXT",
    "OVERLAY_EXT",
    "SESSION_EXTS",
    "PROJECT_FILTER",
    "PROJECT_SAVE_FILTER",
    "OVERLAY_FILTER",
    "save_project",
    "load_project",
    "serialize_pattern",
    "deserialize_pattern",
    "serialize_reference",
    "deserialize_reference",
]

PROJECT_VERSION = 1
PROJECT_EXT = ".xrdlab"
# An *overlay* is its own file type: just the multi-pattern comparison view — the
# stacked scans that were checked, their reference overlays, guide lines and view
# settings — and it opens straight into the Waterfall. Same JSON schema as a project
# (so either reader can open it), tagged ``kind: "overlay"``.
OVERLAY_EXT = ".xrdov"
SESSION_EXTS = (PROJECT_EXT, OVERLAY_EXT)
PROJECT_FILTER = (
    "XRDLab project or overlay (*.xrdlab *.xrdov);;XRDLab project (*.xrdlab);;"
    "XRDLab overlay (*.xrdov);;All files (*)"
)
PROJECT_SAVE_FILTER = "XRDLab project (*.xrdlab);;All files (*)"
OVERLAY_FILTER = "XRDLab overlay (*.xrdov);;All files (*)"


class _NpEncoder(json.JSONEncoder):
    """Encode numpy arrays / scalars (as produced by pymatgen and the parsers)."""

    def default(self, o):  # noqa: D401
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, tuple):
            return list(o)
        return super().default(o)


def _clean(obj):
    """Recursively make ``obj`` JSON-safe (arrays→lists, np scalars→py, tuples→lists)."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


# -- patterns --------------------------------------------------------------

def serialize_pattern(p: Pattern, *, checked: bool = True) -> dict:
    return {
        "two_theta": p.two_theta.tolist(),
        "intensity": p.intensity.tolist(),
        "wavelength": float(p.wavelength),
        "name": p.name,
        "meta": _clean(p.meta),
        "checked": bool(checked),
    }


def deserialize_pattern(d: dict) -> Pattern:
    return Pattern(
        two_theta=np.asarray(d["two_theta"], dtype=float),
        intensity=np.asarray(d["intensity"], dtype=float),
        wavelength=float(d.get("wavelength", Pattern.wavelength)),
        name=d.get("name", ""),
        meta=dict(d.get("meta", {})),
    )


# -- references ------------------------------------------------------------

def serialize_reference(r: ReferencePattern) -> dict:
    return {
        "two_theta": np.asarray(r.two_theta).tolist(),
        "intensity": np.asarray(r.intensity).tolist(),
        "hkls": _clean(r.hkls),
        "formula": r.formula,
        "material_id": r.material_id,
        "wavelength": str(r.wavelength),
        "d_spacings": None if r.d_spacings is None else np.asarray(r.d_spacings).tolist(),
        "crystal_system": r.crystal_system,
        "space_group": r.space_group,
        "space_group_number": r.space_group_number,
    }


def deserialize_reference(d: dict) -> ReferencePattern:
    ds = d.get("d_spacings")
    return ReferencePattern(
        two_theta=np.asarray(d["two_theta"], dtype=float),
        intensity=np.asarray(d["intensity"], dtype=float),
        hkls=list(d.get("hkls", [])),
        formula=d.get("formula", ""),
        material_id=d.get("material_id", ""),
        wavelength=d.get("wavelength", "CuKa1"),
        d_spacings=None if ds is None else np.asarray(ds, dtype=float),
        crystal_system=d.get("crystal_system", ""),
        space_group=d.get("space_group", ""),
        space_group_number=d.get("space_group_number"),
    )


# -- dict-with-exotic-keys helpers (peak overrides / label offsets) ---------

def encode_keyed(mapping: dict) -> list:
    """Serialize a dict whose keys may be floats/tuples as ``[[key_repr, value], …]``."""
    return [[repr(k), _clean(v)] for k, v in mapping.items()]


def decode_keyed(pairs) -> dict:
    out = {}
    for k_repr, value in pairs or []:
        try:
            key = ast.literal_eval(k_repr)
        except (ValueError, SyntaxError):
            key = k_repr
        out[key] = value
    return out


# -- file I/O --------------------------------------------------------------

def save_project(path: str | Path, data: dict, kind: str | None = None) -> None:
    """Write a session. ``kind`` defaults from the extension (.xrdov → overlay)."""
    if kind is None:
        kind = "overlay" if str(path).lower().endswith(OVERLAY_EXT) else "project"
    data = {"xrdlab_project": PROJECT_VERSION, "kind": kind, **data}
    text = json.dumps(data, cls=_NpEncoder, indent=1)
    Path(path).write_text(text, encoding="utf-8")


def load_project(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "xrdlab_project" not in data:
        raise ValueError("Not an XRDLab project file (missing 'xrdlab_project').")
    ver = data["xrdlab_project"]
    if not isinstance(ver, int) or ver > PROJECT_VERSION:
        raise ValueError(
            f"Project was saved by a newer XRDLab (version {ver}); please update."
        )
    return data
