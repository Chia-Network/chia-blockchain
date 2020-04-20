# this script cleans and builds all of the packages and bundle
.\clean.ps1

.\build-wallet-msi.ps1
if ($LastExitCode) { exit $LastExitCode }

.\build-blockchain-msi.ps1
if ($LastExitCode) { exit $LastExitCode }

.\build-bundle.ps1
if ($LastExitCode) { exit $LastExitCode }

Write-Host "Succesfully built Chia installer for $env:version"
