# CI-only OpenGL runtime. It is loaded by tests/conftest.py, never packaged.
$ErrorActionPreference = 'Stop'
$destination = Join-Path $env:RUNNER_TEMP 'voxplane-mesa-26.2.6'
$archive = "$destination.7z"
Invoke-WebRequest 'https://github.com/pal1000/mesa-dist-win/releases/download/26.2.6/mesa3d-26.2.6-release-msvc.7z' -OutFile $archive
$expected = 'b2e00615feaba45942343c265cc8c5f576142ca682c1ac6661922d4b72492877'
if ((Get-FileHash $archive -Algorithm SHA256).Hash.ToLower() -ne $expected) {
    throw 'Mesa test runtime checksum mismatch'
}
& 7z x $archive "-o$destination" -y
if ($LASTEXITCODE -ne 0) { throw 'Could not extract Mesa test runtime' }
$candidates = @(Get-ChildItem $destination -Filter opengl32.dll -Recurse | Where-Object {
    $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
    $pe = [BitConverter]::ToInt32($bytes, 0x3c)
    [BitConverter]::ToUInt16($bytes, $pe + 4) -eq 0x8664
})
if ($candidates.Count -ne 1) {
    Get-ChildItem $destination -Recurse | Select-Object -First 80 FullName
    Write-Host "x64 OpenGL candidates: $($candidates.FullName -join ', ')"
    throw 'Expected exactly one x64 Mesa OpenGL runtime'
}
$runtime = $candidates[0].DirectoryName
foreach ($dll in @('opengl32.dll', 'libgallium_wgl.dll')) {
    if (-not (Test-Path (Join-Path $runtime $dll))) { throw "Missing Mesa runtime: $dll" }
}
"VOXPLANE_TEST_OPENGL_DIR=$runtime" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
"GALLIUM_DRIVER=llvmpipe" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
Write-Host "Verified CI-only Mesa 26.2.6: $expected"
