@echo off
rem Same as XRDLab.bat but keeps a console open and shows the full traceback —
rem use this if the app won't start. It also bootstraps the venv on first run.
cd /d "%~dp0"
where py >nul 2>nul && ( py run.py ) || ( python run.py )
echo.
echo (XRDLab exited. Press any key to close.)
pause >nul
