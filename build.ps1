param(
    [string]$Python = (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')
)

$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath($PSScriptRoot)
$distribution = [IO.Path]::GetFullPath((Join-Path $project 'dist'))
$work = [IO.Path]::GetFullPath((Join-Path $project 'build'))
$prefix = $project.TrimEnd('\') + '\'
foreach ($target in @($distribution, $work)) {
    if (-not $target.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Build output must stay inside project: $target"
    }
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python interpreter not found: $Python"
}

Push-Location $project
try {
    & $Python -m PyInstaller `
        --noconfirm --clean --onedir --windowed `
        --name FilesOrganizer `
        --distpath $distribution --workpath $work --specpath $work `
        --collect-data rapidocr --collect-binaries onnxruntime `
        app.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    $exe = Join-Path $distribution 'FilesOrganizer\FilesOrganizer.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        throw "Build finished without exe: $exe"
    }
    # PyInstaller can pick up Poppler's icuuc.dll from the developer PATH.
    # That DLL exports versioned ICU names and breaks Qt6Core on Windows.
    $conflictingIcu = Join-Path $distribution 'FilesOrganizer\_internal\icuuc.dll'
    if (Test-Path -LiteralPath $conflictingIcu -PathType Leaf) {
        Remove-Item -LiteralPath $conflictingIcu -Force
    }
    $uninstallDist = Join-Path $work 'uninstaller-dist'
    & $Python -m PyInstaller `
        --noconfirm --clean --onefile --windowed `
        --name uninstall `
        --distpath $uninstallDist --workpath (Join-Path $work 'uninstaller-work') --specpath $work `
        uninstaller.py
    if ($LASTEXITCODE -ne 0) {
        throw "Uninstaller build failed with exit code $LASTEXITCODE"
    }
    $release = Join-Path $distribution 'FilesOrganizer'
    Copy-Item -LiteralPath (Join-Path $uninstallDist 'uninstall.exe') -Destination (Join-Path $release 'uninstall.exe') -Force
    $files = Get-ChildItem -LiteralPath $release -Recurse -File | Where-Object {
        $_.Name -ne 'uninstall.exe' -and $_.Name -ne 'release-manifest.json'
    } | ForEach-Object {
        @{ path = [IO.Path]::GetRelativePath($release, $_.FullName); sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
    @{ schema_version = 1; files = @($files) } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $release 'release-manifest.json') -Encoding utf8
    Write-Host "Release ready: $exe"
}
finally {
    Pop-Location
}
