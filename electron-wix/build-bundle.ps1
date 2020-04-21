# This script builds the bundled installation executable
$ScriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
try {
    . ("$ScriptDirectory\config.ps1")
}
catch {
    Write-Host "Error while loading supporting PowerShell Scripts"
    Write-Host $_    
    exit 1
}
$packageName = "chia-$env:version.exe"

Write-Host "Compiling $packageName"
candle "$sourceDir\bundle.wxs" "$sourceDir\python-package.wxs" "$sourceDir\msvc2019-package.wxs" `
            "$sourceDir\blockchain-package.wxs" "$sourceDir\wallet-package.wxs" `
            -nologo -o "$buildDir\" -ext WixBalExtension -ext WixUtilExtension
if ($LastExitCode) { exit $LastExitCode }

Write-Host "Building $packageName"
light "$buildDir\bundle.wixobj" "$buildDir\python-package.wixobj" "$buildDir\msvc2019-package.wixobj" `
            "$buildDir\blockchain-package.wixobj" "$buildDir\wallet-package.wixobj" `
            -nologo -o "$buildDir\$packageName" -sw1133 -ext WixBalExtension -ext WixUtilExtension
if ($LastExitCode) { exit $LastExitCode }

# the bootstrapper's engine.exe file needs to be signed with the same cert as everything else
# so take it out, sign it, and put it back into the bootstrapper, then sign the bootstrapper
# https://stackoverflow.com/questions/20381525/wix-digitally-sign-bootstrapper-project
insignia -ib "$buildDir\$packageName" -o "$buildDir\engine.exe"
Sign-Item "$buildDir\engine.exe"
insignia -ab "$buildDir\engine.exe" "$buildDir\$packageName" -o "$buildDir\$packageName"
Remove-Item "$buildDir\engine.exe" -Force -ErrorAction Ignore

Sign-Item "$buildDir\$packageName"

Write-Host "Successfully built $packageName"
