param([string]$IsccPath)
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
$previousEncoding = $env:PYTHONUTF8
$result = 1
Push-Location $projectDir
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'Install uv before building VoxPlane.'
    }
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectDir '.venv-build-windows'
    $env:PYTHONUTF8 = '1'
    $builderArgs = @()
    if ($IsccPath) { $builderArgs += @('--iscc', $IsccPath) }
    & uv run --locked --python 3.13 --no-dev --group build --no-editable python scripts/build_windows_installer.py @builderArgs
    $result = $LASTEXITCODE
} finally {
    $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment
    $env:PYTHONUTF8 = $previousEncoding
    Pop-Location
}
exit $result
