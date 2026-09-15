[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$WebView2RuntimeCab,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$RuntimeSha256,
    [string]$InnoCompiler = 'ISCC.exe',
    [ValidatePattern('^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$')]
    [string]$AppVersion = '0.1.0',
    [string]$RuntimeVersion = '',
    [string]$OutputDirectory = 'dist/installer'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Windows x64 is required.' }
$Repo = Split-Path -Parent $PSScriptRoot
$NumericVersion = ($AppVersion -split '-', 2)[0]
foreach ($Part in $NumericVersion.Split('.')) {
    if ([long]$Part -gt 65535) { throw 'Windows version components must be at most 65535.' }
}
$BuildId = [Guid]::NewGuid().ToString('N')
$Stage = Join-Path $Repo ('build/installer-' + $BuildId)
$OutputRoot = if ([IO.Path]::IsPathRooted($OutputDirectory)) { $OutputDirectory } else { Join-Path $Repo $OutputDirectory }
$Output = Join-Path $OutputRoot $BuildId
$Compiler = (Get-Command $InnoCompiler -ErrorAction Stop).Source
if ((Get-Item -LiteralPath $Compiler).VersionInfo.ProductVersion -notmatch '^6\.7\.3(\.|$)') {
    throw 'Inno Setup 6.7.3 is required; temporary-uninstaller cleanup is pinned to that engine.'
}
$Cab = (Resolve-Path -LiteralPath $WebView2RuntimeCab).Path
if ((Get-FileHash -LiteralPath $Cab -Algorithm SHA256).Hash -ine $RuntimeSha256) {
    throw 'Fixed WebView2 CAB checksum does not match the trusted download receipt.'
}

function Assert-NativeExit([string]$Description) {
    if ($LASTEXITCODE -ne 0) { throw ($Description + ' failed: ' + $LASTEXITCODE) }
}

New-Item -ItemType Directory -Force -Path $Stage, $Output | Out-Null
# Reuse the audited base and all native Python/frozen gates. The base remains
# separate from the private browser; the portable size policy is not weakened.
$BaseOutput = Join-Path $Stage 'base-output'
& (Join-Path $PSScriptRoot 'build_windows.ps1') -OutputDirectory $BaseOutput
$BaseArchives = @(Get-ChildItem -LiteralPath $BaseOutput -Recurse -Filter 'PKUCourseHelper-windows-x64-portable.zip')
if ($BaseArchives.Count -ne 1) { throw 'Expected exactly one audited base artifact.' }
$PayloadParent = Join-Path $Stage 'payload'
Expand-Archive -LiteralPath $BaseArchives[0].FullName -DestinationPath $PayloadParent
$Payload = Join-Path $PayloadParent 'PKUCourseHelper'
$BrowserExtraction = Join-Path $Stage 'browser-extraction'
New-Item -ItemType Directory -Path $BrowserExtraction | Out-Null
& expand.exe $Cab '-F:*' $BrowserExtraction
Assert-NativeExit 'Fixed WebView2 extraction'
$BrowserExecutables = @(Get-ChildItem -LiteralPath $BrowserExtraction -Recurse -Filter msedgewebview2.exe)
if ($BrowserExecutables.Count -ne 1) { throw 'Expected exactly one fixed WebView2 runtime.' }
$BrowserSource = $BrowserExecutables[0].Directory.FullName
if ($RuntimeVersion -and $BrowserExecutables[0].VersionInfo.ProductVersion -ne $RuntimeVersion) {
    throw 'The extracted WebView2 version does not match the release manifest.'
}
$Signature = Get-AuthenticodeSignature -LiteralPath $BrowserExecutables[0].FullName
if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'Private WebView2 executable does not have a valid Microsoft signature.'
}
$Redirected = @(Get-ChildItem -LiteralPath $BrowserExtraction -Recurse -Force |
    Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 })
if ($Redirected.Count) { throw 'Runtime extraction contains redirected filesystem entries.' }
$Runtime = Join-Path $Payload 'runtime\webview2'
New-Item -ItemType Directory -Force -Path (Split-Path $Runtime) | Out-Null
Copy-Item -LiteralPath $BrowserSource -Destination $Runtime -Recurse
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install-layout.ini') -Destination $Payload
Copy-Item -LiteralPath (Join-Path $Repo 'docs/INSTALLATION.md') -Destination (Join-Path $Payload 'INSTALLATION.md')
Copy-Item -LiteralPath (Join-Path $Repo 'docs/INSTALLATION.md') -Destination (Join-Path $Payload '使用说明.md')
$Maintenance = Join-Path $Payload '_internal\maintenance'
New-Item -ItemType Directory -Path $Maintenance | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'uninstall_cleanup.ps1') -Destination $Maintenance
$RuntimeFiles = @(Get-ChildItem -LiteralPath $Runtime -Recurse -File | Sort-Object FullName | ForEach-Object {
    [ordered]@{
        path = $_.FullName.Substring($Runtime.Length + 1).Replace('\', '/')
        bytes = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
})
$Provenance = [ordered]@{
    version = $BrowserExecutables[0].VersionInfo.ProductVersion
    cab_sha256 = $RuntimeSha256.ToLowerInvariant()
    signature_status = [string]$Signature.Status
    signer_subject = $Signature.SignerCertificate.Subject
    files = $RuntimeFiles
}
$Utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText((Join-Path $Payload 'runtime-manifest.json'), ($Provenance | ConvertTo-Json -Depth 8), $Utf8)
$Python = Join-Path $Repo '.venv-desktop\Scripts\python.exe'
& $Python (Join-Path $Repo 'tools\audit_bundle.py') $Payload --distribution installed --report (Join-Path $Output 'installed-payload-audit.json')
Assert-NativeExit 'Installed payload ownership, content and runtime hash audit'
& $Compiler ('/DPayloadDir=' + $Payload) ('/DArtifactDir=' + $Output) `
    ('/DReleaseVersion=' + $AppVersion) ('/DNumericVersion=' + $NumericVersion) (Join-Path $PSScriptRoot 'installer.iss')
Assert-NativeExit 'Installer compilation'
$Installer = Join-Path $Output 'PKUCourseHelper-windows-x64-setup.exe'
if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) { throw 'Installer output is missing.' }
if ((Get-Item -LiteralPath $Installer).Length -gt 600000000) { throw 'Installer exceeds 600 MB size gate.' }
$Hash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText((Join-Path $Output 'SHA256SUMS.txt'), ($Hash + '  ' + [IO.Path]::GetFileName($Installer) + "`n"), $Utf8)
Copy-Item -LiteralPath (Join-Path $BaseArchives[0].Directory.FullName 'pytest-windows.xml') -Destination $Output
Copy-Item -LiteralPath (Join-Path $BaseArchives[0].Directory.FullName 'frozen-self-test.json') -Destination $Output
Write-Host ('Installer candidate: ' + $Installer)
Write-Host 'Not release-certified until native install/use/uninstall and residue acceptance pass.'
