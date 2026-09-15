<#
Run only in a disposable Windows QA account. Install refuses an existing app;
Uninstall removes only the installation created by that Install phase.
Explicit test logs and the external sentinel stay in EvidenceDirectory.
This checks targeted residue, not all OS file/registry activity or native UI.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Install', 'Uninstall')][string]$Phase,
    [Parameter(Mandatory = $true)][string]$EvidenceDirectory,
    [string]$InstallerPath,
    [switch]$DisposableVm
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $DisposableVm -or [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'A disposable Windows QA account and -DisposableVm are required.'
}
$AppRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\PKUCourseHelper'
$Shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'PKUCourseHelper.lnk'
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{6AF68EC2-4877-4A72-B3EB-41776586D9DF}_is1'
$EvidenceDirectory = [IO.Path]::GetFullPath($EvidenceDirectory)
if ($EvidenceDirectory.StartsWith($AppRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or $EvidenceDirectory -ieq $AppRoot) {
    throw 'Evidence must be outside the installation.'
}
$ReceiptFile = Join-Path $EvidenceDirectory 'installation-receipt.json'
$Utf8 = [Text.UTF8Encoding]::new($false)

function TempEntries {
    @(Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Force |
        Where-Object { $_.Name -like 'is-*.tmp' -or $_.Name -like '_iu*.tmp' } |
        Select-Object -ExpandProperty FullName | Sort-Object)
}

function SharedRuntimeState {
    $State = @()
    foreach ($Key in @('HKCU:\Software\Microsoft\EdgeUpdate\Clients',
                       'HKLM:\Software\Microsoft\EdgeUpdate\Clients',
                       'HKLM:\Software\WOW6432Node\Microsoft\EdgeUpdate\Clients')) {
        if (Test-Path -LiteralPath $Key) {
            $State += @(Get-ChildItem -LiteralPath $Key | Sort-Object Name | ForEach-Object {
                [ordered]@{ key = $_.Name; name = $_.GetValue('name'); version = $_.GetValue('pv') }
            })
        }
    }
    ConvertTo-Json -InputObject $State -Compress -Depth 5
}

function RunInstaller([string]$Executable, [string]$LogName) {
    $Child = Start-Process -FilePath $Executable -WorkingDirectory $EvidenceDirectory -WindowStyle Hidden -PassThru -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/LOG="' + (Join-Path $EvidenceDirectory $LogName) + '"'))
    try {
        if (-not $Child.WaitForExit(1800000)) { throw 'Installer exceeded the 30-minute QA deadline; inspect its window.' }
        $Child.WaitForExit()
        if ($Child.ExitCode -ne 0) { throw ('Installer returned failure: ' + $Child.ExitCode) }
    } finally { $Child.Dispose() }
}

if ($Phase -eq 'Install') {
    if (-not $InstallerPath) { throw '-InstallerPath is required for Install.' }
    if ((Test-Path -LiteralPath $AppRoot) -or (Test-Path -LiteralPath $Shortcut) -or
        (Test-Path -LiteralPath $UninstallKey) -or (Test-Path -LiteralPath $ReceiptFile)) {
        throw 'QA requires a fresh account/installation and a new evidence directory. Existing state was not changed.'
    }
    New-Item -ItemType Directory -Path $EvidenceDirectory -Force | Out-Null
    $Receipt = [ordered]@{
        app_root = $AppRoot; token = [Guid]::NewGuid().ToString('N');
        installer_sha256 = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash;
        temporary_before = @(TempEntries); shared_runtime_before = (SharedRuntimeState)
    }
    [IO.File]::WriteAllText($ReceiptFile, ($Receipt | ConvertTo-Json -Depth 6), $Utf8)
    RunInstaller ([IO.Path]::GetFullPath($InstallerPath)) 'install.log'
    foreach ($Path in @((Join-Path $AppRoot 'PKUCourseHelper.exe'), (Join-Path $AppRoot 'install-layout.ini'),
                        (Join-Path $AppRoot 'runtime\webview2\msedgewebview2.exe'), $Shortcut, $UninstallKey)) {
        if (-not (Test-Path -LiteralPath $Path)) { throw ('Installation evidence missing: ' + $Path) }
    }
    $Data = Join-Path $AppRoot 'data'
    New-Item -ItemType Directory -Path $Data -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $Data 'qa-installation-token.txt'), $Receipt.token, $Utf8)
    [IO.File]::WriteAllText((Join-Path $EvidenceDirectory 'external-export-sentinel.txt'), $Receipt.token, $Utf8)
    Write-Output 'Installed. Native UI/DPAPI/quit journeys may now be tested before the Uninstall phase.'
    exit 0
}

$Receipt = Get-Content -LiteralPath $ReceiptFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Receipt.app_root -ine $AppRoot -or
    [IO.File]::ReadAllText((Join-Path $AppRoot 'data\qa-installation-token.txt')) -cne $Receipt.token) {
    throw 'This is not the disposable installation recorded by the Install phase.'
}
$OwnedProcesses = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($AppRoot + '\', [StringComparison]::OrdinalIgnoreCase)
})
if ($OwnedProcesses.Count) { throw 'Application processes are still running; test closing first.' }
RunInstaller (Join-Path $AppRoot 'unins000.exe') 'uninstall.log'
$Deadline = [DateTime]::UtcNow.AddMinutes(3)
do {
    $UnexpectedTemp = @(TempEntries | Where-Object { $_ -notin $Receipt.temporary_before })
    $Remaining = @($AppRoot, $Shortcut, $UninstallKey | Where-Object { Test-Path -LiteralPath $_ })
    if (-not $UnexpectedTemp.Count -and -not $Remaining.Count) { break }
    Start-Sleep -Milliseconds 250
} while ([DateTime]::UtcNow -lt $Deadline)
$OwnedProcesses = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($AppRoot + '\', [StringComparison]::OrdinalIgnoreCase)
} | Select-Object ProcessId, Name, ExecutablePath)
$ExternalIntact = [IO.File]::ReadAllText((Join-Path $EvidenceDirectory 'external-export-sentinel.txt')) -ceq $Receipt.token
$SharedUnchanged = (SharedRuntimeState) -ceq $Receipt.shared_runtime_before
$Passed = -not $UnexpectedTemp.Count -and -not $Remaining.Count -and -not $OwnedProcesses.Count -and $ExternalIntact -and $SharedUnchanged
$Report = [ordered]@{
    passed = $Passed; checked_at_utc = [DateTime]::UtcNow.ToString('o');
    installer_sha256 = $Receipt.installer_sha256; remaining_owned_paths = $Remaining;
    new_installer_temporary_entries = $UnexpectedTemp; remaining_owned_processes = $OwnedProcesses;
    external_export_intact = $ExternalIntact; shared_runtime_registry_unchanged = $SharedUnchanged;
    scope = 'Targeted ownership/residue check; not a full file/registry trace or native UI certification.'
}
[IO.File]::WriteAllText((Join-Path $EvidenceDirectory 'uninstall-residue.json'), ($Report | ConvertTo-Json -Depth 8), $Utf8)
if (-not $Passed) { throw 'Uninstall residue acceptance failed; see uninstall-residue.json.' }
Write-Output 'Targeted install/uninstall residue acceptance passed.'
