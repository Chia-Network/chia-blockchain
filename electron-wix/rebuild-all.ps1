$ScriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
try {
    . ("$ScriptDirectory\config.ps1")
}
catch {
    Write-Host "Error while loading supporting PowerShell Scripts" 
    Write-Host $_    
    exit 1
}

# this script cleans and builds all of the packages and bundle
.\clean.ps1

New-Item -ItemType Directory -Path "$buildDir"

.\build-wallet-msi.ps1
if ($LastExitCode) { exit $LastExitCode }

.\build-blockchain-msi.ps1
if ($LastExitCode) { exit $LastExitCode }

.\build-bundle.ps1
if ($LastExitCode) { exit $LastExitCode }

Write-Host "Succesfully built Chia installer for $env:version"

New-Item -ItemType Directory -Path "$finalDir"
Copy-Item "$buildDir\*.msi" "$finalDir\" -Force
Copy-Item "$buildDir\*.exe" "$finalDir\" -Force