$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "frontend")
& npm.cmd ci
& npm.cmd run build
Set-Location $root
& uv sync --extra dev
& uv run pytest
