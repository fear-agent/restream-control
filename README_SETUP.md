# Restream Control Setup Guide

This guide is for setting up Restream Control on a new Windows machine.

Restream Control is currently Windows-only and has only been tested on Windows 10/11.

Restream Control launches Twitch runner feeds through Streamlink/VLC, writes OBS text files, saves OBS crop presets, and helps sync runner streams.

## 1. Get The App From GitHub

Option A: Download ZIP

1. Open the GitHub repository page.
2. Click `Code`.
3. Click `Download ZIP`.
4. Extract the ZIP somewhere permanent, for example:

```text
C:\Users\YOURNAME\Documents\RestreamControl
```

Option B: Clone with Git

```powershell
cd C:\Users\YOURNAME\Documents
git clone REPOSITORY_URL_HERE restream-control
cd restream-control
```

Replace `REPOSITORY_URL_HERE` with the URL from GitHub's `Code` button.

## 2. Install Required Programs

Install these before running the app.

### Python

Download Python for Windows from the official Python site:

```text
https://www.python.org/downloads/windows/
```

During install, enable:

```text
Add python.exe to PATH
```

After install, open PowerShell and check:

```powershell
python --version
pip --version
```

### VLC

Download VLC for Windows from VideoLAN:

```text
https://images.videolan.org/vlc/download-windows.html
```

The app looks for VLC in the normal install locations:

```text
C:\Program Files\VideoLAN\VLC\vlc.exe
C:\Program Files (x86)\VideoLAN\VLC\vlc.exe
```

### Streamlink

Install Streamlink from the official Streamlink install guide:

```text
https://streamlink.github.io/install.html
```

On Windows, the installer build is usually the easiest choice.

After install, open PowerShell and check:

```powershell
streamlink --version
```

### OBS Studio

Download OBS Studio from the official OBS site:

```text
https://obsproject.com/download
```

OBS Studio 28 and newer includes obs-websocket by default. If you use OBS Studio older than 28, install obs-websocket separately:

```text
https://github.com/obsproject/obs-websocket
```

## 3. Install Python Packages

From the project folder:

```powershell
cd C:\Users\YOURNAME\Documents\restream-control
pip install -r requirements.txt
```

The required Python packages are:

```text
Pillow
obsws-python
streamlink
```

## 4. Start The App

Run:

```text
app\start_restream_app.bat
```

Or from PowerShell:

```powershell
cd C:\Users\YOURNAME\Documents\restream-control\app
python restream_app.py
```

To create a Start Menu shortcut:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File app\create_desktop_shortcut.ps1 -Location StartMenu
```

## 5. Enable OBS Websocket

In OBS:

1. Open `Tools`.
2. Open `WebSocket Server Settings`.
3. Enable the websocket server.
4. Use port `4455` unless you have a reason to change it.
5. Set or copy the websocket password.

In Restream Control:

1. Open `Settings`.
2. Enter OBS websocket host, port, and password.
3. Click `Save`.
4. Click `Test`.

Typical settings:

```text
Host: localhost
Port: 4455
Password: your OBS websocket password
```

## 6. Set Up OBS Text Files

If you want a starter OBS layout, import the included scene collection first:

```text
obs-template\Restream_Control_Template.json
```

In OBS:

1. Open `Scene Collection`.
2. Click `Import`.
3. Select the template JSON file above.
4. Switch to the imported `Restream Control Template` scene collection.
5. If OBS reports missing image or text files, open that source's properties and browse to the matching file in this repo.

The template already uses the default source names that Restream Control expects.

Restream Control writes runner names and race mode to text files.

Default folder:

```text
PROJECT_FOLDER\app\obs_text
```

Create OBS text sources that read from these files:

```text
runner1.txt
runner2.txt
runner3.txt
runner4.txt
comm_names.txt
race_mode.txt
```

The app creates and updates those files automatically.

## 7. Set Up OBS Source Names

The crop memory system needs OBS stream/tracker/timer sources. The default expected names are listed in:

```text
examples\obs_source_names.txt
```

You have two choices.

Option A: Use the default source names in OBS.

Example:

```text
4P R1 Stream
4P R1 Tracker
4P R1 Timer
```

Option B: Use your own OBS source names and map them in Restream Control.

In Restream Control:

1. Open `Settings`.
2. Find `OBS Source Mapping`.
3. Edit the right side only.
4. Click `Save Mapping`.

Example:

```text
4P R1 Stream = Player 1 Capture
```

The left side is what the app expects. The right side is your actual OBS source or group item name.

## 8. First Preflight

Open `Checklist` and click `Refresh Checklist`.

Check for:

```text
VLC installed or available on PATH
Streamlink available
OBS websocket connection
Runner CSV found
OBS crop targets found
OBS text files updating
```

If OBS crop targets are missing, either rename your OBS sources to the default names or update `OBS Source Mapping` in Settings.

## 9. Basic Workflow

1. Open `Setup`.
2. Choose `2P` or `4P`.
3. Enter or select runners.
4. Enter commentator names.
5. Click `Launch Streams`.
6. Open `Checklist`.
7. Click `Take Screenshots`.
8. Open `Cropping Tool`.
9. Crop `Stream`, `Tracker`, and `Timer` for each runner.
10. Use `Save/Apply`.
11. Open `Sync Tool` if runner feeds need delay.

After crops are saved once, future races with the same runners can auto-apply their saved crops.

## 10. Troubleshooting

If streams do not launch:

```powershell
streamlink --version
```

If OBS crop apply fails:

1. Confirm OBS is open.
2. Confirm websocket is enabled.
3. Confirm the password is correct in Settings.
4. Confirm OBS source mapping points to real OBS source names.

If text files do not update:

1. Confirm OBS text sources point to `app\obs_text`.
2. Click `Write Names Only` in Setup.
3. Check the files in `app\obs_text`.

If VLC shows a black screen after a runner ends stream, VLC behavior depends on how the stream disconnects. The app launches VLC with `--play-and-pause`, which can hold the last frame when VLC receives a clean end of input.
