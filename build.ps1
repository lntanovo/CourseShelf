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
    Write-Host "Release ready: $exe"
}
finally {
    Pop-Location
}
