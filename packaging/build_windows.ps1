[CmdletBinding()]
param(
    [string]$OutputDirectory = 'dist/portable'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Windows x64 is required. PyInstaller cannot cross-compile this package from Linux.'
}
if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }

$RepoRoot = Split-Path -Parent $PSScriptRoot
$OldUvEnvironment = $env:UV_PROJECT_ENVIRONMENT
$env:UV_PROJECT_ENVIRONMENT = Join-Path $RepoRoot '.venv-desktop'
$BuildId = [Guid]::NewGuid().ToString('N')
$StageRoot = Join-Path $RepoRoot ('build/portable-' + $BuildId)
$StageDist = Join-Path $StageRoot 'dist'
$StageWork = Join-Path $StageRoot 'work'
$Bundle = Join-Path $StageDist 'PKUCourseHelper'
$OutputRoot = if ([IO.Path]::IsPathRooted($OutputDirectory)) {
    [IO.Path]::GetFullPath($OutputDirectory)
} else { [IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputDirectory)) }
# Each build receives its own output folder; existing artifacts are never erased.
$OutputRun = Join-Path $OutputRoot $BuildId

function Assert-CommandExit([string]$Description) {
    if ($LASTEXITCODE -ne 0) { throw ($Description + ' failed, exit code ' + $LASTEXITCODE) }
}

try {
    Get-Command uv -ErrorAction Stop | Out-Null
    Get-Command npm -ErrorAction Stop | Out-Null
    New-Item -ItemType Directory -Path $StageRoot, $OutputRun -Force | Out-Null
    Push-Location $RepoRoot
    try {
        & (Join-Path $RepoRoot 'tools/check_powershell_syntax.ps1') -Repo $RepoRoot
        & uv sync --locked --group dev --group build
        Assert-CommandExit 'Locked Python dependency installation'
        $Python = Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts/python.exe'
        & $Python -c "import platform; assert platform.machine().upper() in ('AMD64', 'X86_64'), 'x64 Python required'"
        Assert-CommandExit 'Python architecture check'
        Push-Location (Join-Path $RepoRoot 'frontend')
        try {
            & npm ci --no-audit --no-fund
            Assert-CommandExit 'Locked frontend dependency installation'
            & npm run test
            Assert-CommandExit 'Frontend tests'
            & npm run build
            Assert-CommandExit 'Frontend build'
        } finally { Pop-Location }

        & $Python -m pytest tests -q --junitxml (Join-Path $OutputRun 'pytest-windows.xml')
        Assert-CommandExit 'Offline Python and native Windows tests'
        # Keep test-only packages out of the frozen dependency environment.
        & uv sync --locked --no-default-groups --group build
        Assert-CommandExit 'Prune test-only dependencies before freezing'

        & $Python -m PyInstaller --noconfirm --clean --distpath $StageDist --workpath $StageWork (Join-Path $PSScriptRoot 'portable.spec')
        Assert-CommandExit 'PyInstaller build'
        $Licenses = Join-Path $Bundle 'licenses'
        & $Python (Join-Path $PSScriptRoot 'collect_licenses.py') --output $Licenses --frontend (Join-Path $RepoRoot 'frontend')
        Assert-CommandExit 'Dependency license collection'
        Copy-Item -LiteralPath (Join-Path $RepoRoot 'LICENSE') -Destination (Join-Path $Bundle 'LICENSE.txt')
        Copy-Item -LiteralPath (Join-Path $RepoRoot 'resources/model/LICENSE') -Destination (Join-Path $Licenses 'MODEL-LICENSE.txt')
        Copy-Item -LiteralPath (Join-Path $RepoRoot 'docs/PORTABLE.md') -Destination (Join-Path $Bundle '使用说明.md')
        # App-local configuration also supports DLLs retaining their browser
        # download marks; never edit Machine.config or remove Zone.Identifier.
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'PKUCourseHelper.exe.config') -Destination $Bundle

        $AuditTool = Join-Path $RepoRoot 'tools/audit_bundle.py'
        & $Python $AuditTool $Bundle --report (Join-Path $StageRoot 'pre-archive-audit.json')
        Assert-CommandExit 'Pre-archive content and size audit'
        # A GUI-subsystem executable must be waited on explicitly. Keep smoke
        # output outside the bundle so no runtime profile can enter the ZIP.
        $SelfTestReport = Join-Path $OutputRun 'frozen-self-test.json'
        $Executable = Join-Path $Bundle 'PKUCourseHelper.exe'
        $SelfTestProcess = Start-Process -FilePath $Executable -ArgumentList @('--self-test', ('"' + $SelfTestReport + '"')) -WorkingDirectory $StageRoot -WindowStyle Hidden -PassThru
        try {
            if (-not $SelfTestProcess.WaitForExit(60000)) {
                Stop-Process -Id $SelfTestProcess.Id -Force -ErrorAction SilentlyContinue
                throw 'Frozen executable self-test exceeded 60 seconds.'
            }
            $SelfTestProcess.WaitForExit()
            if ($SelfTestProcess.ExitCode -ne 0) {
                throw ('Frozen executable self-test failed, exit code ' + $SelfTestProcess.ExitCode)
            }
        } finally { $SelfTestProcess.Dispose() }
        if (-not (Test-Path -LiteralPath $SelfTestReport -PathType Leaf)) {
            throw 'Frozen executable self-test did not produce a report.'
        }
        $SelfTestEvidence = Get-Content -LiteralPath $SelfTestReport -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($SelfTestEvidence.passed -ne $true -or $SelfTestEvidence.platform -ne 'Windows' -or $SelfTestEvidence.frozen -ne $true) {
            throw 'Frozen executable self-test report did not confirm a passing frozen Windows build.'
        }
        $Archive = Join-Path $OutputRun 'PKUCourseHelper-windows-x64-portable.zip'
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::CreateFromDirectory($Bundle, $Archive, [IO.Compression.CompressionLevel]::Optimal, $true)
        $Report = Join-Path $OutputRun 'bundle-audit.json'
        & $Python $AuditTool $Bundle --archive $Archive --report $Report
        Assert-CommandExit 'Final ZIP integrity and size audit'
        $Hash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
        [IO.File]::WriteAllText((Join-Path $OutputRun 'SHA256SUMS.txt'), ($Hash + '  ' + [IO.Path]::GetFileName($Archive) + "`n"), [Text.UTF8Encoding]::new($false))
        Write-Host ('Portable artifact: ' + $Archive)
        Write-Host ('Audit report: ' + $Report)
        Write-Host 'Native UI and Windows no-residue acceptance checks remain required before distribution.'
    } finally { Pop-Location }
} finally {
    $env:UV_PROJECT_ENVIRONMENT = $OldUvEnvironment
}
