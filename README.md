# Restream Control

Restream Control is a Windows app for running 2-player and 4-player restreams in OBS Studio.

It supports two playback methods: Streamlink/VLC windows, or Streamlink/FFmpeg local feeds sent directly to OBS. It also writes runner and commentator text files, saves crop presets per runner, helps sync delayed streams, controls OBS audio sources, and can create OBS layouts from either the included template or a custom drawn layout.

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
- `VLC Windows` playback: VLC and Streamlink
- `OBS Media Feeds` playback: FFmpeg and Streamlink

Python is not required when using the release ZIP.

Open `Setup Wizard` after starting the app. It checks the tools required for the playback method you selected and can install missing tools with Windows Package Manager, or open the official downloads when that is unavailable.

## Playback Methods

Choose one method on `Setup`. Cropping, Sync, Audio, and Custom Layout follow that choice automatically.

- `Standard: VLC Windows`: the established workflow. Each runner opens in a VLC window.
- `Direct to OBS: Media Feeds`: no VLC windows. Streamlink and FFmpeg send feeds directly to OBS. On first use, open `Direct OBS` and click `Create 2P/4P OBS Layouts`. Its `Direct quality` control applies when a feed is started or restarted.

## Main Workflow

1. Open `Setup`.
2. Choose `2P` or `4P`.
3. Select runners and enter commentator names.
4. Choose `VLC Windows` or `OBS Media Feeds`. For Direct OBS, create the Media layouts once, then launch the race.
5. Open `Cropping`, take screenshots, and apply crops.
6. Open `Sync` if streams need delay.
7. Confirm the OBS scene, audio levels, and saved crops before going live.

Saved crops are remembered by runner and layout, so repeat runners usually load with their previous crop positions.

## OBS Layouts

Use `Template Setup` if you want the included default Restream Control scenes and source names. It follows the playback method selected on Setup, creating either VLC Restream scenes or Direct OBS Media Restream scenes.

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
