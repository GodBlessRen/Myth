param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$env:PYTHONIOENCODING = 'utf-8'
python -m myth.cli --root $PSScriptRoot web --port $Port
