@echo off
rem Double-click to run XRDLab. On the very first run this sets everything up
rem (creates .venv, installs dependencies, registers .xrdlab/.xrdov files);
rem after that it launches instantly. Files dropped on this .bat are opened.
cd /d "%~dp0"

if exist ".venv\Scripts\XRDLab.exe" (
  start "" ".venv\Scripts\XRDLab.exe" %*
) else if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m xrdlab.app %*
) else (
  rem First run: bootstrap with a visible console so progress and any errors show.
  echo Preparing XRDLab for first use...
  where py >nul 2>nul && ( py run.py %* ) || ( python run.py %* )
)
