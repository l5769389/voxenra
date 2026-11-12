# CI-only OpenGL runtime. It is loaded by tests/conftest.py, never packaged.
$ErrorActionPreference = 'Stop'
$destination = Join-Path $env:RUNNER_TEMP 'voxplane-mesa-26.2.6'
$archive = "$destination.7z"
Invoke-WebRequest 'https://github.com/pal1000/mesa-dist-win/releases/download/26.2.6/mesa3d-26.2.6-release-msvc.7z' -OutFile $archive
$expected = 'b2e00615feaba45942343c265cc8c5f576142ca682c1ac6661922d4b72492877'
if ((Get-FileHash $archive -Algorithm SHA256).Hash.ToLower() -ne $expected) {
    throw 'Mesa test runtime checksum mismatch'
}
& 7z x $archive "-o$destination" -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not extract Mesa test runtime' }
$runtime = Join-Path $destination 'x64'
foreach ($dll in @('opengl32.dll', 'libgallium_wgl.dll')) {
    if (-not (Test-Path (Join-Path $runtime $dll))) { throw "Missing Mesa runtime: $dll" }
}
"VOXPLANE_TEST_OPENGL_DIR=$runtime" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
"GALLIUM_DRIVER=llvmpipe" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
Write-Host "Verified CI-only Mesa 26.2.6: $expected"
