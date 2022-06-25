$ErrorActionPreference = "Stop"

$script_directory = Split-Path $MyInvocation.MyCommand.Path -Parent

Invoke-Expression "$script_directory/../venv/Scripts/activate"
Invoke-Expression "$args"
