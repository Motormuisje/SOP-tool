# Windows Executable Build

This app is packaged with PyInstaller as a one-folder Windows executable.
The resulting launcher is:

```text
dist\SOPPlanningEngine\SOPPlanningEngine.exe
```

The build script also creates a distributable zip:

```text
dist\SOPPlanningEngine-windows.zip
```

## Build

From the repository root:

```powershell
.\scripts\build_exe.ps1
```

The script installs `requirements-build.txt` if PyInstaller is missing, compiles
the key Python entry points, runs PyInstaller with
`packaging\SOPPlanningEngine.spec`, starts the executable briefly to verify
that the Flask home page answers, and zips the `dist\SOPPlanningEngine` folder.

To build without the executable smoke test:

```powershell
.\scripts\build_exe.ps1 -SkipSmoke
```

## Runtime Data

The executable keeps user data out of the install folder. By default it writes
uploads, exports, sessions, and config to:

```text
%LOCALAPPDATA%\SOPPlanningEngine
```

Override this for testing or portable deployments:

```powershell
$env:SOP_APP_DATA_DIR = "C:\path\to\data"
.\dist\SOPPlanningEngine\SOPPlanningEngine.exe
```

## Notes

- The build is `onedir`, not `onefile`, for faster startup and better reliability
  with pandas, pyarrow, matplotlib, openpyxl, and Flask static/template files.
- Do not commit `build\`, `dist\`, or generated `.exe` files.
- The console window is intentionally enabled so startup messages and crashes are
  visible during client support.
