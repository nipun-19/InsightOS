# InsightOS release build notes

## Version authority
- Application and packaging version: `1.0.0`
- Authoritative source: `src/version.py`
- Packaging metadata reads from that source via `pyproject.toml`

## Requirements
- Python 3.11 or 3.12
- PySide6 runtime dependency
- PyInstaller for the frozen executable build
- Inno Setup (`iscc`) for the Windows installer build, if available

## Installer scope and user data
- The installer is per-user and does not request administrator privileges.
- Application files are installed under `%LOCALAPPDATA%\Programs\InsightOS`.
- Settings and tracking data remain under `%LOCALAPPDATA%\InsightOS` and are
  not removed by uninstall.
- Uninstall removes only the current user's `InsightOS` Run value. The saved
  autostart preference remains in settings and is reapplied on the next launch
  after reinstall.

## Build commands

From the project root:

```powershell
python -m pip install -U pip
python -m pip install -r .\requirements.txt
python -m PyInstaller --clean --noconfirm --distpath dist --workpath build/.work --specpath build build/InsightOS.spec
```

If using the provided script:

```powershell
powershell -ExecutionPolicy Bypass -File .\build\build_release.ps1
```

## Output locations
- Windows executable: `dist/InsightOS/InsightOS.exe`
- Windows installer script: `build/InsightOS.iss`
- Final installer naming convention: `InsightOS-1.0.0-Setup.exe`

## Code signing
- No certificate is configured in this environment.
- No signing claim is made.
- Windows SmartScreen and trust warnings remain a real distribution consideration for public release.

## Public release note
- The website download target is intentionally set to the GitHub Releases latest artifact URL pattern until the actual release host is configured.
- Update the URL in `website/index.html` if the release host changes.
