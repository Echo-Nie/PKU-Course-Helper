[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$WebView2RuntimeCab,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$RuntimeSha256,
    [string]$BaseArchive,
    [string]$RuntimeVersion = '',
    [string]$OutputDirectory = 'dist/portable-private'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'Build on Windows x64.'
}
$Repo = Split-Path -Parent $PSScriptRoot
$BuildId = [Guid]::NewGuid().ToString('N')
$Stage = Join-Path $Repo ('build/private-portable-' + $BuildId)
$OutputRoot = if ([IO.Path]::IsPathRooted($OutputDirectory)) { $OutputDirectory } else { Join-Path $Repo $OutputDirectory }
$Output = Join-Path $OutputRoot $BuildId
$Cab = (Resolve-Path -LiteralPath $WebView2RuntimeCab).Path
if ((Get-FileHash -LiteralPath $Cab -Algorithm SHA256).Hash -ine $RuntimeSha256) {
    throw 'WebView2 CAB checksum mismatch.'
}
function Assert-NativeExit([string]$Description) {
    if ($LASTEXITCODE -ne 0) { throw ($Description + ' failed: ' + $LASTEXITCODE) }
}
New-Item -ItemType Directory -Path $Stage, $Output -Force | Out-Null
if (-not $BaseArchive) {
    $BaseOutput = Join-Path $Stage 'base-output'
    & (Join-Path $PSScriptRoot 'build_windows.ps1') -OutputDirectory $BaseOutput
    $BaseArchives = @(Get-ChildItem -LiteralPath $BaseOutput -Recurse -Filter 'PKUCourseHelper-windows-x64-portable.zip')
    if ($BaseArchives.Count -ne 1) { throw 'Expected exactly one base archive.' }
    $BaseArchive = $BaseArchives[0].FullName
}
$BaseArchive = (Resolve-Path -LiteralPath $BaseArchive).Path
# Keep test evidence alongside the build, never inside the customer ZIP.
$BaseTests = Join-Path (Split-Path $BaseArchive) 'pytest-windows.xml'
if (-not (Test-Path -LiteralPath $BaseTests -PathType Leaf)) { throw 'Base archive lacks Python test evidence.' }
Copy-Item -LiteralPath $BaseTests -Destination $Output
$Python = Join-Path $Repo '.venv-desktop/Scripts/python.exe'
$AuditTool = Join-Path $Repo 'tools/audit_bundle.py'
Expand-Archive -LiteralPath $BaseArchive -DestinationPath (Join-Path $Stage 'payload')
$Payload = Join-Path $Stage 'payload/PKUCourseHelper'
& $Python $AuditTool $Payload --archive $BaseArchive --report (Join-Path $Output 'base-audit.json')
Assert-NativeExit 'Base archive integrity audit'

$Extraction = Join-Path $Stage 'browser-extraction'
New-Item -ItemType Directory -Path $Extraction | Out-Null
& expand.exe $Cab '-F:*' $Extraction | Out-Null
Assert-NativeExit 'WebView2 extraction'
$Browsers = @(Get-ChildItem -LiteralPath $Extraction -Recurse -Filter 'msedgewebview2.exe')
if ($Browsers.Count -ne 1) { throw 'Expected exactly one WebView2 runtime.' }
if ($RuntimeVersion -and $Browsers[0].VersionInfo.ProductVersion -ne $RuntimeVersion) {
    throw 'The extracted WebView2 version does not match the release manifest.'
}
$Signature = Get-AuthenticodeSignature -LiteralPath $Browsers[0].FullName
if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'WebView2 does not have a valid Microsoft signature.'
}
$Redirected = @(Get-ChildItem -LiteralPath $Extraction -Recurse -Force |
    Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 })
if ($Redirected.Count) { throw 'Runtime contains redirected filesystem entries.' }
$Runtime = Join-Path $Payload 'runtime/webview2'
New-Item -ItemType Directory -Path (Split-Path $Runtime) | Out-Null
Copy-Item -LiteralPath $Browsers[0].Directory.FullName -Destination $Runtime -Recurse
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'portable-layout.ini') -Destination (Join-Path $Payload 'install-layout.ini')
# Replace the base package's system-runtime directions with end-user directions.
$QuickStart = Join-Path $Repo 'docs/QUICK_START.txt'
Copy-Item -LiteralPath $QuickStart -Destination (Join-Path $Payload '使用前请您务必阅读我.txt')
# Remove only the generated base-package directions from this owned staging
# payload. Ship a single short guide, not duplicated developer documentation.
$BaseGuide = [IO.Path]::GetFullPath((Join-Path $Payload '使用说明.md'))
if (-not $BaseGuide.StartsWith([IO.Path]::GetFullPath($Stage) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Generated guide is outside the owned staging directory.'
}
if (Test-Path -LiteralPath $BaseGuide -PathType Leaf) { Remove-Item -LiteralPath $BaseGuide }
$RuntimeFiles = @(Get-ChildItem -LiteralPath $Runtime -Recurse -File | Sort-Object FullName | ForEach-Object {
    [ordered]@{ path = $_.FullName.Substring($Runtime.Length + 1).Replace('\', '/'); bytes = $_.Length;
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
})
$Receipt = [ordered]@{
    version = $Browsers[0].VersionInfo.ProductVersion
    source_page = 'https://developer.microsoft.com/en-us/microsoft-edge/webview2/'
    cab_sha256 = $RuntimeSha256.ToLowerInvariant()
    signature_status = [string]$Signature.Status
    signer_subject = $Signature.SignerCertificate.Subject
    files = $RuntimeFiles
}
[IO.File]::WriteAllText((Join-Path $Payload 'runtime-manifest.json'), ($Receipt | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
& $Python $AuditTool $Payload --distribution portable-private --report (Join-Path $Output 'payload-audit.json')
Assert-NativeExit 'Private portable payload audit'

$SelfTestReport = Join-Path $Output 'frozen-self-test.json'
$Process = Start-Process -FilePath (Join-Path $Payload 'PKUCourseHelper.exe') -WindowStyle Hidden -PassThru -WorkingDirectory $Stage -ArgumentList @('--self-test', ('"' + $SelfTestReport + '"'))
try {
    if (-not $Process.WaitForExit(60000)) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        throw 'Frozen self-test exceeded 60 seconds.'
    }
    $Process.WaitForExit()
    if ($Process.ExitCode -ne 0) { throw ('Frozen self-test failed: ' + $Process.ExitCode) }
} finally { $Process.Dispose() }
$Evidence = Get-Content -LiteralPath $SelfTestReport -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Evidence.passed -or -not $Evidence.frozen -or $Evidence.platform -ne 'Windows') {
    throw 'Frozen self-test evidence is incomplete.'
}
$Archive = Join-Path $Output 'PKUCourseHelper-Windows11-x64-portable.zip'
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($Payload, $Archive, [IO.Compression.CompressionLevel]::Optimal, $true)
& $Python $AuditTool $Payload --distribution portable-private --archive $Archive --report (Join-Path $Output 'bundle-audit.json')
Assert-NativeExit 'Final archive and per-file hash audit'
$Hash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText((Join-Path $Output 'SHA256SUMS.txt'), ($Hash + '  ' + [IO.Path]::GetFileName($Archive) + "`n"), [Text.UTF8Encoding]::new($false))
Write-Host ('Private portable package: ' + $Archive)
Write-Host 'Native UI, process lifetime and app-owned residue checks remain required.'
