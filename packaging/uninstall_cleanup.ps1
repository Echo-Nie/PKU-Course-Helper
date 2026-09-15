# Runs only for the current Inno uninstaller. No services, scheduled tasks,
# recursive deletion, global temp scans, or delete-on-reboot registry entries.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][int]$UninstallerPid,
    [Parameter(Mandatory = $true)][string]$ImagePath,
    [Parameter(Mandatory = $true)][string]$ReadyPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-FileDigest([string]$Path) {
    # Python can inherit PowerShell 7's PSModulePath before launching Windows
    # PowerShell 5.1. Use .NET directly instead of loading incompatible modules.
    $Stream = [IO.File]::OpenRead($Path)
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($Hasher.ComputeHash($Stream)) }
    finally { $Hasher.Dispose(); $Stream.Dispose() }
}

function Assert-PlainPath([string]$Path) {
    $Current = [IO.Path]::GetFullPath($Path)
    while ($Current) {
        if ([IO.File]::Exists($Current) -or [IO.Directory]::Exists($Current)) {
            if (([IO.File]::GetAttributes($Current) -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Refusing a redirected cleanup path.'
            }
        }
        $Parent = [IO.Path]::GetDirectoryName($Current)
        if ($Parent -eq $Current) { break }
        $Current = $Parent
    }
}

$ImagePath = [IO.Path]::GetFullPath($ImagePath)
$CopyDirectory = [IO.Path]::GetDirectoryName($ImagePath)
$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
if ([IO.Path]::GetFileName($ImagePath) -ine '_unins.tmp' -or
    [IO.Path]::GetFileName($CopyDirectory) -notmatch '^is-[a-z0-9]+-uninstall\.tmp$' -or
    [IO.Path]::GetDirectoryName($CopyDirectory) -ine $TempRoot) {
    throw 'The cleanup target is not this uninstaller temporary copy.'
}
Assert-PlainPath $ImagePath
Assert-PlainPath $ReadyPath
$ReadyDirectory = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($ReadyPath))
if ([IO.Path]::GetDirectoryName($ReadyDirectory) -ine $TempRoot -or
    [IO.Path]::GetFileName($ReadyPath) -cne 'pku-cleanup-ready.txt') {
    throw 'Unexpected handshake path.'
}
$Uninstaller = [Diagnostics.Process]::GetProcessById($UninstallerPid)
try {
    # Pin the process handle before acknowledging, so PID reuse cannot redirect
    # the wait. The executable identity comes from Windows, not a filename glob.
    $null = $Uninstaller.Handle
    if ($Uninstaller.MainModule.FileName -ine $ImagePath) { throw 'Uninstaller process identity mismatch.' }
    $OriginalHash = Get-FileDigest $ImagePath
    [IO.File]::WriteAllText($ReadyPath, 'ready', [Text.Encoding]::ASCII)
    if (-not $Uninstaller.WaitForExit(7200000)) { throw 'Uninstaller did not exit within the cleanup deadline.' }
} finally { $Uninstaller.Dispose() }

$LastFailure = $null
for ($Attempt = 0; $Attempt -lt 50; $Attempt++) {
    try {
        Assert-PlainPath $CopyDirectory
        if ([IO.File]::Exists($ImagePath)) {
            if ((Get-FileDigest $ImagePath) -cne $OriginalHash) {
                throw 'Uninstaller copy changed after exit; refusing removal.'
            }
            [IO.File]::Delete($ImagePath)
        }
        $Done = [IO.Path]::Combine($CopyDirectory, '_unins-done.tmp')
        if ([IO.File]::Exists($Done)) {
            Assert-PlainPath $Done
            if (([IO.FileInfo]$Done).Length -ne 0) { throw 'Unexpected uninstall completion file.' }
            [IO.File]::Delete($Done)
        }
        if ([IO.Directory]::Exists($CopyDirectory)) { [IO.Directory]::Delete($CopyDirectory, $false) }
        exit 0
    } catch {
        $LastFailure = $_
        [Threading.Thread]::Sleep(100)
    }
}
# Do not turn cleanup failure into a silent success or sweep the parent temp dir.
$null = [Reflection.Assembly]::Load('System.Windows.Forms, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089')
$null = [Windows.Forms.MessageBox]::Show(
    ('Uninstall temporary-file cleanup was not completed. Close the related processes and retry. Remaining directory: ' + $CopyDirectory),
    'PKUCourseHelper - cleanup incomplete', 'OK', 'Warning')
throw $LastFailure
