param(
    [string]$Project = (Split-Path -Parent $PSScriptRoot),
    [switch]$UseFictionalSample,
    [string]$ReleaseDirectory = (Join-Path $Project 'dist\CourseShelf')
)

$ErrorActionPreference = 'Stop'
$sourceRelease = [IO.Path]::GetFullPath($ReleaseDirectory)
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$sandbox = [IO.Path]::GetFullPath((Join-Path $tempRoot ('courseshelf-packed-' + [guid]::NewGuid().ToString('N'))))
if (-not $sandbox.StartsWith($tempRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Temporary sandbox path escaped system temp directory'
}
New-Item -ItemType Directory -Path $sandbox | Out-Null
$relocated = Join-Path $sandbox 'moved-publish-folder'
try {
    Copy-Item -LiteralPath $sourceRelease -Destination $relocated -Recurse
    $env:FILES_ORGANIZER_CONFIG_DIR = Join-Path $sandbox 'private-settings'
    New-Item -ItemType Directory -Path $env:FILES_ORGANIZER_CONFIG_DIR | Out-Null
    $settingsFile = Join-Path $env:FILES_ORGANIZER_CONFIG_DIR 'settings.json'
    Set-Content -LiteralPath $settingsFile -Value '{"root":"test-only"}' -Encoding utf8
    $userRoot = Join-Path $relocated 'user-materials'
    New-Item -ItemType Directory -Path $userRoot | Out-Null
    $userFile = Join-Path $userRoot 'keep.txt'
    Set-Content -LiteralPath $userFile -Value 'retain this private material' -Encoding utf8
    $emptyUser = Join-Path $relocated 'my-empty-folder'
    New-Item -ItemType Directory -Path $emptyUser | Out-Null

    $appExe = Join-Path $relocated 'CourseShelf.exe'
    $ocrJson = Join-Path $sandbox 'packed-ocr.json'
    $ocrSample = Join-Path $Project '课表.png'
    if ($UseFictionalSample -or -not (Test-Path -LiteralPath $ocrSample -PathType Leaf)) {
        $ocrSample = Join-Path $sandbox 'sample-timetable.png'
        $python = Join-Path $Project '.venv\Scripts\python.exe'
        & $python (Join-Path $Project 'tests\smoke_demo.py') --make-sample $ocrSample
        if ($LASTEXITCODE -ne 0) { throw 'Could not create a fictional OCR sample' }
    }
    $env:COURSESHELF_OFFLINE_TEST = '1'
    $ocrProcess = Start-Process -FilePath $appExe -ArgumentList @('--verify-ocr', $ocrSample, $ocrJson) -WorkingDirectory $relocated -WindowStyle Hidden -Wait -PassThru
    if ($ocrProcess.ExitCode -ne 0) { throw "Relocated app OCR failed: $($ocrProcess.ExitCode)" }
    $ocr = Get-Content -LiteralPath $ocrJson -Raw -Encoding utf8 | ConvertFrom-Json
    if ($ocr.courses.Count -ne 9) { throw "Relocated app OCR count: $($ocr.courses.Count)" }
    Write-Host "Relocated exe OCR: $($ocr.courses.Count) courses"
    $cacheJson = Join-Path $sandbox 'ocr-cache.json'
    $cacheProcess = Start-Process -FilePath $appExe -ArgumentList @('--verify-ocr-cache', $ocrSample, $cacheJson) -WorkingDirectory $relocated -WindowStyle Hidden -Wait -PassThru
    if ($cacheProcess.ExitCode -ne 0) { throw "Persistent OCR process failed: $($cacheProcess.ExitCode)" }
    $cached = Get-Content -LiteralPath $cacheJson -Raw -Encoding utf8 | ConvertFrom-Json
    if ($cached.courses.Count -ne 9) { throw 'Cached OCR result changed' }
    Write-Host "Cached exe OCR: $($cached.seconds[0]) s then $($cached.seconds[1]) s"

    $archiveSource = Join-Path $sandbox 'test-document.txt'
    Set-Content -LiteralPath $archiveSource -Value 'archive test' -Encoding utf8
    $archiveJson = Join-Path $sandbox 'packed-archive.json'
    $archiveProcess = Start-Process -FilePath $appExe -ArgumentList @('--verify-archive', $userRoot, $archiveSource, $archiveJson) -WorkingDirectory $relocated -WindowStyle Hidden -Wait -PassThru
    if ($archiveProcess.ExitCode -ne 0) { throw "Relocated archive failed: $($archiveProcess.ExitCode)" }
    $archive = Get-Content -LiteralPath $archiveJson -Raw -Encoding utf8 | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $archive.target -PathType Leaf) -or -not (Test-Path -LiteralPath $archiveSource -PathType Leaf)) {
        throw 'Relocated archive did not copy and retain source'
    }
    Write-Host 'Relocated exe archive: test file copied into user library; source retained'

    @{ root = $userRoot; last_viewed = (Split-Path -Parent $archive.target) } | ConvertTo-Json | Set-Content -LiteralPath $settingsFile -Encoding utf8
    $appearanceFile = Join-Path $env:FILES_ORGANIZER_CONFIG_DIR 'appearance.json'
    @{ theme = 'ink'; background = $ocrSample; visibility = 50 } | ConvertTo-Json | Set-Content -LiteralPath $appearanceFile -Encoding utf8
    $backgroundHash = (Get-FileHash -LiteralPath $ocrSample -Algorithm SHA256).Hash
    $process = Start-Process -FilePath $appExe -WorkingDirectory $relocated -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 3
    $process.Refresh()
    if ($process.HasExited) { throw "Relocated GUI app exited unexpectedly: $($process.ExitCode)" }
    Write-Host "Relocated GUI app opened: PID $($process.Id)"
    # The GUI may still be warming its OCR child. Stop the disposable test process
    # tree together so the uninstaller is not raced against a loaded OCR DLL.
    if (-not $process.CloseMainWindow() -or -not $process.WaitForExit(10000)) {
        & taskkill.exe /PID $process.Id /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not stop relocated test process tree' }
    }
    $process.WaitForExit()

    $uninstallExe = Join-Path $relocated 'uninstall.exe'
    $reportJson = Join-Path $sandbox 'uninstall-report.json'
    $reportProcess = Start-Process -FilePath $uninstallExe -ArgumentList @('--report', $reportJson) -WorkingDirectory $relocated -WindowStyle Hidden -Wait -PassThru
    if ($reportProcess.ExitCode -ne 0) { throw 'Relocated uninstaller report failed' }
    $report = Get-Content -LiteralPath $reportJson -Raw -Encoding utf8 | ConvertFrom-Json
    if ($report.owned.Count -lt 100) { throw "Unexpected release manifest size: $($report.owned.Count)" }
    $executeJson = Join-Path $sandbox 'uninstall-execute.json'
    $uninstallProcess = Start-Process -FilePath $uninstallExe -ArgumentList @('--execute', $executeJson, '--clear-settings', '--self-cleanup') -WorkingDirectory $relocated -WindowStyle Hidden -Wait -PassThru
    if ($uninstallProcess.ExitCode -ne 0) {
        if (Test-Path -LiteralPath $executeJson) { Get-Content -LiteralPath $executeJson -Raw -Encoding utf8 | Write-Output }
        throw 'Relocated uninstaller execution failed'
    }
    Start-Sleep -Seconds 4
    $done = Get-Content -LiteralPath $executeJson -Raw -Encoding utf8 | ConvertFrom-Json
    if ($done.failed.Count -ne 0 -or $done.modified.Count -ne 0) { throw 'Uninstaller reported failed or modified release files' }
    if (Test-Path -LiteralPath $appExe) { throw 'App exe survived uninstall' }
    if (Test-Path -LiteralPath $uninstallExe) { throw 'Uninstaller self cleanup did not complete' }
    if (Test-Path -LiteralPath $settingsFile) { throw 'Optional settings cleanup failed' }
    if (Test-Path -LiteralPath $appearanceFile) { throw 'Optional appearance cleanup failed' }
    if (-not (Test-Path -LiteralPath $ocrSample -PathType Leaf) -or (Get-FileHash -LiteralPath $ocrSample -Algorithm SHA256).Hash -ne $backgroundHash) {
        throw 'Original background image was changed or removed'
    }
    if (-not (Test-Path -LiteralPath $userFile -PathType Leaf)) { throw 'User material was deleted' }
    if (-not (Test-Path -LiteralPath $emptyUser -PathType Container)) { throw 'User-created empty directory was deleted' }
    Write-Host "Relocated uninstall: $($done.owned.Count) owned files removed; user material and empty folder preserved"
    Write-Host 'Appearance: saved ink theme and local background launch; preferences cleared, original image preserved'
}
finally {
    if (Test-Path -LiteralPath $sandbox) {
        $resolved = [IO.Path]::GetFullPath($sandbox)
        if (-not $resolved.StartsWith($tempRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Refusing to remove a path outside system temp'
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
