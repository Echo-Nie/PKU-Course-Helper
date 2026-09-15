# Parse without running installers or invoking any Windows-only functionality.
[CmdletBinding()]
param([string]$Repo = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$Failed = $false
foreach ($File in @(Get-ChildItem -LiteralPath (Join-Path $Repo 'packaging'), (Join-Path $Repo 'tools') -Filter '*.ps1')) {
    $ParseTokens = $null
    $ParseErrors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($File.FullName, [ref]$ParseTokens, [ref]$ParseErrors)
    if ($ParseErrors.Count) {
        $Failed = $true
        foreach ($ParseError in $ParseErrors) {
            Write-Output ($File.Name + ':' + $ParseError.Extent.StartLineNumber + ': ' + $ParseError.Message)
        }
    } else { Write-Output ('Syntax OK: ' + $File.Name) }
}
if ($Failed) { throw 'PowerShell source syntax check failed.' }
