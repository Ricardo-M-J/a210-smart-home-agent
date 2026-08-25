# VirtualHome Demo Shortcuts

Run these from Windows Explorer by double-clicking, or from PowerShell.

```text
01_generate_bedroom_walk_light.bat  Generate bedroom person enter/leave + light-off demo
02_showcase_panel.bat               Open local Python showcase panel with clickable scenarios
03_export_interface_samples.bat     Export frame/result/feedback JSONL samples
04_editor_attach_smoke_test.bat     Attach to Unity Editor Play mode on port 8080 and capture one image
05_capture_room_cameras_720p.bat    Capture room-camera 720p snapshots from Unity Editor Play mode
06_export_kitchen_pet_jpg_stream.bat Re-export pet MP4 into 720p/10fps JPG frames
07_generate_fall_bluetooth_emergency.bat Generate fall detection + BLE watch/phone emergency demo
08_api_bedroom_walk_light_attach.bat Attach to visible VirtualHome.exe and run fixed-camera person in/out + light-off script
09_api_fall_lie_ble_attach.bat       Attach to visible VirtualHome.exe and run abnormal-posture BLE script
10_generate_scripted_showcase_demos.bat Generate fire-smoke and health-assistant demos
11_generate_kitchen_pet_alert.bat     Attach to VirtualHome.exe and generate real pet model + phone alert demo
12_generate_fire_smoke_alarm.bat      Generate fire-smoke + phone alert demo
13_generate_health_assistant.bat      Generate health assistant + playable music demo
14_generate_smart_mode_security_demos.bat Generate optimized 04 normal-mode pet alert and 07 away-mode stranger alert demos
```

For the live Unity workflow, open `virtualhome_unity_project` in Unity Editor, open `Assets/Story Generator/Scene/Scene_0.unity`, press `Play`, then run `04` or `05`.

For the prebuilt simulator API workflow, open `windows_exec/windows_exec.v2.2.4/VirtualHome.exe`, choose Windowed if the launcher appears, press `Play!`, then run `08`, `11`, or `09`. Run `14` after `08` and `11` if you want to rebuild the optimized showcase-layer 04/07 videos.
