"""Import/export of Rietveld refinement output for the obs/calc/diff/bkg figure.

Refinement engines (GSAS-II, FullProf, TOPAS) all differ in their native output,
so the common exchange path here is a CSV with columns
``2theta, yobs, ycalc, ybkg`` (+ an optional ``reflections`` column of 2θ tick
positions). Column names are matched case-insensitively against a set of aliases.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

__all__ = ["RietveldData", "read_rietveld_csv", "write_rietveld_csv"]

_ALIASES: dict[str, set[str]] = {
    "two_theta": {"2theta", "2-theta", "2 theta", "twotheta", "ttheta", "angle", "x"},
    "yobs": {"yobs", "obs", "observed", "yexp", "iobs", "yo"},
    "ycalc": {"ycalc", "calc", "calculated", "icalc", "yc"},
    "ybkg": {"ybkg", "bkg", "background", "ibkg", "backg", "back"},
    "reflections": {"reflections", "hkl_2theta", "ticks", "reflection", "bragg"},
}


@dataclass
class RietveldData:
    """Container for a Rietveld refinement result."""

    two_theta: np.ndarray
    yobs: np.ndarray
    ycalc: np.ndarray
    ybkg: np.ndarray
    reflections: np.ndarray | None = None
    name: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.two_theta = np.asarray(self.two_theta, dtype=float)
        self.yobs = np.asarray(self.yobs, dtype=float)
        self.ycalc = np.asarray(self.ycalc, dtype=float)
        self.ybkg = np.asarray(self.ybkg, dtype=float)
        n = self.two_theta.size
        for label, arr in (("yobs", self.yobs), ("ycalc", self.ycalc), ("ybkg", self.ybkg)):
            if arr.size != n:
                raise ValueError(
                    f"{label} length ({arr.size}) != two_theta length ({n})"
                )
        if self.reflections is not None:
            self.reflections = np.asarray(self.reflections, dtype=float)

    @property
    def diff(self) -> np.ndarray:
        """Difference curve, observed − calculated."""
        return self.yobs - self.ycalc


def _resolve_columns(headers: list[str]) -> dict[str, int]:
    lut = {h.strip().lower(): i for i, h in enumerate(headers)}
    resolved: dict[str, int] = {}
    for field_name, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in lut:
                resolved[field_name] = lut[alias]
                break
    return resolved


def read_rietveld_csv(path: str | os.PathLike) -> RietveldData:
    """Read a Rietveld CSV into a :class:`RietveldData`.

    Raises
    ------
    ValueError
        If a required column (2theta/yobs/ycalc/ybkg) cannot be found; the error
        lists the header names that were present.
    """
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        rows = list(csv.reader(fh))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ValueError(f"Empty CSV: {Path(path).name}")

    headers = rows[0]
    cols = _resolve_columns(headers)
    required = ("two_theta", "yobs", "ycalc", "ybkg")
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValueError(
            f"Rietveld CSV {Path(path).name} is missing column(s) {missing}. "
            f"Found headers: {headers}. Expected names like "
            "2theta, yobs, ycalc, ybkg (+ optional reflections)."
        )

    data: dict[str, list[float]] = {k: [] for k in cols}
    for r in rows[1:]:
        try:
            parsed = {k: float(r[idx]) for k, idx in cols.items() if idx < len(r) and r[idx].strip() != ""}
        except ValueError:
            continue
        # require the four mandatory numeric values on this row
        if not all(k in parsed for k in required):
            continue
        for k, v in parsed.items():
            data[k].append(v)

    reflections = np.asarray(data["reflections"]) if "reflections" in cols and data.get("reflections") else None
    return RietveldData(
        two_theta=np.asarray(data["two_theta"]),
        yobs=np.asarray(data["yobs"]),
        ycalc=np.asarray(data["ycalc"]),
        ybkg=np.asarray(data["ybkg"]),
        reflections=reflections,
        name=Path(path).stem,
        meta={"source_file": str(path)},
    )


def write_rietveld_csv(path: str | os.PathLike, data: RietveldData) -> None:
    """Write ``data`` to a ``2theta,yobs,ycalc,ybkg`` CSV (round-trip helper)."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["2theta", "yobs", "ycalc", "ybkg"])
        for row in zip(data.two_theta, data.yobs, data.ycalc, data.ybkg):
            writer.writerow([f"{v:.6g}" for v in row])
