# Restream Control

Windows helper app for launching and managing 2-player or 4-player restreams.

**Platform support:** Restream Control is currently Windows-only and has only been tested on Windows 10/11.

The app coordinates Streamlink/VLC runner feeds, OBS text files, OBS crop values, screenshots, and simple stream delay controls.

New users should start with [README_SETUP.md](README_SETUP.md).

## What It Does

- Launches Twitch runner feeds through Streamlink into VLC windows titled `RUNNER 1` through `RUNNER 4`.
- Writes local OBS text files for runner names, commentator names, and race mode.
- Saves the last race setup so a runner slot can be reloaded later.
- Captures screenshots of the runner VLC windows for crop setup.
- Applies crop values to OBS sources through OBS websocket.
- Reads OBS audio-capable inputs and provides mute/volume controls.
- Builds a starter OBS scene from the included template.
- Provides a custom OBS layout editor for drawing and applying source positions.
- Cleans unused Restream Control scene items from custom OBS layouts.
- Sends pause/resume timing to VLC windows to delay runner feeds.

## Folder Layout

- `app/` contains the desktop app and helper scripts.
- `data/runners.csv` is the tracked starter runner list.
- `app/obs_text/` is generated locally and should be used by OBS text sources.
- `app/crop_screenshots/` is generated locally and can be cleared often.
- `app/sync_screenshots/` is generated locally by the Sync Tool timer screenshot feature.
- `app/state/` is generated locally and stores current race state, crop presets, and logs.
- `examples/obs_text/` contains example OBS text files only.
- `obs-template/` contains an importable OBS starter scene collection and artwork assets.
- `examples/obs_source_names.txt` lists the default OBS source names for 2P and 4P layouts.

The generated `app/obs_text/`, `app/crop_screenshots/`, `app/sync_screenshots/`, `app/state/`, and local config files are ignored by Git.

## Requirements

- Windows 10/11
- Python 3
- VLC
- Streamlink available as the `streamlink` command
- OBS with websocket enabled
- Python packages from `requirements.txt`

Install Python packages:

```powershell
pip install -r requirements.txt
```

## Run

From the app folder:

```powershell
cd C:\Path\To\restream-control\app
python restream_app.py
```

Or run:

```powershell
C:\Path\To\restream-control\app\start_restream_app.bat
```

The batch launcher prefers `pythonw.exe`, so normal double-click launches should open the app without leaving an extra console window behind. If `pythonw.exe` is not available, it falls back to `python` and keeps the console open so errors are visible.

To create or refresh a desktop shortcut:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Path\To\restream-control\app\create_desktop_shortcut.ps1
```

To create or refresh a Start Menu shortcut:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Path\To\restream-control\app\create_desktop_shortcut.ps1 -Location StartMenu
```

Before launching streams, the app checks Streamlink and VLC. It also asks Streamlink to verify each selected Twitch channel has playable streams. Offline or mistyped channels are reported and skipped, while the available runner streams still launch.

VLC is launched with player arguments that disable the media title overlay and on-screen display, so startup text like `fd://` and pause/play icons should not appear over runner feeds. Streamlink is also launched with `--player-no-close` so it does not intentionally close VLC when a stream ends.

## OBS Setup Notes

Point OBS text sources at files under:

```text
C:\Path\To\restream-control\app\obs_text
```

The app writes:

- `runner1.txt`
- `runner2.txt`
- `runner3.txt`
- `runner4.txt`
- `comm_names.txt`
- `race_mode.txt`

The crop tool expects OBS sources or group items with names such as:

- `4P R1 Stream`
- `4P R1 Tracker`
- `4P R1 Timer`
- `2P R1 Stream`
- `2P R1 Tracker`
- `2P R1 Timer`

Use the Checklist tab before an event to confirm scripts, packages, Streamlink, VLC, OBS websocket, expected OBS crop targets, saved crop coverage, and the runner CSV are available.

OBS websocket host, port, and password can be edited in the Settings tab. Use `Test` after changing them. The crop tool and main app both use the same saved settings.

The app tabs are:

- `Setup`: race type, runner selection, launch streams, replace a runner, and update OBS text.
- `Wizard`: guided setup for first-run checks, OBS websocket, layout setup, audio, and first race testing.
- `Cropping`: capture runner screenshots, crop Game/Tracker/Timer/Facecam, and save runner crop memory.
- `Sync`: timer screenshots, delay calculator, pause/relaunch controls, and timer image cleanup.
- `Audio`: OBS mixer controls and audio source mapping for runner VLC windows, Discord, and mic sources.
- `OBS Layout`: custom draw-your-own layout editor.
- `OBS Builder`: quick setup for the included default Restream Control OBS template.
- `Checklist`: event-day preflight and quick actions.
- `Settings`: OBS websocket, source mapping, settings import/export, and cleanup buttons.

The Settings tab can export/import app settings as JSON. It also has an OBS Source Mapping editor so another user can map the app's expected source names, such as `4P R1 Stream`, to their own OBS source names.

### OBS Source Mapping

Use this only if your OBS source names do not match the app's default names.

Each line means:

```text
App expected source name = Your actual OBS source name
```

Edit the right side only. For example, if the app expects this:

```text
4P R1 Stream
```

but your OBS source is named this:

```text
Player 1 Capture
```

set the line to:

```text
4P R1 Stream = Player 1 Capture
```

If your OBS source is already named `4P R1 Stream`, leave it as:

```text
4P R1 Stream = 4P R1 Stream
```

The top dashboard summarizes the current layout, saved runner count, OBS connection, crop preset coverage, and screenshot count.

The Checklist tab is the event-day view. It summarizes preflight checks, current race state, crop preset coverage, OBS text file values, screenshots, and a few manual reminders. It also includes direct action buttons for screenshots, saved crops, cropping, Discord, OBS text files, and OBS settings.

The Sync page includes a time-difference calculator. Enter two times such as `1:23`, `1:25.5`, or `01:02:03`, calculate the difference, and send that value to a runner delay field.

The Sync page can also create a `Timer Screenshot`, which captures the visible runner VLC windows and displays one combined 2x2 image ordered as R1 top-left, R2 bottom-left, R3 top-right, and R4 bottom-right.

## OBS Builder vs OBS Layout

New users can start in `Wizard`. It walks through install checks, OBS websocket setup, OBS layout choices, audio mapping, a first race test, and Start Menu shortcut creation.

`OBS Builder` is the fast path. It uses the included Restream Control template names and assets.

- `Scan OBS` reports which expected scenes and sources exist.
- `Create Missing Defaults` adds missing scenes/sources without moving existing scene items.
- `Reset To Default Template` intentionally moves/resizes/reorders the included template items back to the shipped default. It does not delete extra custom sources and leaves audio settings alone.

`OBS Layout` is the custom path. It lets you draw boxes on a 1920x1080 canvas and apply those positions to OBS.

- Draw one box for each source you want: `Game`, `Tracker`, `Timer`, `Facecam`, `Runner Name`, `Comms`, or `Text`.
- The `Load Layout Image` button starts in `obs-template/assets` with `overlay-bg-default.png` for 2P and `overlay-bg-default-4p.png` for 4P as example images.
- `Overlay layer` controls whether the main layout image is an overlay above the feeds or a background behind the feeds. Use a transparent PNG/WebP/GIF for overlays. Use `Behind feeds` for a non-transparent background.
- `Image` regions can be added as extra image sources. Their own `Layer` dropdown controls whether they sit behind feeds, above feeds, or above the overlay.
- Hold `Shift` and click boxes to select multiple boxes. Use arrow keys to nudge selected boxes by 1 pixel, or `Shift` + arrow keys to nudge by 10 pixels.
- Use `Copy runner` to copy either all boxes for one runner or one individual piece, such as only `Game` or only `Timer`, to another runner slot.
- `Undo` reverses layout drawing/moving/deleting changes.
- `Clear Text Boxes` removes extra text boxes from the current custom layout.
- `Remove Unused Sources` removes Restream Control scene items from the current OBS layout scene when they are no longer represented by the current boxes. It does not globally delete OBS inputs or unrelated sources.

If you change a custom layout, apply it to OBS, then remove boxes such as `Tracker` or `Timer`, use `Remove Unused Sources` to remove those old scene items from OBS.

## Audio

The `Audio` tab can read OBS audio inputs and provide mute/volume controls. The `Audio Source Mapper` can create/map runner audio sources for VLC windows and leave them muted by default.

For runner audio sources, set priority to `Window title must match` so each OBS audio capture stays attached to the intended `RUNNER 1`, `RUNNER 2`, `RUNNER 3`, or `RUNNER 4` VLC window.

Discord and mic audio are supported as starter sources, but some device/window properties may still need final adjustment in OBS depending on the user's machine.

## Crop Memory

The app saves the current race to `app/state/current_race.json` when you launch streams, replace a runner, or write names.

The Cropping page uses that state to connect OBS targets like `4P R2 Stream` to the runner currently in slot 2. In the UI, the main stream crop is labeled `Game`. When a crop is applied successfully, it saves a crop preset by Twitch name and source type, for example `runnername + Stream`.

Crop presets are saved separately for the `2P` and `4P` layouts.

When you click `Launch Streams`, the main app automatically connects to OBS through websocket and applies all saved crops for the current race layout. The Checklist tab also has `Apply Saved Crops` as a manual retry if OBS was not ready during launch.

The Cropping page can capture and load the selected runner slot screenshot directly with `Take Screenshot`. Draw a rectangle around `Game`, `Tracker`, `Timer`, or `Facecam`, then click that part's `Apply` button.

Use `Reapply This Runner` to reapply saved crops for only the selected runner slot. Use `Reapply All Runners` to reapply saved crops for every runner in the current race.

## Runner List Memory

If you manually type a runner that is not already in `data/runners.csv`, the app asks whether to save them to the runner list. Saved runners appear in the dropdown the next time the list is loaded.

## Screenshots

The main app captures screenshots from the GUI without opening a separate prompt. It defaults to the current race mode: a 2P race captures Runner 1 and Runner 2, and a 4P race captures all four.

The command-line screenshot helper still supports overriding the slot list if you run it directly.
