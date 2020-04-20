# This script builds the blockchain MSI package
$ScriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
try {
    . ("$ScriptDirectory\config.ps1")
}
catch {
    Write-Host "Error while loading supporting PowerShell Scripts"
    Write-Host $_    
    exit 1
}
$venvDir = "..\venv"

$tempName = "blockchain-files"
$packageName = "$env:blockchainProductName-$env:version.msi"

# this generates package-files.wxs from the contents of the electron packager folder
Write-Host "Creating manifest of python environment files"
heat dir $venvDir -cg ChiaBlockchainFiles -nologo -gg -scom -sreg -sfrag -srd -dr venvDir -out "$buildDir\$tempName.wxs"
if ($LastExitCode) { exit $LastExitCode }

# compile the installer
Write-Host "Compiling $packageName"
candle "$buildDir\$tempName.wxs" "$sourceDir\blockchain-msi.wxs" -nologo -arch x64 -o "$buildDir\"
if ($LastExitCode) { exit $LastExitCode }

# link the installer
Write-Host "Building $packageName"
light -ext WixUIExtension "$buildDir\$tempName.wixobj" "$buildDir\blockchain-msi.wixobj" -nologo -b $venvDir -o "$buildDir\$packageName"
if ($LastExitCode) { exit $LastExitCode }

Sign-Item "$buildDir\$packageName"

Write-Host "Successfully built $packageName"
