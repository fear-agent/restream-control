# Restream Control

Restream Control is a Windows app for running 2-player and 4-player restreams in OBS Studio.

It supports two playback methods: Streamlink/VLC windows, or local Streamlink HTTP feeds sent directly to OBS. It also writes runner and commentator text files, saves crop presets per runner, helps sync delayed streams, controls OBS audio sources, and can create OBS layouts from either the included template or a custom drawn layout.

## What's New in v0.3.0

- Settings, runners, crops, layouts, screenshots, logs, and generated OBS text now live in `%LOCALAPPDATA%\RestreamControl`, separate from application files.
- Existing portable data is migrated automatically when the new version is run from the previous folder. `Settings` also includes `Import Previous Installation` when the new version was extracted elsewhere.
- Existing OBS file-based runner and commentator text sources are automatically repointed to the shared app data folder the next time names are updated.
- Direct OBS now uses persistent local Streamlink HTTP feeds. The retired FFmpeg/UDP relay is no longer required.
- Direct feeds can be started, restarted, and replaced while OBS is live, with staggered multi-runner startup and automatic migration of older Direct source URLs.
- Direct feed rows distinguish `Ready`, `Playing`, and `Offline`, and wait for an offline runner to return without requiring a relaunch.
- Preferred quality now includes 576p and 540p source variants before falling back to 480p.
- Direct sync uses OBS's native delay filter, and the 2P sync preview preserves the complete simultaneous OBS screenshot.
- Custom Layout shows live position, size, and edge-distance measurements while boxes are drawn, moved, resized, or nudged.

## Download

For normal use, download the latest release ZIP from GitHub Releases.

1. Download `RestreamControl-VERSION.zip`.
2. Extract it somewhere permanent.
3. Run `Restream Control.exe`.
4. Open `Setup Wizard` inside the app.

Keep the extracted folder together. Do not move the exe away from the folders beside it.

To check for future releases from inside the app, open `Settings` and click `Check for Updates`.

## Updating

User data is stored separately from the downloaded application at:

```text
%LOCALAPPDATA%\RestreamControl
```

Packaged releases can update themselves from `Settings`:

1. Click `Check for Updates`.
2. Click `Install` when a newer release is available.
3. Restream Control downloads the release ZIP and SHA-256 file, verifies the package, stops Direct feeds, replaces only application files, and restarts.

The prior packaged version is retained under `%LOCALAPPDATA%\RestreamControl\updates\backups`. Use `Restore Previous Version` in Settings to roll back application files. If an updated app cannot confirm a healthy startup, the updater restores and launches the prior version automatically.

Automatic installation requires a GitHub release containing both `RestreamControl-vX.Y.Z.zip` and `RestreamControl-vX.Y.Z.zip.sha256`. Source/BAT users should update with GitHub Desktop.

For the one-time move from v0.2.x or an earlier portable v0.3.0 build:

- If the updated files are extracted over the previous application folder, the first launch migrates the old data automatically without deleting it.
- If the update is extracted into a different folder, open `Settings`, click `Import Previous Installation`, and choose the old extracted folder. Restart Restream Control after the import.

The release package contains `data\example_runners.csv` only as a first-run seed. It does not contain `data\runners.csv`, so an update cannot replace a user runner list.

## Required Programs

- Windows 10/11
- OBS Studio
- `VLC Windows` playback: VLC and Streamlink
- `OBS Media Feeds` playback: Streamlink

Python is not required when using the release ZIP.

Open `Setup Wizard` after starting the app. It checks the tools required for the playback method you selected and can install missing tools with Windows Package Manager, or open the official downloads when that is unavailable.

## Playback Methods

Choose one method on `Setup`. Cropping, Sync, Audio, and Custom Layout follow that choice automatically.

- `Standard: VLC Windows`: each runner opens in a VLC window.
- `Direct to OBS: Media Feeds`: no VLC windows. Streamlink serves one local HTTP feed per runner directly to OBS. OBS decodes each runner once and reuses that input for independently cropped Game, Tracker, Timer, and Facecam items. Existing Direct layouts from v0.2.4 or earlier are migrated automatically from the retired UDP transport when the next race starts, including while OBS output is active. On first use, open `Direct OBS` and use `First-time Direct OBS setup` > `Create Direct Layouts`. Its `Direct quality` control applies when a feed is started or restarted.

Direct feeds may be started before or after the OBS output. When OBS is already streaming or recording, `Start Direct OBS Feeds` on Setup automatically starts runners one at a time to avoid initializing every decoder at once. Layout creation and source-setting repairs still require the OBS output to be stopped. Individual runner restart/replace remains available during a live race.

## Sync

The `Sync` screenshot captures the full 2P or 4P OBS race scene in one frame, so every visible timer represents the same instant. For Direct OBS, delays use OBS's native async delay filter and do not restart a runner feed. Direct delays support up to 20 seconds; use VLC Windows for longer delays.

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

Use `Custom OBS Layout` if you want to draw your own OBS layout inside the app. Selected boxes show exact `X`, `Y`, width, height, and distance from every 1920x1080 canvas edge. Measurement guides update while moving or resizing boxes, and multiple selected boxes show their combined bounds.

Restream Control supports OBS Studio with obs-websocket. Streamlabs Desktop is not supported.

## Audio Note

Do not mute VLC, turn VLC volume to 0, or use `--no-audio` if OBS is capturing VLC audio. If you do not want to hear runner audio locally, route VLC to an unused output device in Windows Volume Mixer. OBS can still capture VLC while your speakers stay quiet.

## Troubleshooting

Open `Setup Wizard` and click `Refresh Checks`.

If you need help, click `Copy Diagnostics` and paste the copied report when asking for support.

If the exe opens and closes, check:

```text
%LOCALAPPDATA%\RestreamControl\state\crash.log
```
