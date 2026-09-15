# Local build entry point; all build environments and caches stay in the repo.
[CmdletBinding()]
param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$SavedEnvironment = @{}
foreach ($Key in @('PATH', 'UV_CACHE_DIR', 'UV_PYTHON', 'npm_config_cache', 'PYINSTALLER_CONFIG_DIR')) {
    $SavedEnvironment[$Key] = [Environment]::GetEnvironmentVariable($Key, 'Process')
}

function Assert-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw ($Step + ' failed: ' + $LASTEXITCODE) }
}

Push-Location $RepoRoot
try {
    $PythonPath = & $Python -c "import sys, struct; assert sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8, 'Python 3.11 x64 is required'; print(sys.executable)"
    Assert-Exit 'Check Python'
    $ToolsPython = Join-Path $RepoRoot '.venv-build-tools/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $ToolsPython)) {
        & $PythonPath -m venv .venv-build-tools
        Assert-Exit 'Create build tools environment'
    }
    $Uv = Join-Path $RepoRoot '.venv-build-tools/Scripts/uv.exe'
    if (-not (Test-Path -LiteralPath $Uv)) {
        & $ToolsPython -m pip install uv --index-url https://pypi.tuna.tsinghua.edu.cn/simple --cache-dir (Join-Path $RepoRoot 'build/pip-cache') --disable-pip-version-check
        Assert-Exit 'Install uv'
    }
    $env:PATH = (Split-Path -Parent $Uv) + [IO.Path]::PathSeparator + $env:PATH
    $env:UV_CACHE_DIR = Join-Path $RepoRoot 'build/uv-cache'
    $env:UV_PYTHON = $PythonPath
    $env:npm_config_cache = Join-Path $RepoRoot 'build/npm-cache'
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $RepoRoot 'build/pyinstaller-cache'
    & (Join-Path $RepoRoot 'packaging/build_windows.ps1')
} finally {
    foreach ($Key in $SavedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($Key, $SavedEnvironment[$Key], 'Process')
    }
    Pop-Location
}
