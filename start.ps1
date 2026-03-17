$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    Write-Host 'Creating virtual environment...' -ForegroundColor Cyan
    py -3 -m venv .venv
}

Write-Host 'Installing dependencies...' -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt

Write-Host 'Starting Codes app...' -ForegroundColor Green
& $VenvPython app.py
