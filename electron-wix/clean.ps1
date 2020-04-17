# This script deletes any intermediate and final build outputs

# Include required files
$ScriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
try {
    . ("$ScriptDirectory\config.ps1")
}
catch {
    Write-Host "Error while loading supporting PowerShell Scripts" 
    exit 1
}

# remove any exisitng outputs
Write-Host "Cleaning any previous outputs"
Remove-Item $electronpackagerdir -Recurse -Force -ErrorAction Ignore
Remove-Item "$buildDir" -Recurse -Force -ErrorAction Ignore
New-Item -ItemType Directory -Path "$buildDir"
