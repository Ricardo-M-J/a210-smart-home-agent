@echo off
setlocal
cd /d "%~dp0..\.."
.\vhome\Scripts\python.exe .\src\virtualhome_env\smart_mode_showcase_demos.py --scenario all --fps 10 --width 1280 --height 720
pause
