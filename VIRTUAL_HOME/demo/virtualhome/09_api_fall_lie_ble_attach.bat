@echo off
setlocal
cd /d "%~dp0..\.."
.\vhome\Scripts\python.exe .\src\virtualhome_env\virtualhome_api_motion_demo.py --attach --scenario fall_lie_ble --fps 10 --width 1280 --height 720 --camera-mode AUTO --time-scale 1.0
pause
