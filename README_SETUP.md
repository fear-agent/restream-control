# Restream Control Setup Guide

Use this guide when setting up Restream Control on a new Windows machine.

## 1. Install Required Programs

Install these first:

- OBS Studio: https://obsproject.com/download
- VLC: https://images.videolan.org/vlc/download-windows.html
- Streamlink: https://streamlink.github.io/install.html

Restream Control supports OBS Studio. Streamlabs Desktop is not supported.

## 2. Download Restream Control

1. Open the GitHub Releases page.
2. Download `RestreamControl-VERSION.zip`.
3. Extract it somewhere permanent, such as:

```text
C:\Users\YOURNAME\Documents\RestreamControl
```

4. Run:

```text
Restream Control.exe
```

Keep the extracted folder together.

## 3. Run Setup Wizard

In Restream Control, open `Setup Wizard`.

Use it to:

- Check VLC, Streamlink, and OBS connection.
- Open OBS websocket settings.
- Choose template setup or custom layout.
- Start audio mapping.
- Create a Start Menu shortcut.

If something fails, click `Copy Diagnostics` and paste that report when asking for help.

## 4. Enable OBS WebSocket

In OBS Studio:

1. Open `Tools`.
2. Open `WebSocket Server Settings`.
3. Enable the websocket server.
4. Use port `4455`.
5. Copy or set the password.

In Restream Control:

1. Open `Settings`.
2. Enter host, port, and password.
3. Click `Save`.
4. Click `Test`.

Typical settings:

```text
Host: localhost
Port: 4455
```

## 5. Choose OBS Layout Setup

Use one of these:

- `Template Setup`: creates the included default Restream Control scenes and sources.
- `Custom Layout`: lets you draw your own layout and apply it to OBS.
- OBS import: import `obs-template\Restream_Control_Template.json` manually in OBS.

Most new users should start with `Template Setup`.

## 6. Audio

Open `Audio` after runner VLC windows are launched.

Recommended:

1. Click `Load Audio Windows`.
2. For runner audio, use `Window title must match`.
3. Click `Apply Audio Mapping`.
4. Unmute only the audio sources you want live.

Do not mute VLC or turn VLC volume to 0 if OBS is capturing VLC audio. To avoid hearing VLC locally, route VLC to an unused output device in Windows:

```text
Windows Settings > System > Sound > Volume mixer > VLC media player
```

Then control what goes live from the app's `Audio` tab or OBS, not from VLC.

Optional: in `Settings`, choose `VLC Audio Output` to have Restream Control launch VLC directly to a selected Windows playback device. Click `Save & Relaunch` to apply it to the current race.

## 7. Basic Race Workflow

1. Open `Setup`.
2. Choose `2P` or `4P`.
3. Select runners.
4. Enter commentator names.
5. Click `Launch Streams`.
6. Open `Cropping`.
7. Take screenshots and apply crops.
8. Open `Sync` if stream timing needs adjustment.
9. Open `Checklist` before going live.

## 8. Troubleshooting

First, open `Setup Wizard` and click `Refresh Checks`.

If streams do not launch, check that Streamlink and VLC are installed.

If OBS actions fail, check that:

- OBS Studio is open.
- Websocket is enabled.
- The password in Restream Control is correct.

If the app opens and closes immediately, look for:

```text
state\crash.log
```

## Source Mode

Most users should not use source mode.

For development:

```powershell
pip install -r requirements.txt
app\start_restream_app.bat
```
