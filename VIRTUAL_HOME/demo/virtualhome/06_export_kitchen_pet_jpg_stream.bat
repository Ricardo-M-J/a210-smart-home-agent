@echo off
setlocal
cd /d "%~dp0..\.."
.\vhome\Scripts\python.exe .\src\virtualhome_env\video_to_jpg_stream.py --video .\outputs\showcase_panel\virtualhome_api_pet\kitchen_pet\kitchen_pet_api_detection.mp4 --jpg-dir .\outputs\showcase_panel\virtualhome_api_pet\kitchen_pet\jpg\kitchen --manifest .\outputs\showcase_panel\virtualhome_api_pet\kitchen_pet\frame_manifest.jsonl --scene kitchen_pet --room kitchen --stream-id kitchen_camera_0
pause
