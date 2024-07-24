$ErrorActionPreference = "Stop"

$script_directory = Split-Path $MyInvocation.MyCommand.Path -Parent

$env_directory = $args[0]
$command = $args[1]
$parameters = [System.Collections.ArrayList]$args
$parameters.RemoveAt(0)
$parameters.RemoveAt(0)

& $script_directory/$env_directory/Scripts/Activate.ps1
& $command @parameters

exit $LASTEXITCODE
