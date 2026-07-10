param(
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

python -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
    python -m pip install -r requirements-build.txt
}

python -m py_compile main.py ui/paths.py ui/app.py modules/planning_engine.py

python -m PyInstaller --noconfirm --clean packaging\SOPPlanningEngine.spec

$ExePath = Join-Path $RepoRoot "dist\SOPPlanningEngine\SOPPlanningEngine.exe"
if (!(Test-Path $ExePath)) {
    throw "Build finished, but executable was not found at $ExePath"
}

if (!$SkipSmoke) {
    $env:SOP_NO_BROWSER = "1"
    $env:SOP_NO_BANNER = "1"
    $env:SOP_PORT = "5055"
    $env:SOP_APP_DATA_DIR = Join-Path $RepoRoot "tmp\exe-smoke-data"

    $LogPath = Join-Path $RepoRoot "tmp\exe-smoke.out.log"
    $ErrPath = Join-Path $RepoRoot "tmp\exe-smoke.err.log"
    New-Item -ItemType Directory -Force -Path (Split-Path $LogPath) | Out-Null
    $Process = Start-Process -FilePath $ExePath -PassThru -WindowStyle Hidden -RedirectStandardOutput $LogPath -RedirectStandardError $ErrPath
    try {
        $Deadline = (Get-Date).AddSeconds(45)
        do {
            Start-Sleep -Milliseconds 500
            if ($Process.HasExited) {
                $Output = (Get-Content $LogPath -Raw -ErrorAction SilentlyContinue) + (Get-Content $ErrPath -Raw -ErrorAction SilentlyContinue)
                throw "Executable exited during smoke test.`n$Output"
            }
            try {
                $Response = Invoke-WebRequest -Uri "http://127.0.0.1:5055/" -UseBasicParsing -TimeoutSec 2
                if ($Response.StatusCode -eq 200) {
                    Write-Host "Smoke test passed: http://127.0.0.1:5055/"
                    break
                }
            } catch {
                # Server is still starting.
            }
        } while ((Get-Date) -lt $Deadline)

        if ((Get-Date) -ge $Deadline) {
            $Output = (Get-Content $LogPath -Raw -ErrorAction SilentlyContinue) + (Get-Content $ErrPath -Raw -ErrorAction SilentlyContinue)
            throw "Executable did not answer within 45 seconds.`n$Output"
        }
    } finally {
        if (!$Process.HasExited) {
            Stop-Process -Id $Process.Id -Force
        }
    }
}

$ZipPath = Join-Path $RepoRoot "dist\SOPPlanningEngine-windows.zip"
if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}
Compress-Archive -Path (Join-Path $RepoRoot "dist\SOPPlanningEngine") -DestinationPath $ZipPath -Force

Write-Host "Executable ready: $ExePath"
Write-Host "Zip package ready: $ZipPath"
