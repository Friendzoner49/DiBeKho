# Build DiBeKho for Windows. Run in PowerShell from the repo root:
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# Output: dist\DiBeKho\ (portable folder) and, if Inno Setup 6 is installed,
#         dist\DiBeKho-<version>-windows-setup.exe
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

uv sync
uv run pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist) { Remove-Item -Recurse -Force dist }
uv run pyinstaller packaging\dibekho.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# The packaged app must start and open every screen.
$p = Start-Process -FilePath dist\DiBeKho\DiBeKho.exe -ArgumentList "--self-test" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "Self-test failed" }

$version = (uv run python -c "import dibekho; print(dibekho.__version__)").Trim()
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc "/DAppVersion=$version" packaging\windows.iss
    Write-Host "Done: dist\DiBeKho-$version-windows-setup.exe"
} else {
    Compress-Archive -Path dist\DiBeKho -DestinationPath "dist\DiBeKho-$version-windows-portable.zip" -Force
    Write-Host "Inno Setup not found. Portable build: dist\DiBeKho-$version-windows-portable.zip"
}
