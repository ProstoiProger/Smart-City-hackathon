$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Test-Path -LiteralPath '.venv/Scripts/python.exe') {
    & ./.venv/Scripts/python.exe run.py
} else {
    python run.py
}
