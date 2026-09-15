# Download-only preparation on an ephemeral GitHub-hosted Windows runner.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or
    [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This script is restricted to disposable GitHub-hosted Windows runners.'
}
$Inputs = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'release-inputs.json') -Raw | ConvertFrom-Json
$Root = Join-Path $env:RUNNER_TEMP ('pku-release-tools-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Root | Out-Null

function DownloadVerified($Entry, [string]$Name) {
    if ($Entry.sha256 -notmatch '^[a-f0-9]{64}$' -or ([uri]$Entry.url).Scheme -ne 'https') {
        throw 'Invalid pinned download manifest.'
    }
    $Destination = Join-Path $Root $Name
    & curl.exe --fail --location --silent --show-error --proto '=https' --proto-redir '=https' `
        --retry 4 --retry-all-errors --connect-timeout 30 --max-time 1800 --output $Destination $Entry.url
    if ($LASTEXITCODE -ne 0) { throw ('Download failed: ' + $Name) }
    if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -ine $Entry.sha256) {
        throw ('SHA-256 mismatch; do not execute or package this download: ' + $Name)
    }
    return $Destination
}

$Cab = DownloadVerified $Inputs.webview2 'webview2-x64.cab'
@("webview_cab=$Cab", "runtime_sha256=$($Inputs.webview2.sha256)",
  "runtime_version=$($Inputs.webview2.version)") | Add-Content -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8
