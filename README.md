# XRDLab

A desktop app for turning raw X-ray diffraction scans into **publication-ready
figures** — stacked waterfall plots, Rietveld obs/calc/diff/background panels, and
Materials Project reference overlays — exported as true vector graphics
(**PDF / EPS / SVG**) plus PNG.

Built with **PySide6** (native desktop UI) and **matplotlib** (vector export).

---

## Features

- **Import** Panalytical `.xrdml` (2θ scans) and generic column formats
  (`.xy`, `.dat`, `.txt`, `.csv`). Drag-and-drop supported.
- **Save & resume projects** — **File ▸ Save project** (`Ctrl+S`) writes the whole
  working session to a self-contained `.xrdlab` file: every loaded pattern *with its
  data*, overlaid references, waterfall guides, manual peaks, phase assignments /
  overrides, moved and cleared labels, the figure title, and all control settings.
  **Save** rewrites the current file in place; **Save project as…** (`Ctrl+Shift+S`)
  starts a new one; **Open project…** (`Ctrl+Shift+O`) restores everything so you
  pick up exactly where you left off. The window title shows the open project. (The
  file is plain JSON, so it stays inspectable and portable between machines.
  Figure **export** moved to `Ctrl+E`.)
- **Overlay files (`.xrdov`)** — the multi-pattern comparison as its **own file
  type**: **File ▸ Export overlay (.xrdov)…** saves just the checked scans (in their
  stack order, data included), their reference overlays, guide lines and view
  settings. Opening one lands straight on the **Waterfall**, ready to compare or
  export; a full project stays a `.xrdlab`. Both open from **Open project…**, by
  drag-and-drop onto the window, or by **double-clicking** them in Explorer.
- **Custom title** — a **Title** field in the controls adds a centered title on top
  of the Single, Waterfall, and Rietveld figures (blank falls back to the pattern
  name). Extra headroom keeps peak labels clear of it.
- **Y-axis scaling (log / sqrt / linear)** — the Single view defaults to **log**,
  so weak peaks next to a dominant one stay visible instead of being flattened.
  **sqrt** (matching Panalytical Data Viewer) and **linear** are also available;
  sqrt/linear keep tick labels in real counts.
- **Automatic peak labelling** — detect peaks and assign each to the nearest
  reflection of the sample's phase(s), annotating with formula + (h k l). Toggle
  between labelling **assigned peaks only** or **every peak** (unassigned peaks get
  their 2θ), with adjustable sensitivity and match tolerance.
- **Peak width (FWHM) & crystallite size** — every detected peak's **full width at
  half maximum** is measured straight from the data (half-max taken above a local
  baseline drawn between the peak's flanking valleys, so a sloped background is
  handled). Tick **Show FWHM on labels** to append it to each Single-view peak label
  (e.g. `GaN (0002) · FWHM 0.033°`), and **Peak table…** opens a sortable list of
  every peak — **2θ, d-spacing, intensity, FWHM, and Scherrer crystallite size**
  (K=0.9, no instrumental-broadening correction, so an upper bound) — exportable to
  **CSV**. Sharp epitaxial reflections read out in the 0.03–0.05° range. The table
  also fits each peak with a **pseudo-Voigt** profile (a more accurate width than the
  raw data crossing) and, when an **instrumental FWHM** is set (Settings ▸ Instrument
  broadening…, from a LaB₆/Si standard), reports **instrument-corrected** Scherrer
  sizes. **Kα-doublet aware:** for scans that record Kα2 (Panalytical `.xrdml`), fits
  model the Kα1 + Kα2 pair (Bragg-placed, measured intensity ratio) and report the
  **Kα1 width** — an unresolved doublet otherwise inflates film peak widths
  substantially (ScN (111) on sapphire: 0.128° true vs 0.182° single-peak).
- **FWHM comparison tab** — the **FWHM** tab (also *Analyze ▸ FWHM comparison*)
  tabulates every reflection across **all checked patterns** — one row per sample,
  one column per reflection — with a selector for **Kα1 FWHM (° or arcsec), data
  FWHM, 2θ, crystallite size, or intensity**, and a trend plot underneath (against
  **temperature** automatically when the sample names carry one, e.g. `600 °C`).
  A reflection that's too weak to be auto-detected in one sample but found in others
  is still measured there when it stands clearly above counting noise. **Export
  CSV** writes every measured quantity; `Ctrl+E` exports the trend plot.
- **Non-destructive processing** — a **Processing** panel toggles **Kα2 stripping**
  (Rachinger), **automatic background subtraction** (asymmetric least squares), and
  **Savitzky–Golay smoothing**. These clean the *displayed and analysed* signal —
  peaks, FWHM and the waterfall all follow — while the underlying data (and anything
  exported) is never altered. Settings are cached and saved in the project.
- **Analysis menu** — **Rocking-curve FWHM…** fits the dominant peak with a
  pseudo-Voigt and **plots the fit** with the width marked, reporting FWHM in ° and
  **arcsec** (the epitaxial-quality metric); **Lattice parameter / strain…** derives
  the cell from assigned peaks (**cubic** a with Nelson–Riley extrapolation, or
  **hexagonal** a, c), shows the reflection-to-reflection spread, and computes
  **% strain** against a reference a₀/c₀ you enter; **Open reciprocal-space map
  (CSV)…** shows a quick log-intensity contour of an RSM.
- **Undo / redo & crash recovery** — **Ctrl+Z / Ctrl+Y** step through data-changing
  actions (loads, guides, labels, assignments). The session
  auto-saves every couple of minutes to `~/.xrdlab/autosave.xrdlab` and offers to
  **restore** it after an unclean exit. The **File ▸ Open recent project** submenu and
  remembered window size / last-used folder get you back to work fast.
- **Click-a-peak** — click any peak in the Single view (it snaps to the nearest
  local maximum, so weak peaks work too) to pop a menu of candidate phases from the
  database (each with formula, hkl, Δ2θ, d-spacing); pick one to lock that
  assignment (a manual override that survives redraws and renders even if the peak
  is below the detection threshold), or clear it.
- **Trackpad / wheel zoom** — two-finger scroll (or mouse wheel) over any plot
  zooms in/out centred on the cursor (log-aware); the toolbar's pan/zoom and Home
  still work.
- **Expected guides from a material** — **Guides from material…** drops labelled
  dotted guide lines at the *expected* reflection positions (per hkl) of any
  database/overlaid material, colour-coded per material, so you can see exactly
  where its peaks should fall relative to your data. Computed at the loaded scan's
  wavelength. **Epitaxial-aware:** because a θ–2θ scan of an oriented film shows
  only the reflection family along the growth direction (e.g. (000ℓ) for a
  c-oriented hexagonal film, (nnn) for (111) rock-salt) — not the full powder
  pattern — the app **assumes the growth orientation** (from your data's strongest
  matching peak, else the material's strongest line) and shows just that family,
  including its weak higher-order harmonics (0002, 0004, …). You can override the
  assumed orientation, pick a different family, or choose the full powder set.
- **Waterfall guide lines** — **Add guide line** (waterfall controls) drops a
  draggable vertical dotted line to check whether peaks line up at the same 2θ
  across the stacked patterns; drag to move (or right-click → **Set position (2θ)…**
  to type the exact angle), right-click to **name** or remove, and a separate
  **Show guide lines** toggle (independent of peak labels). **Guides from material…**
  drops (toggleable, color-coded) guides at a material's expected reflections; their
  labels sit above the graph and auto-thin so they never overlap. On the waterfall,
  scroll-zoom affects only 2θ — the offset y-axis stays fixed so the curves never
  flatten.
- **Rename patterns** — right-click a pattern in the list to rename it; the new name
  is used as the Single-view title and the waterfall edge label.
- **Manual peaks everywhere** — a manually-added peak is tied to its pattern and
  shows on both the Single view (▼ marker) and the Waterfall view (on its curve).
  Right-click a custom label to **edit** or **delete just that one**. Type `_` for
  subscripts in formulas (e.g. `Al_2O_3` → Al₂O₃).
- **Crystallographic notation** — negative Miller indices render as `1̄` (bar) not
  `-1` everywhere (peak labels, reference sticks, tables); formula coefficients are
  auto-subscripted (Al₂O₃).
- **Delete peaks one at a time** — right-click a peak → *Delete this peak label*
  removes only the nearest one (a shoulder next to a main peak included);
  *Restore cleared peaks* undoes it.
- **Manual peaks** — **Add peak…** in the Peaks panel (or right-click the plot)
  marks a peak the auto-detector missed or that has no database match: you give an
  approximate 2θ, it snaps to the nearest local maximum, and you label it (free text
  or an hkl). Manual peaks show a ▼ marker and a draggable label.
- **Left-drag / right-click** — **left-click drags any label** (peak, reference, or
  manual) to reposition it (placement persists across redraws). **Right-click** is
  the menu for everything: assign a phase to the nearest peak, add a custom label,
  clear a label, *Clear manual labels*, *Reset label positions*. **Double-click**
  while the magnifier/pan tool is active resets to the default view.
- **Reference reflection tables** — in the phase-database dialog, double-click a
  phase (or **Reflections…**) to see its full **hkl / d / 2θ (Cu Kα1) / intensity**
  table — the reference-angle table for that material, computed from its stored
  structure with its citation.
- **Import your own reference (CIF)** — **Import CIF…** in the phase-database dialog
  adds a reference from any local `.cif` you have (structure + auto-extracted
  authors/journal/DOI). Use this to bring in structures you've legitimately exported
  from your own crystallography software / licensed tools; XRDLab just reads the
  file you provide.
- **PDF-card reference ticks** — an overlaid Materials Project reference draws as a
  small **tick row along the bottom** (never touching the data), with *every*
  reflection's (hkl) labelled; multiple phases stack in separate rows.
- **Co-located phase labels** — where several phases share an angle they're listed
  comma-separated at the peak (capped at 3 + "…"); Kα doublets are merged.
  Overlaid Materials Project references also label their strongest reflections (hkl).
- **Conventional cell + crystal system** — every reference is computed from the
  **conventional standard structure** (via pymatgen's `SpacegroupAnalyzer`), so peaks
  carry correct conventional Miller indices (ScN → 111/200/220, GaN → 0002/101̄0).
  The **crystal system + space group** (e.g. *cubic · Fm-3m*, *hexagonal · P6₃mc*)
  are stored and shown in the phase list, reflection table, and Citations tab.
- **Phase database for peak identification** — a local, growable database
  (`~/.xrdlab/phase_db.json`) stores each phase as **wavelength-independent
  d-spacings**, so once a material is in it, peaks in *any* dataset (any radiation)
  are identified with a candidate phase + (h k l). It grows automatically from
  every overlay, and **Settings ▸ Phase database…** lets you add formulas or seed a
  common set (GaN, ScN, AlN, Si, Al₂O₃, …). Tick **Identify from phase database**
  in the Peaks panel to use it. *(Local match-by-d — a growing personal database,
  not a full ICDD/PDF search-match.)*
- **Multi-phase references** — enter several formulas (e.g. `ScN, GaN, Al2O3`) to
  overlay and assign peaks against all of them at once. When a scan is loaded the
  reference is simulated at the **measured wavelength** (toggle *Match sample
  wavelength*) and clipped to the scan's 2θ range, so the sticks line up and the
  overlay isn't over-populated.
- **Filename-derived labels** — a loaded file is labelled from its name (e.g.
  `XRD_5292_GaN_ScN_260713_1551` → “GaN/ScN”). The parsing regex and which field
  becomes the label are user-configurable under **Settings ▸ Filename parsing…**
  (with a live preview), so other naming conventions are supported without code
  changes. The full filename stays in the list tooltip and metadata.
- **Stacked waterfall plots** — vertical offset per pattern so peaks never overlap
  and 2θ shifts are obvious; per-curve normalization, edge labels, and a
  **log (default) / linear** Y-scale (log offsets each curve by decades so weak
  peaks show). The active scale type is shown on the y-axis label on every view.
- **Polymorph picker** — in the phase-database dialog, **Choose polymorph…** lists a
  formula's candidate structures (space group / cell for COD, space group + energy
  above hull for Materials Project) so you add the *right* polymorph (e.g. wurtzite
  vs zincblende GaN) instead of the first match.
- **Rietveld view** — the classic figure: observed (red dots), calculated (black
  line), background (green), difference obs−calc (blue) below, with reflection
  ticks. Fed from any refinement engine via a simple CSV of
  `2theta, yobs, ycalc, ybkg` (+ optional `reflections`).
- **Materials Project reference overlays** — type a formula (e.g. `ScN`, `GaN`),
  and the app simulates its XRD stick pattern from the MP crystal structure
  (pymatgen `XRDCalculator`) and overlays it as PDF-card-style reflection lines
  with `(h k l)` labels. Structures are cached locally for offline reuse.
- **Citations tab** — cross-references each identified peak to the source
  literature of its phase, using **openly-licensed sources**: Materials Project
  provenance (CC-BY 4.0) and the **Crystallography Open Database (COD)** (open CIFs
  with source citations; no API key needed — choose the source in the phase-database
  dialog). DOIs are formatted into full citations via the free **Crossref** API
  (author, year, title, journal, volume, pages), with a per-peak table (2θ, d, hkl,
  intensity) and links to the DOI / MP / COD record. Export to **BibTeX**.
  *(Openly-licensed bibliographic provenance for the reference structures — it does
  not scrape paywalled journals or textbooks.)*
- **Publication vector export** — PDF/EPS/SVG keep *editable* text (not outlined),
  ready for journal typesetting; PNG at 300 dpi for previews.
- **ML seam** — `xrdlab.ml` defines `PeakLabeler` / `PhaseIdentifier` protocols
  (plus a scipy-prominence baseline) so a future trained model for auto peak
  labelling / phase ID drops in without touching the plotting code.

---

## High-resolution XRD (HRXRD menu)

XRDLab reads every Panalytical scan type on its **own axis**: coupled 2θ-ω / Gonio
scans on 2θ, **rocking curves (ω scans) on ω**, φ scans on φ, and multi-scan **area
measurements (reciprocal-space maps)** open straight into the map tool. It reads the
optics from the file: a hybrid / Ge-crystal **monochromator** means Kα1-only data, so
no doublet is modelled. Without one, fits include Kα2 — Bragg-placed in 2θ, or a
constant Δω = θ(Kα2) − θ(Kα1) for rocking curves. References and phase labels
(2θ positions) are never drawn on ω/φ scans. Instead the Single view shows the
fitted rocking curve with its FWHM in arcsec, or the φ-scan peaks and symmetry.

| Tool | What you get |
|---|---|
| **Rocking curves — FWHM, dislocations, tilt/twist** | All checked ω scans overlaid on Δω (arcsec), normalized; FWHM (pseudo-Voigt / Gaussian / Lorentzian fit, Kα1), optional instrument-resolution correction; **Dunn–Kogh threading-dislocation density** ρ = β²/(4.35 b²) with Burgers-vector presets (GaN, AlN, InN, ZnO, ScN, TiN, Si, Ge, GaAs, InP, sapphire, 4H-SiC). Rows sharing a *Sample* name combine into **mosaic tilt and twist** (β(χ)² = (β_tilt cos χ)² + (β_twist sin χ)², χ read from the file), giving ρ_screw and ρ_edge, plus **Williamson–Hall-ω** (tilt + lateral coherence length L∥) from several symmetric orders. Reflections are named automatically from each scan's 2θ. CSV + vector-figure export. |
| **Reciprocal-space map** | Qx–Qz (or ω–2θ) log contour map; substrate and film peaks found automatically (a shoulder is never mistaken for a second peak) or placed by clicking; **in-plane / out-of-plane lattice parameters** for hexagonal (0001) or cubic (001) geometry from any (hkl); **strain ε∥, ε⊥ and degree of relaxation R**; pseudomorphic and relaxation lines drawn. CSV (ω, 2θ, Qx, Qz, I) + figure export. |
| **Film thickness from fringes** | Pendellösung / Laue-fringe thickness around any 2θ-ω peak, t = λ / (2 Δsinθ). It tracks the fringe comb outward from the peak using the exact Laue side-maximum positions, and rejects counting-noise wiggles, so the result carries an honest ± uncertainty and per-side values. |
| **Williamson–Hall** | Vertical coherence length D and microstrain ε from several orders of one phase (Kα1 widths, instrument-corrected), with a flag when the data aren't broadening-dominated. |
| **φ-scan symmetry** | Peak positions, spacing, n-fold symmetry — e.g. 6 peaks on a {200} scan of a (111) cubic film = two rotation-twin domains. |
| **Lattice parameter / strain** | From assigned 2θ-ω peaks (Nelson–Riley for cubic; a, c for hexagonal), % strain vs a reference. |

Rocking curves also appear in the **FWHM** tab, grouped by reflection (e.g.
*ω scan GaN (0002)*), so a growth series can be compared in arcsec across samples.

**Validation.** Each analysis is tested against synthetic data with known answers
(77 tests). Tilt/twist is recovered to < 0.3%, RSM film lattice parameters to
0.001 Å and relaxation to 0.1%. Fringe thickness is checked over 10–250 nm films
at several noise levels and step sizes: 27 of 28 cases are within 5%, with a median
error of 0.3% and no systematic bias.

---

## Sharing with other computers — automatic updates

Every installed copy is a clone of one GitHub repository. You publish; everyone
else updates on their next launch.

**Install on another computer** (once, needs git and Python 3.11):

```powershell
git clone https://github.com/<you>/xrdlab.git
cd xrdlab
.\XRDLab.bat        # first run sets everything up, registers .xrdlab/.xrdov files
```

**Publish an update** (from the machine you develop on):

```powershell
.\.venv\Scripts\python.exe tools\publish_update.py "What changed"
```

It runs the full test suite and **refuses to publish if anything fails**, then
commits and pushes. Every other copy checks in the background when XRDLab starts.
If it's simply behind, it fast-forwards to the new version (reinstalling
dependencies only if they changed) and says *restart to use it*.
**Help ▸ Check for updates now** does the same on demand. **Help ▸ Automatically
update on launch** turns it off, and **Help ▸ About** shows the installed version.

A copy with **local edits or unpublished commits is never overwritten**. That's
normally your development machine, so publish from there instead. Updates only
fast-forward; nothing is merged or rewritten. Settings, the phase database and the
API key live in `~/.xrdlab/` on each machine and are never part of the repository.

---

## Setup — one step

**You don't set anything up by hand.** Just launch it and the first run creates the
virtual environment and installs everything automatically:

- **Windows:** double-click **`XRDLab.bat`**. The first run shows a console while it
  installs (a few minutes for pymatgen/PySide6); every run after that opens the app
  instantly with no console. If it won't start, use **`XRDLab (debug).bat`** to see
  the traceback.
- **Any platform / terminal:**

  ```bash
  python run.py
  ```

  `run.py` uses only the standard library, so it works before anything is installed —
  it builds `.venv`, installs XRDLab into it, then launches. Re-run it any time; it
  only installs once.

<details><summary>Manual setup (optional)</summary>

```powershell
cd xrdlab
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[mp]        # full install (Materials Project + pymatgen)
# pip install -e .          # lighter/faster core only — see "Optional extras" below
```
</details>

**Optional extras.** The base package (`pip install -e .`) is small and fast to
install — loading, plotting, peak analysis, **FWHM**, and the bundled phase database
all work with it. The heavy **Materials Project / pymatgen** stack (structure
simulation, overlays, CIF import, DB seeding) is the `[mp]` extra
(`pip install -e .[mp]`); `run.py` / `XRDLab.bat` install it by default so the
double-click experience is complete. `[build]` adds PyInstaller (below).

**Faster launches (Windows).** Real-time antivirus scanning of the many files in
`.venv` is usually the biggest cause of a slow first launch. Excluding the folder
once (admin PowerShell) makes startup snappy:

```powershell
Add-MpPreference -ExclusionPath "$PWD\.venv"   # run from the xrdlab folder
```

**One-file executable (no Python needed for end users).**

```powershell
pip install -e .[mp,build]
pyinstaller xrdlab.spec        # -> dist\XRDLab.exe
```

### Materials Project API key

The MP overlay needs an API key. **Get/rotate one** at
<https://next-gen.materialsproject.org/api>. You can provide it two ways:

- **In the app (persistent):** *Settings ▸ Set Materials Project API key…* (or the
  **Set API key…** button in the Materials Project panel). The key is saved to
  `~/.xrdlab/config.json` and reused on every launch; the panel shows a masked
  status and the input is password-masked. Leave the field blank to clear it.
- **Environment / `.env`:**

  ```powershell
  copy .env.example .env
  # edit .env and set MP_API_KEY=<your key>
  ```

Resolution order is **saved key → `MP_API_KEY` env/`.env`** (an explicit argument
to `MPClient` wins over both). The key is **never** stored in source. Everything
except the MP overlay works without it.

---

## Running

**Double-click launch (no terminal):** use the desktop **XRDLab** shortcut, or
`XRDLab.bat` in the project folder (which bootstraps the environment on first run,
then runs windowless via `.venv\Scripts\XRDLab.exe`). **Updates are instant** — just
relaunch after any code change, no rebuild. Your database / settings live in
`~/.xrdlab/` and are never touched by updates. If it won't start, run
`XRDLab (debug).bat` to see the traceback.

**Opening files by double-click (Windows).** First-run setup registers `.xrdlab`
projects and `.xrdov` overlays to open in XRDLab (per-user, no admin), and adds
XRDLab to *Open with* for `.xrdml` scans without changing their default. To
(re)apply or undo it by hand:

```powershell
.\.venv\Scripts\python.exe tools\register_filetypes.py              # register
.\.venv\Scripts\python.exe tools\register_filetypes.py --unregister # undo
```

If you earlier ticked *Always* for another app on `.xrdlab`, Windows keeps that
choice (programs can't change it): right-click the file ▸ **Open with ▸ Choose
another app ▸ XRDLab**, tick **Always use this app**. The app also accepts files on
its command line: `XRDLab.exe path\to\file.xrdlab` (or a scan to load). The
terminal entry point is now `xrdlab-cli`.

**From a terminal:**

```powershell
python -m xrdlab.app          # launch the GUI
python examples\sample_figures.py   # no-GUI demo -> examples\out\*.pdf/.svg/.png
pytest                        # run the parser tests
```

### Quick GUI walkthrough
1. **File ▸ Open patterns…** (or drag files onto the window) to load scans.
2. **Single** tab — pick a **Y scale** (log by default reveals weak peaks; sqrt/linear also available).
3. **Peaks & display** panel — tick **Label peaks**; choose *Assigned only* or
   *All peaks*, and tune sensitivity / match tolerance.
4. **Materials Project** panel — enter one or more formulas (e.g. `ScN, GaN`),
   *Overlay reference*; peaks are then labelled with phase + (h k l).
5. **Waterfall** tab — check patterns in the list, tune the offset gap.
6. **File ▸ Open Rietveld CSV…** to view a refinement in the **Rietveld** tab.
7. **File ▸ Export current figure…** — pick `.pdf`, `.eps`, `.svg`, or `.png`.

---

## Project layout

```
src/xrdlab/
  core/       Pattern model + I/O (xrdml, generic, rietveld) + processing,
              project save/load, pseudo-Voigt fitting
  plotting/   style, export, waterfall, rietveld, MP overlay
  mp/         Materials Project client + pattern simulation
  ml/         future ML interfaces (stubs + a baseline peak labeller)
  ui/         PySide6 window, panels, dialogs, matplotlib canvas
  app.py      entry point (python -m xrdlab.app)
run.py        zero-setup launcher (bootstraps the venv)
xrdlab.spec   PyInstaller one-file build
examples/     scripted demo
tests/        parser / FWHM / HRXRD / project / updater / startup tests
```

## Performance & startup
- **Lazy heavy imports** — scipy, pymatgen and mp-api are imported only when first
  used, never at launch (a startup test enforces this), so the app opens on just
  numpy + matplotlib + Qt. A **splash screen** shows immediately and pymatgen is
  **pre-warmed in a background thread** so the first Materials Project overlay isn't
  a cold stall.
- **Display decimation** — large scans (tens of thousands of points) are peak-preserving
  down-sampled *for drawing only*; math, fitting, FWHM and export always use full data.
- **Peak/FWHM caching** — detection + FWHM are cached per pattern and only recomputed
  when the data or sensitivity changes.
- See **Setup** for the antivirus-exclusion tip (the biggest Windows launch-speed win)
  and the lighter `pip install -e .` core-only option.

## Roadmap
- XRR reflectivity mode (log-scale, thin-film fringes) — parser is structured for it.
- Le Bail / full-pattern fitting building on the pseudo-Voigt single-peak fitter.
- Trained ML peak labelling / phase identification against MP references.
