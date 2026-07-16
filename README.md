# Restream Control

Restream Control is a Windows app for running 2-player and 4-player restreams in OBS Studio.

It launches Twitch streams through Streamlink/VLC, writes runner and commentator text files, saves crop presets per runner, helps sync delayed streams, controls OBS audio sources, and can create OBS layouts from either the included template or a custom drawn layout.

## Download

For normal use, download the latest release ZIP from GitHub Releases.

1. Download `RestreamControl-VERSION.zip`.
2. Extract it somewhere permanent.
3. Run `Restream Control.exe`.
4. Open `Setup Wizard` inside the app.

Keep the extracted folder together. Do not move the exe away from the folders beside it.

## Required Programs

- Windows 10/11
- OBS Studio
- VLC
- Streamlink

Python is not required when using the release ZIP.

## Main Workflow

1. Open `Setup`.
2. Choose `2P` or `4P`.
3. Select runners and enter commentator names.
4. Click `Launch Streams`.
5. Open `Cropping`, take screenshots, and apply crops.
6. Open `Sync` if streams need delay.
7. Use `Checklist` before going live.

Saved crops are remembered by runner and layout, so repeat runners usually load with their previous crop positions.

## OBS Layouts

Use `Template Setup` if you want the included default Restream Control scenes and source names.

Use `Custom Layout` if you want to draw your own OBS layout inside the app.

Restream Control supports OBS Studio with obs-websocket. Streamlabs Desktop is not supported.

## Audio Note

Do not mute VLC, turn VLC volume to 0, or use `--no-audio` if OBS is capturing VLC audio. If you do not want to hear runner audio locally, route VLC to an unused output device in Windows Volume Mixer. OBS can still capture VLC while your speakers stay quiet.

## Troubleshooting

Open `Setup Wizard` and click `Refresh Checks`.

If you need help, click `Copy Diagnostics` and paste the copied report when asking for support.

If the exe opens and closes, check:

```text
state\crash.log
```
