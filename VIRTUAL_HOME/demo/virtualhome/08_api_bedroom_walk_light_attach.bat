@echo off
setlocal
cd /d "%~dp0..\.."
.\vhome\Scripts\python.exe .\src\virtualhome_env\virtualhome_api_motion_demo.py --attach --scenario bedroom_walk_light --fps 10 --width 1280 --height 720 --camera-mode AUTO --fixed-camera-fov 58 --fixed-camera-height-ratio 0.38 --time-scale 1.35
pause
