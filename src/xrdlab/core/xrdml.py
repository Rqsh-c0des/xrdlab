"""Reader for Panalytical ``.xrdml`` measurement files.

The format is namespaced XML (``http://www.xrdml.com/XRDMeasurement/<ver>``). Each
``<scan>`` stores its 2θ axis as only a start/end position, and the intensities as a
single space-separated ``<counts>`` (or ``<intensities>``) string, so the x-axis is
reconstructed with ``np.linspace(start, end, n)``.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from xrdlab.core.pattern import Pattern

__all__ = ["read_xrdml", "read_xrdml_single", "read_xrdml_area", "is_area_measurement"]


def _local(tag: str) -> str:
    """Strip an ``{namespace}`` prefix from an element tag."""
    return tag.rsplit("}", 1)[-1]


def _ns(root: ET.Element) -> dict[str, str]:
    """Build a namespace map from the root's default namespace, if any."""
    if root.tag.startswith("{"):
        uri = root.tag[1:].split("}", 1)[0]
        return {"x": uri}
    return {}


def _find(elem: ET.Element, path: str, ns: dict[str, str]):
    """Namespace-aware find that also works when the file has no namespace."""
    if ns:
        return elem.find(path, ns)
    return elem.find(path.replace("x:", ""))


def _findall(elem: ET.Element, path: str, ns: dict[str, str]):
    if ns:
        return elem.findall(path, ns)
    return elem.findall(path.replace("x:", ""))


def _text_float(elem, path, ns, default=None):
    node = _find(elem, path, ns) if path else elem
    if node is None or node.text is None or not node.text.strip():
        return default
    try:
        return float(node.text.strip())
    except ValueError:
        return default


def _parse_wavelengths(measurement: ET.Element, ns: dict[str, str]) -> dict:
    used = _find(measurement, "x:usedWavelength", ns)
    wl: dict = {}
    if used is not None:
        wl["kAlpha1"] = _text_float(used, "x:kAlpha1", ns, 1.5405980)
        wl["kAlpha2"] = _text_float(used, "x:kAlpha2", ns)
        wl["kBeta"] = _text_float(used, "x:kBeta", ns)
        wl["ratioKAlpha2KAlpha1"] = _text_float(used, "x:ratioKAlpha2KAlpha1", ns)
    else:
        wl["kAlpha1"] = 1.5405980
    return wl


# scanAxis → the axis that forms the x data. Coupled scans (Gonio, 2Theta-Omega…)
# are plotted against 2θ; rocking curves against ω; in-plane scans against φ, etc.
_SCAN_AXIS_TO_X = {
    "gonio": "2Theta", "2theta-omega": "2Theta", "omega-2theta": "2Theta",
    "2theta": "2Theta", "omega": "Omega", "phi": "Phi", "chi": "Chi", "psi": "Chi",
    "z": "Z", "x": "X", "y": "Y",
}


def _axis_positions(pos: ET.Element, ns, n: int):
    """Return (array, fixed) for a <positions> element: array if it varies over the
    scan (start/end or listPositions), else None and the common value."""
    lst = _find(pos, "x:listPositions", ns)
    if lst is not None and lst.text and lst.text.split():
        vals = np.array(lst.text.split(), dtype=float)
        if vals.size == n:
            return vals, None
    start = _text_float(pos, "x:startPosition", ns)
    end = _text_float(pos, "x:endPosition", ns)
    if start is not None and end is not None:
        if n > 1 and start != end:
            return np.linspace(start, end, n), None
        return None, start
    return None, _text_float(pos, "x:commonPosition", ns)


def _parse_scan(scan: ET.Element, ns: dict[str, str]) -> tuple[np.ndarray, np.ndarray, dict] | None:
    data_points = _find(scan, "x:dataPoints", ns)
    if data_points is None:
        return None

    # Intensities: prefer <counts>, fall back to <intensities>.
    counts_node = _find(data_points, "x:counts", ns)
    if counts_node is None:
        counts_node = _find(data_points, "x:intensities", ns)
    if counts_node is None or not (counts_node.text and counts_node.text.strip()):
        return None
    counts = np.array(counts_node.text.split(), dtype=float)
    n = counts.size

    arrays: dict[str, np.ndarray] = {}
    fixed: dict[str, float] = {}
    for pos in _findall(data_points, "x:positions", ns):
        axis = pos.get("axis") or ""
        arr, val = _axis_positions(pos, ns, n)
        if arr is not None:
            arrays[axis] = arr
        elif val is not None:
            fixed[axis] = val

    scan_axis = (scan.get("scanAxis") or "").strip()
    x_axis = _SCAN_AXIS_TO_X.get(scan_axis.lower())
    if x_axis is None or x_axis not in arrays:  # unknown / inconsistent → best guess
        x_axis = next((a for a in ("2Theta", "Omega", "Phi", "Chi") if a in arrays), None)
    if x_axis is not None:
        x = arrays[x_axis]
    else:
        x_axis = "2Theta" if "2Theta" in fixed else "index"
        x = np.full(n, fixed["2Theta"]) if x_axis == "2Theta" else np.arange(n, dtype=float)

    meta: dict = {"x_axis": x_axis, "fixed_positions": fixed}
    ct = _text_float(data_points, "x:commonCountingTime", ns)
    if ct is not None:
        meta["counting_time"] = ct
    tt = arrays.get("2Theta")
    meta["two_theta_start"] = float(tt[0]) if tt is not None else fixed.get("2Theta")
    meta["two_theta_end"] = float(tt[-1]) if tt is not None else fixed.get("2Theta")
    if "Omega" in arrays:  # needed for reciprocal-space maps
        meta["omega_start"] = float(arrays["Omega"][0])
        meta["omega_end"] = float(arrays["Omega"][-1])
    meta["intensity_unit"] = counts_node.get("unit", "counts")
    meta["_arrays"] = arrays  # stripped before building the Pattern (RSM use only)
    return x, counts, meta


def _kalpha1_only(measurement: ET.Element, ns) -> bool:
    """True if the incident optics remove Kα2 (hybrid / crystal monochromator).

    A Bragg-Brentano HD mirror (hybrid="false") only removes Kβ — the Kα doublet
    remains, so that returns False.
    """
    path = _find(measurement, "x:incidentBeamPath", ns)
    if path is None:
        return False
    for el in path.iter():
        tag = _local(el.tag).lower()
        name = (el.get("name") or "").lower()
        text = (el.text or "").lower()
        if "monochromator" in tag or "monochromator" in name:
            return True
        if el.get("hybrid", "").lower() == "true":
            return True
        if tag == "crystal" and re.search(r"ge|ge\s*\(", text):
            return True  # Ge(220)/(440) channel-cut crystals
        if "hybrid" in name and "mirror" in name:
            return True
    return False


def _collect_comments(elem: ET.Element, ns: dict[str, str]) -> list[str]:
    out: list[str] = []
    comment = _find(elem, "x:comment", ns)
    if comment is not None:
        for entry in _findall(comment, "x:entry", ns):
            if entry.text and entry.text.strip():
                out.append(entry.text.strip())
    return out


def read_xrdml(path: str | os.PathLike) -> list[Pattern]:
    """Parse an ``.xrdml`` file into one :class:`Pattern` per ``<scan>``.

    Returns an empty list if the file contains no readable scan.
    """
    path = Path(path)
    root = ET.parse(path).getroot()
    ns = _ns(root)
    stem = path.stem

    file_comments = _collect_comments(root, ns)
    measurements = _findall(root, "x:xrdMeasurement", ns) or [root]

    patterns: list[Pattern] = []
    scan_index = 0
    total_scans = sum(len(_findall(m, "x:scan", ns)) for m in measurements)
    for measurement in measurements:
        wl = _parse_wavelengths(measurement, ns)
        meas_comments = _collect_comments(measurement, ns)
        k1_only = _kalpha1_only(measurement, ns)
        mtype = measurement.get("measurementType") or ""
        for scan in _findall(measurement, "x:scan", ns):
            parsed = _parse_scan(scan, ns)
            if parsed is None:
                continue
            two_theta, counts, meta = parsed
            meta.pop("_arrays", None)
            meta.update(
                {
                    "source_file": str(path),
                    "kAlpha2": wl.get("kAlpha2"),
                    "kBeta": wl.get("kBeta"),
                    "ratioKAlpha2KAlpha1": wl.get("ratioKAlpha2KAlpha1"),
                    "scan_axis": scan.get("scanAxis"),
                    "measurement_type": mtype,
                    "kalpha1_only": k1_only,
                    "comments": file_comments + meas_comments,
                }
            )
            name = stem if total_scans <= 1 else f"{stem} [{scan_index + 1}]"
            patterns.append(
                Pattern(
                    two_theta=two_theta,
                    intensity=counts,
                    wavelength=wl.get("kAlpha1", 1.5405980),
                    name=name,
                    meta=meta,
                )
            )
            scan_index += 1
    return patterns


def read_xrdml_single(path: str | os.PathLike) -> Pattern:
    """Parse an ``.xrdml`` file and return its first scan as a :class:`Pattern`.

    Raises
    ------
    ValueError
        If the file contains no readable scan.
    """
    patterns = read_xrdml(path)
    if not patterns:
        raise ValueError(f"No readable scan found in {Path(path).name}")
    return patterns[0]


def read_xrdml_area(path: str | os.PathLike) -> dict:
    """Read a multi-scan *area* measurement (reciprocal-space map) as scattered points.

    Returns ``{"omega", "two_theta", "intensity"}`` (1-D arrays, one entry per
    measured point, any scan type: stepped 2θ-ω or stepped ω), plus ``wavelength``,
    ``kalpha1_only``, ``n_scans`` and ``name``. Works for coupled scans at stepped ω
    offsets and for ω scans at stepped 2θ.
    """
    path = Path(path)
    root = ET.parse(path).getroot()
    ns = _ns(root)
    om, tt, ii = [], [], []
    wl, k1, n_scans = 1.5405980, False, 0
    for measurement in _findall(root, "x:xrdMeasurement", ns) or [root]:
        wl = _parse_wavelengths(measurement, ns).get("kAlpha1", wl)
        k1 = _kalpha1_only(measurement, ns)
        for scan in _findall(measurement, "x:scan", ns):
            parsed = _parse_scan(scan, ns)
            if parsed is None:
                continue
            _x, counts, meta = parsed
            arrays, fixed, n = meta["_arrays"], meta["fixed_positions"], counts.size
            o = arrays.get("Omega", np.full(n, fixed.get("Omega", np.nan)))
            t = arrays.get("2Theta", np.full(n, fixed.get("2Theta", np.nan)))
            if np.isnan(o).any() or np.isnan(t).any():
                continue
            om.append(o); tt.append(t); ii.append(counts); n_scans += 1
    if not n_scans:
        raise ValueError(f"No readable scans in {path.name}")
    return {"omega": np.concatenate(om), "two_theta": np.concatenate(tt),
            "intensity": np.concatenate(ii), "wavelength": float(wl),
            "kalpha1_only": k1, "n_scans": n_scans, "name": path.stem}


def is_area_measurement(path: str | os.PathLike) -> bool:
    """True for a reciprocal-space map: Panalytical "Area measurement", or several
    scans whose ω–2θ/2 offset (coupled scans) or fixed 2θ (ω scans) steps."""
    try:
        root = ET.parse(Path(path)).getroot()
    except (ET.ParseError, OSError):
        return False
    ns = _ns(root)
    offsets = set()
    for measurement in _findall(root, "x:xrdMeasurement", ns) or [root]:
        if "area" in (measurement.get("measurementType") or "").lower():
            return True
        for scan in _findall(measurement, "x:scan", ns):
            parsed = _parse_scan(scan, ns)
            if parsed is None:
                continue
            _x, counts, meta = parsed
            a, f = meta["_arrays"], meta["fixed_positions"]
            o = a.get("Omega", np.array([f.get("Omega", np.nan)]))
            t = a.get("2Theta", np.array([f.get("2Theta", np.nan)]))
            offsets.add(round(float(o[0] - t[0] / 2.0), 4))
    return len(offsets) >= 3
