$ErrorActionPreference = "Stop"

Write-Output "we're inside python.ps1"

exit 1

$parameters = [System.Collections.ArrayList]$args
& python3 @parameters

exit $LASTEXITCODE
