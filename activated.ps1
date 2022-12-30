$ErrorActionPreference = "Stop"

$script_directory = Split-Path $MyInvocation.MyCommand.Path -Parent

$command = $args[0]
$parameters = [System.Collections.ArrayList]$args
$parameters.RemoveAt(0)

& $script_directory/venv/Scripts/Activate.ps1
& $command @parameters

exit $LASTEXITCODE
