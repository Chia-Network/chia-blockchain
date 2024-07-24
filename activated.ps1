$ErrorActionPreference = "Stop"

$script_directory = Split-Path $MyInvocation.MyCommand.Path -Parent

$env_director = $args[0]
$command = $args[1]
$parameters = [System.Collections.ArrayList]$args
$parameters.RemoveAt(0)
$parameters.RemoveAt(1)

& $script_directory/$env_director/Scripts/Activate.ps1
& $command @parameters

exit $LASTEXITCODE
