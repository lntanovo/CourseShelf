param([Parameter(Mandatory=$true)][string]$Milestone)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$project = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
Set-Location -LiteralPath $project
$python = Join-Path $project '.venv\Scripts\python.exe'
$logs = Join-Path $project 'artifacts\improvement'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$sources = @(Get-ChildItem -LiteralPath $project -Filter '*.py' -File | ForEach-Object FullName)
foreach ($package in @('services','ui','tasks')) {
    $folder = Join-Path $project $package
    if (Test-Path -LiteralPath $folder) {
        $sources += @(Get-ChildItem -LiteralPath $folder -Filter '*.py' -File -Recurse | ForEach-Object FullName)
    }
}
& $python -m py_compile @sources *> (Join-Path $logs "$Milestone-syntax.log")
if ($LASTEXITCODE -ne 0) { throw 'Syntax failed' }
& $python -m unittest discover -s tests -p 'test_*.py' -v *> (Join-Path $logs "$Milestone-unit.log")
if ($LASTEXITCODE -ne 0) { Get-Content (Join-Path $logs "$Milestone-unit.log"); throw 'Tests failed' }
& $python tests\smoke_demo.py *> (Join-Path $logs "$Milestone-smoke.log")
if ($LASTEXITCODE -ne 0) { Get-Content (Join-Path $logs "$Milestone-smoke.log"); throw 'Smoke failed' }
& .\build.ps1 *> (Join-Path $logs "$Milestone-build.log")
& .\tests\packed_acceptance.ps1 -UseFictionalSample *> (Join-Path $logs "$Milestone-packed.log")
Get-Content (Join-Path $logs "$Milestone-unit.log") -Tail 5
Get-Content (Join-Path $logs "$Milestone-packed.log")
Write-Output "$Milestone verified"
