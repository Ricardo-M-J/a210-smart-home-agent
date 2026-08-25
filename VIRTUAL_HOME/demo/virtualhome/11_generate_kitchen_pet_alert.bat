@echo off
setlocal
cd /d "%~dp0..\.."
.\vhome\Scripts\python.exe .\src\virtualhome_env\virtualhome_api_pet_demo.py --attach --pet-type cat --fps 10 --width 1280 --height 720
pause
