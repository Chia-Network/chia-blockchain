# Include required files
$ScriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
try {
    . ("$ScriptDirectory\config.ps1")
}
catch {
    Write-Host "Error while loading supporting PowerShell Scripts" 
    exit 1
}
$venvDir = "..\venv"

$tempName = "blockchain-files"
$packageName = "$env:blockchainProductName-$env:version.msi"

# this generates package-files.wxs from the contents of the electron packager folder
heat dir $venvDir -cg ChiaBlockchainFiles -gg -scom -sreg -sfrag -srd -dr INSTALLDIR -out "$buildDir\$tempName.wxs"
if ($LastExitCode) { exit $LastExitCode }

# compile the installer
candle "$buildDir\$tempName.wxs" "$sourceDir\blockchain-msi.wxs" -o "$buildDir\"
if ($LastExitCode) { exit $LastExitCode }

# link the installer
light -ext WixUIExtension "$buildDir\$tempName.wixobj" "$buildDir\blockchain-msi.wixobj" -b $venvDir -o "$buildDir\$packageName"
if ($LastExitCode) { exit $LastExitCode }

Write-Host "Successfully built $packageName"
