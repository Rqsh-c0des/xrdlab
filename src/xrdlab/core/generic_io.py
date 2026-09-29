"""Readers for common column-based XRD text formats.

Each returns a :class:`Pattern`. ``read_pattern`` dispatches by file extension,
delegating ``.xrdml`` to :mod:`xrdlab.core.xrdml`.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import numpy as np

from xrdlab.core.pattern import Pattern

__all__ = ["read_xy", "read_csv", "read_dat", "read_pattern"]

_X_ALIASES = {"2theta", "2-theta", "2 theta", "twotheta", "ttheta", "angle", "theta", "x", "pos", "position"}
_Y_ALIASES = {"intensity", "counts", "int", "i", "y", "yobs", "signal"}


def _two_columns(path: str | os.PathLike) -> tuple[np.ndarray, np.ndarray]:
    """Load the first two numeric columns, skipping comments/headers.

    Tolerant of ``#``/``;`` comment lines, blank lines, and a leading text header.
    Accepts whitespace-, comma-, tab-, or semicolon-delimited data.
    """
    xs: list[float] = []
    ys: list[float] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s[0] in "#;!*":
                continue
            parts = [p for p in s.replace(",", " ").replace("\t", " ").split() if p]
            if len(parts) < 2:
                continue
            try:
                x = float(parts[0])
                y = float(parts[1])
            except ValueError:
                continue  # header / non-numeric row
            xs.append(x)
            ys.append(y)
    if not xs:
        raise ValueError(f"No numeric 2-column data found in {Path(path).name}")
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


def read_xy(path: str | os.PathLike) -> Pattern:
    """Read a two-column ``2theta intensity`` file (``.xy``/``.txt``)."""
    x, y = _two_columns(path)
    return Pattern(x, y, name=Path(path).stem, meta={"source_file": str(path)})


def read_dat(path: str | os.PathLike) -> Pattern:
    """Read a two-column ``.dat`` file (tolerant of headers)."""
    return read_xy(path)


def _match_column(headers: list[str], aliases: set[str]) -> int | None:
    for i, h in enumerate(headers):
        if h.strip().lower() in aliases:
            return i
    return None


def read_csv(path: str | os.PathLike) -> Pattern:
    """Read a CSV with a header, auto-detecting the 2θ and intensity columns.

    Falls back to the first two columns when header names are unrecognised.
    """
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        rows = list(csv.reader(fh))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ValueError(f"Empty CSV: {Path(path).name}")

    headers = rows[0]
    xi = _match_column(headers, _X_ALIASES)
    yi = _match_column(headers, _Y_ALIASES)
    if xi is None or yi is None:
        # No usable header — treat everything as data, first two columns.
        xi, yi, data_rows = 0, 1, rows
    else:
        data_rows = rows[1:]

    xs: list[float] = []
    ys: list[float] = []
    for r in data_rows:
        if len(r) <= max(xi, yi):
            continue
        try:
            xs.append(float(r[xi]))
            ys.append(float(r[yi]))
        except ValueError:
            continue
    if not xs:
        raise ValueError(f"No numeric data found in {Path(path).name}")
    return Pattern(
        np.asarray(xs), np.asarray(ys), name=Path(path).stem,
        meta={"source_file": str(path)},
    )


def read_pattern(path: str | os.PathLike) -> Pattern:
    """Dispatch on file extension and return a single :class:`Pattern`."""
    ext = Path(path).suffix.lower()
    if ext == ".xrdml":
        from xrdlab.core.xrdml import read_xrdml_single

        return read_xrdml_single(path)
    if ext == ".csv":
        return read_csv(path)
    # .xy / .dat / .txt / unknown -> tolerant two-column reader
    return read_xy(path)
