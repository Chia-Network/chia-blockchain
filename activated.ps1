$ErrorActionPreference = "Stop"

$script_directory = Split-Path $MyInvocation.MyCommand.Path -Parent

$command = $args[0]
$parameters = [System.Collections.ArrayList]$args
if ($parameters.Count -gt 0) {
    $parameters.RemoveAt(0)
}

& $script_directory/venv/Scripts/Activate.ps1
if ($command) {
    & $command @parameters
}

exit $LASTEXITCODE
