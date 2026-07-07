# OBS Scene Collection Template

This folder contains a starter OBS scene collection for Restream Control.

## Files

- `Restream_Control_Template.json` - OBS scene collection export.
- `assets/` - background and outline images used by the template.
- `../obs_text/` - example text files for runner and commentator names.

## Import

1. Open OBS.
2. Go to `Scene Collection` -> `Import`.
3. Select `Restream_Control_Template.json`.
4. Switch to the imported `Restream Control Template` scene collection.
5. If OBS reports missing files, open each missing Image or Text source and browse to the matching file in this repo.

## Required Source Names

The app depends on these OBS source names staying the same:

- `2P R1 Stream`, `2P R1 Tracker`, `2P R1 Timer`
- `2P R2 Stream`, `2P R2 Tracker`, `2P R2 Timer`
- `4P R1 Stream`, `4P R1 Tracker`, `4P R1 Timer`
- `4P R2 Stream`, `4P R2 Tracker`, `4P R2 Timer`
- `4P R3 Stream`, `4P R3 Tracker`, `4P R3 Timer`
- `4P R4 Stream`, `4P R4 Tracker`, `4P R4 Timer`
- `Runner 1 Name`, `Runner 2 Name`, `Runner 3 Name`, `Runner 4 Name`
- `Comms Name`

You can move and resize sources in OBS. If you rename these sources, update the OBS Source Mapping in Restream Control.
