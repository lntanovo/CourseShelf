param(
    [string]$Python = (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    [string]$UpxDirectory = (Join-Path $PSScriptRoot '.tools\upx-5.2.1-win64')
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
$upx = Join-Path $UpxDirectory 'upx.exe'
if (-not (Test-Path -LiteralPath $upx -PathType Leaf)) { throw 'Run tools\setup_upx.ps1 once before building (official UPX 5.2.1, SHA-256 pinned).' }

Push-Location $project
try {
    & $Python tools\release_assets.py
    if ($LASTEXITCODE -ne 0) { throw 'Could not create release assets' }
    $assets = Join-Path $project 'assets'
    $icon = Join-Path $assets 'courseshelf.ico'
    $versionFile = Join-Path $project 'version_info.txt'
    & $Python -m PyInstaller `
        --noconfirm --clean --onedir --windowed --noupx `
        --name CourseShelf --icon $icon --version-file $versionFile `
        --distpath $distribution --workpath $work --specpath $work `
        --collect-data rapidocr --collect-binaries onnxruntime `
        --add-data "$assets;assets" `
        --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick `
        --exclude-module PySide6.QtVirtualKeyboard --exclude-module PySide6.QtPdf `
        --exclude-module PySide6.QtNetwork --exclude-module PySide6.QtOpenGL `
        --exclude-module PySide6.QtPrintSupport --exclude-module PySide6.QtSvg `
        --exclude-module PIL.AvifImagePlugin --exclude-module PIL.WebPImagePlugin `
        --exclude-module PIL._avif --exclude-module PIL._webp `
        app.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    $exe = Join-Path $distribution 'CourseShelf\CourseShelf.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        throw "Build finished without exe: $exe"
    }
    # PyInstaller can pick up Poppler's icuuc.dll from the developer PATH.
    # That DLL exports versioned ICU names and breaks Qt6Core on Windows.
    $release = Join-Path $distribution 'CourseShelf'
    $internal = Join-Path $release '_internal'
    foreach ($file in @(Get-ChildItem -LiteralPath $internal -Filter 'icu*.dll' -File)) {
        Remove-Item -LiteralPath $file.FullName -Force
    }
    # Only still-image OCR is shipped; video decoders and OpenGL software rendering are unused.
    foreach ($pattern in @('cv2\opencv_videoio_ffmpeg*.dll', 'PySide6\opengl32sw.dll', 'onnxruntime\capi\onnxruntime.dll')) {
        Get-ChildItem -Path (Join-Path $internal $pattern) -File -ErrorAction SilentlyContinue | ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Force
        }
    }
    $translations = Join-Path $internal 'PySide6\translations'
    if (Test-Path -LiteralPath $translations) {
        Get-ChildItem -LiteralPath $translations -File | Where-Object {
            $_.Name -notmatch '^qt(base)?_(zh_CN|en)\.qm$'
        } | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
    }
    # QtGui hooks collect optional native plugins even when Python modules are excluded.
    $qt = Join-Path $internal 'PySide6'
    Get-ChildItem -LiteralPath $qt -Filter 'Qt6*.dll' -File | Where-Object {
        $_.Name -notin @('Qt6Core.dll','Qt6Gui.dll','Qt6Widgets.dll')
    } | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
    $plugins = Join-Path $qt 'plugins'
    $keepPlugins = @('qwindows.dll','qoffscreen.dll','qminimal.dll','qjpeg.dll','qico.dll','qgif.dll','qmodernwindowsstyle.dll','qwindowsvistastyle.dll')
    Get-ChildItem -LiteralPath $plugins -Recurse -File | Where-Object { $_.Name -notin $keepPlugins } | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force
    }
    # Compress only the tested numeric/OCR libraries; leave Qt and Python runtime untouched.
    $compress = @((Join-Path $internal 'cv2\cv2.pyd'))
    $compress += @(Get-ChildItem -LiteralPath (Join-Path $internal 'numpy.libs') -Filter '*openblas*.dll' -File | ForEach-Object FullName)
    foreach ($binary in $compress) {
        & $upx --lzma --no-progress $binary
        if ($LASTEXITCODE -ne 0) { throw "UPX compression failed: $binary" }
        & $upx --test --no-progress $binary
        if ($LASTEXITCODE -ne 0) { throw "UPX integrity check failed: $binary" }
    }
    $uninstallDist = Join-Path $work 'uninstaller-dist'
    & $Python -m PyInstaller `
        --noconfirm --clean --onefile --windowed --noupx `
        --name uninstall --icon $icon `
        --distpath $uninstallDist --workpath (Join-Path $work 'uninstaller-work') --specpath $work `
        uninstaller.py
    if ($LASTEXITCODE -ne 0) {
        throw "Uninstaller build failed with exit code $LASTEXITCODE"
    }
    Copy-Item -LiteralPath (Join-Path $uninstallDist 'uninstall.exe') -Destination (Join-Path $release 'uninstall.exe') -Force
    foreach ($document in @('LICENSE','README.md','THIRD_PARTY_NOTICES.md')) {
        Copy-Item -LiteralPath (Join-Path $project $document) -Destination $release -Force
    }
    & $Python tools\release_assets.py $release
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy dependency licenses' }
    $files = Get-ChildItem -LiteralPath $release -Recurse -File | Where-Object {
        $_.Name -ne 'uninstall.exe' -and $_.Name -ne 'release-manifest.json'
    } | ForEach-Object {
        @{ path = [IO.Path]::GetRelativePath($release, $_.FullName); sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
    $version = '1.3.0'
    @{ schema_version = 1; version = $version; built_at = [DateTime]::UtcNow.ToString('o'); files = @($files) } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $release 'release-manifest.json') -Encoding utf8
    $archive = Join-Path $distribution "CourseShelf-$version-Windows.zip"
    Compress-Archive -LiteralPath $release -DestinationPath $archive -Force
    $bytes = (Get-ChildItem -LiteralPath $release -Recurse -File | Measure-Object -Property Length -Sum).Sum
    Write-Host "Release bytes: $bytes; archive: $archive"
    if ($bytes -gt 180MB) { throw "Release exceeds 180 MiB budget: $bytes bytes" }
    Write-Host "Release ready: $exe"
}
finally {
    Pop-Location
}
