@echo off
setlocal
cd /d "%~dp0..\.."
.\vhome\Scripts\python.exe .\src\virtualhome_env\showcase_panel.py --export-samples
pause
