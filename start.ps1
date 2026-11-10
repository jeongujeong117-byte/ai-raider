$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
uv run --extra processing --extra browser python raider.py serve
