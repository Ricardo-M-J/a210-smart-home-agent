@echo off
setlocal
cd /d "%~dp0..\.."
.\vhome\Scripts\python.exe .\src\virtualhome_env\room_camera_framework.py --attach --port 8080 --snapshot-only --width 1280 --height 720
pause
