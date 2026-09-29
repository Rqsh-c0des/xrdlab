"""Reusable matplotlib-in-Qt widgets."""

from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as _NavigationToolbar
from matplotlib.figure import Figure
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

__all__ = ["MplCanvas", "PlotWidget", "CitationsView"]


class NavigationToolbar(_NavigationToolbar):
    """Standard matplotlib toolbar minus the built-in 'Customize' editor.

    That editor exposes its own axis Scale/limits dialog, which conflicts with the
    app's Y-scale control (and can't represent the custom sqrt scale). Removing it
    leaves the app panel as the single source of truth for scaling.
    """

    toolitems = [t for t in _NavigationToolbar.toolitems if t[0] != "Customize"]


class MplCanvas(FigureCanvasQTAgg):
    """A blank matplotlib canvas backed by a fresh Figure."""

    def __init__(self, width: float = 6.0, height: float = 4.5, dpi: int = 120):
        self.figure = Figure(figsize=(width, height), dpi=dpi)
        super().__init__(self.figure)

    def clear(self) -> None:
        self.figure.clear()
        self.draw_idle()


class PlotWidget(QWidget):
    """A canvas plus the standard matplotlib navigation toolbar."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.canvas = MplCanvas()
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.lock_y = False  # waterfall sets this: scroll-zoom only affects x
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        # Trackpad two-finger / mouse-wheel zoom centred on the cursor.
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        # Double-click while a nav tool (zoom/pan) is active resets to Home.
        self.canvas.mpl_connect("button_press_event", self._on_double_click)

    def _on_double_click(self, event) -> None:
        if not getattr(event, "dblclick", False):
            return
        # Only when the magnifier / pan tool is active, so it doesn't interfere
        # with normal double-clicks elsewhere.
        if str(getattr(self.toolbar, "mode", "")):
            self.toolbar.home()

    def _on_scroll(self, event) -> None:
        import math

        ax = event.inaxes
        if ax is None or event.xdata is None or event.ydata is None:
            return
        f = 0.83 if event.button == "up" else 1.0 / 0.83  # up = zoom in
        x, y = event.xdata, event.ydata
        xlo, xhi = ax.get_xlim()
        new_xlo, new_xhi = x - (x - xlo) * f, x + (xhi - x) * f
        # Never zoom out past the actual data extent.
        dlo, dhi = ax.dataLim.intervalx
        if dlo < dhi:
            new_xlo, new_xhi = max(new_xlo, dlo), min(new_xhi, dhi)
        if new_xlo < new_xhi:
            ax.set_xlim(new_xlo, new_xhi)
        if self.lock_y:  # waterfall: y is arbitrary offset — don't zoom/flatten it
            self.canvas.draw_idle()
            return
        ylo, yhi = ax.get_ylim()
        if ax.get_yscale() == "log" and min(y, ylo, yhi) > 0:
            ly, llo, lhi = math.log10(y), math.log10(ylo), math.log10(yhi)
            ax.set_ylim(10 ** (ly - (ly - llo) * f), 10 ** (ly + (lhi - ly) * f))
        else:
            ax.set_ylim(y - (y - ylo) * f, y + (yhi - y) * f)
        self.canvas.draw_idle()

    @property
    def figure(self) -> Figure:
        return self.canvas.figure

    def clear(self) -> None:
        self.canvas.clear()

    def refresh(self) -> None:
        self.canvas.draw_idle()


class CitationsView(QWidget):
    """A read-only HTML report of identified peaks and their source citations."""

    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)

        self.export_btn = QPushButton("Export citations (.bib)…")
        self.export_btn.clicked.connect(lambda: self.export_requested.emit())
        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(self.export_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        layout.addLayout(bar)

    def set_html(self, html: str) -> None:
        self.browser.setHtml(html)
