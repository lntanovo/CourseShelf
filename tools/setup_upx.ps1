param([string]$Proxy = '')
$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$tools = [IO.Path]::GetFullPath((Join-Path $project '.tools'))
if (-not $tools.StartsWith($project.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Tool path escaped workspace' }
New-Item -ItemType Directory -Path $tools -Force | Out-Null
$archive = Join-Path $tools 'upx-5.2.1-win64.zip'
$request = @{ Uri = 'https://github.com/upx/upx/releases/download/v5.2.1/upx-5.2.1-win64.zip'; OutFile = $archive }
if ($Proxy) { $request.Proxy = $Proxy }
Invoke-WebRequest @request
$expected = 'eabc6792a347d45e945be7748423e7868fd01b0d2bcaa2f4b1031fd71ff69bda'
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'UPX archive checksum mismatch' }
Expand-Archive -LiteralPath $archive -DestinationPath $tools -Force
Write-Host 'UPX 5.2.1 ready (build-time only; application remains offline).'
