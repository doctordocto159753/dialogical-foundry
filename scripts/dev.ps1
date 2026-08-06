$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Start-Process -FilePath "uv" -ArgumentList @("run", "uvicorn", "server.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $root -WindowStyle Hidden
Set-Location (Join-Path $root "frontend")
& npm.cmd run dev
