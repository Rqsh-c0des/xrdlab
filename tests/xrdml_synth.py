"""Write synthetic Panalytical-style .xrdml files (for tests and GUI checks).

Mirrors the XRDML 2.1 layout the Empyrean writes: namespaced root, one
<xrdMeasurement measurementType=...>, <usedWavelength>, <incidentBeamPath>, and
<scan scanAxis=...> blocks with <positions axis=...> start/end or commonPosition.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

NS = "http://www.xrdml.com/XRDMeasurement/2.1"


def _pos(axis: str, arr=None, common=None) -> str:
    if arr is not None:
        return (f'<positions axis="{axis}" unit="deg"><startPosition>{arr[0]:.8f}'
                f'</startPosition><endPosition>{arr[-1]:.8f}</endPosition></positions>')
    return (f'<positions axis="{axis}" unit="deg"><commonPosition>{common:.6f}'
            f'</commonPosition></positions>')


def _scan(axis: str, positions: dict, counts) -> str:
    body = "".join(_pos(a, *( (v, None) if isinstance(v, np.ndarray) else (None, v)))
                   for a, v in positions.items())
    c = " ".join(str(int(max(0, round(v)))) for v in counts)
    return (f'<scan appendNumber="0" mode="Continuous" scanAxis="{axis}" status="Completed">'
            f'<dataPoints>{body}<commonCountingTime unit="seconds">1.0</commonCountingTime>'
            f'<counts unit="counts">{c}</counts></dataPoints></scan>')


def write_xrdml(path, scans_xml: list[str], *, measurement_type="Scan",
                monochromator: bool = False) -> Path:
    optics = ('<monochromator name="Hybrid monochromator 2xGe(220)"><crystal>Ge (220)'
              '</crystal></monochromator>' if monochromator else
              '<xRayMirror name="Bragg-Brentano HD Cu" hybrid="false"><crystal type="Graded">'
              'BB/HD</crystal></xRayMirror>')
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><xrdMeasurements xmlns="{NS}" '
           f'status="Completed"><xrdMeasurement measurementType="{measurement_type}" '
           f'status="Completed"><usedWavelength intended="K-Alpha 1"><kAlpha1 unit="Angstrom">'
           f'1.5405980</kAlpha1><kAlpha2 unit="Angstrom">1.5444260</kAlpha2>'
           f'<kBeta unit="Angstrom">1.3922500</kBeta><ratioKAlpha2KAlpha1>0.5000'
           f'</ratioKAlpha2KAlpha1></usedWavelength><incidentBeamPath>{optics}'
           f'</incidentBeamPath>{"".join(scans_xml)}</xrdMeasurement></xrdMeasurements>')
    path = Path(path)
    path.write_text(xml, encoding="utf-8")
    return path


def pv(x, c, w, a, eta=0.5):
    s = w / (2 * np.sqrt(2 * np.log(2)))
    return a * (eta * (w / 2) ** 2 / ((x - c) ** 2 + (w / 2) ** 2)
                + (1 - eta) * np.exp(-((x - c) ** 2) / (2 * s**2)))


def rocking_curve(path, *, two_theta=34.57, omega0=17.285, fwhm=0.08, peak=5e4,
                  bg=20.0, monochromator=True, seed=0) -> Path:
    rng = np.random.default_rng(seed)
    om = np.linspace(omega0 - 1.0, omega0 + 1.0, 801)
    y = rng.poisson(bg + pv(om, omega0, fwhm, peak)).astype(float)
    return write_xrdml(path, [_scan("Omega", {"2Theta": two_theta, "Omega": om}, y)],
                       monochromator=monochromator)


def phi_scan(path, *, n_fold=6, offset=15.0, fwhm=1.0, seed=0) -> Path:
    rng = np.random.default_rng(seed)
    phi = np.linspace(0, 359.9, 3600)
    y = 30.0 + sum(pv(phi, (offset + k * 360 / n_fold) % 360, fwhm, 4e3)
                   for k in range(n_fold))
    return write_xrdml(path, [_scan("Phi", {"2Theta": 36.8, "Omega": 18.4, "Phi": phi},
                                    rng.poisson(y))], monochromator=True)


def area_map(path, *, wavelength=1.540598, peaks=(), bg=5.0, n_scans=41,
             tt_center=105.0, tt_span=4.0, off_center=0.0, off_span=2.0,
             seed=0) -> Path:
    """Stepped-offset 2θ-ω scans; ``peaks`` = [(qx, qz, sigma_q, amplitude), …]."""
    from xrdlab.core.hrxrd import rsm_to_q

    rng = np.random.default_rng(seed)
    scans = []
    tt = np.linspace(tt_center - tt_span / 2, tt_center + tt_span / 2, 301)
    for off in np.linspace(off_center - off_span / 2, off_center + off_span / 2, n_scans):
        om = tt / 2.0 + off
        qx, qz = rsm_to_q(om, tt, wavelength)
        I = bg + sum(a * np.exp(-((qx - px) ** 2 + (qz - pz) ** 2) / (2 * s**2))
                     for px, pz, s, a in peaks)
        scans.append(_scan("2Theta-Omega", {"2Theta": tt, "Omega": om}, rng.poisson(I)))
    return write_xrdml(path, scans, measurement_type="Area measurement",
                       monochromator=True)
