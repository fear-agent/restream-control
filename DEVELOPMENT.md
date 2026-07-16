# Development

These notes are for working from source or building a GitHub release ZIP. Normal users should download the release ZIP and run `Restream Control.exe`.

## Run From Source

```powershell
pip install -r requirements.txt
app\start_restream_app.bat
```

## Build A Release ZIP

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_release.ps1 -Version v0.1.4
```

The release ZIP is created under:

```text
release\
```
