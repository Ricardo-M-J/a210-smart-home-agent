@echo off
setlocal
cd /d "%~dp0..\.."
.\vhome\Scripts\python.exe .\src\virtualhome_env\scripted_showcase_demos.py --scenario health_event --fps 10 --width 1280 --height 720
pause
