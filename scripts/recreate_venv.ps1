<#
Recreate the project virtual environment using the newest available Python.
Usage (PowerShell):
  .\scripts\recreate_venv.ps1

This script tries to use the `py` launcher to find a recent Python, falls back to `python` on PATH,
creates a `.venv` in the project root, upgrades pip, and installs `requirements.txt`.
#>

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Try to get the newest installed Python using the py launcher
$pyPath = $null
try {
    $pyList = & py -0p 2>$null
    if ($LASTEXITCODE -eq 0 -and $pyList) {
        $firstLine = ($pyList -split "\r?\n" | Where-Object { $_ -match '\S' } | Select-Object -First 1).Trim()
        # extract the path token at the end of the line
        $parts = $firstLine -split '\s+'
        $pyPath = $parts[-1]
    }
} catch {}

if (-not $pyPath) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $pyPath = $cmd.Source }
}

if (-not $pyPath) {
    Write-Error "No Python executable found. Install Python 3.13+ and ensure it's on PATH or install the 'py' launcher."
    exit 1
}

Write-Host "Using Python:" $pyPath

# Create venv
& $pyPath -m venv "$scriptRoot\..\.venv"

$venvPython = Join-Path $scriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Failed to create .venv or locate python in .venv\Scripts."
    exit 1
}

& $venvPython -m pip install --upgrade pip setuptools wheel
& $venvPython -m pip install -r (Join-Path $scriptRoot "..\requirements.txt")

Write-Host 'Virtual environment created at .venv and dependencies installed. Activate with: .\.venv\Scripts\Activate.ps1'
