# Include required files
$ScriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
try {
    . ("$ScriptDirectory\config.ps1")
}
catch {
    Write-Host "Error while loading supporting PowerShell Scripts" 
    exit 1
}

candle "$sourceDir\bundle.wxs" "$sourceDir\blockchain-package.wxs" "$sourceDir\wallet-package.wxs" -o "$buildDir\" -ext WixBalExtension -ext WixUtilExtension
if ($LastExitCode) { exit $LastExitCode }

light "$buildDir\bundle.wixobj" "$buildDir\blockchain-package.wixobj" "$buildDir\wallet-package.wixobj" -o "$buildDir\chia-bundle" -ext WixBalExtension -ext WixUtilExtension
if ($LastExitCode) { exit $LastExitCode }

Write-Host "Successfully built chia-bundle.exe"