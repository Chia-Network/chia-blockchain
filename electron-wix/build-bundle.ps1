# This script builds the bundled installation executable
$ScriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
try {
    . ("$ScriptDirectory\config.ps1")
}
catch {
    Write-Host "Error while loading supporting PowerShell Scripts" 
    exit 1
}
$packageName = "chia-bundle-$env:version.exe"

Write-Host "Compiling $packageName"
candle "$sourceDir\bundle.wxs" "$sourceDir\msvc2019-package.wxs" "$sourceDir\blockchain-package.wxs" "$sourceDir\wallet-package.wxs" -nologo -o "$buildDir\" -ext WixBalExtension -ext WixUtilExtension
if ($LastExitCode) { exit $LastExitCode }

Write-Host "Building $packageName"
light "$buildDir\bundle.wixobj" "$buildDir\msvc2019-package.wixobj" "$buildDir\blockchain-package.wixobj" "$buildDir\wallet-package.wixobj" -nologo -o "$buildDir\$packageName" -sw1133 -ext WixBalExtension -ext WixUtilExtension
if ($LastExitCode) { exit $LastExitCode }

Write-Host "Successfully built $packageName"
