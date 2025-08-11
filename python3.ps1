$ErrorActionPreference = "Stop"

Write-Output "we're inside python3.ps1"

exit 1

$parameters = [System.Collections.ArrayList]$args
& python @parameters

exit $LASTEXITCODE
