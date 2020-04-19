# This script builds the wallet MSI package
$ScriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
try {
    . ("$ScriptDirectory\config.ps1")
}
catch {
    Write-Host "Error while loading supporting PowerShell Scripts" 
    Write-Host $_
    exit 1
}

# package up the electron stuff and sources
electron-packager ../electron-ui $env:walletProductName --platform=win32 --arch=x64 --icon="$env:resourceDir\icon.ico" `
            --app-version="$env:version" --win32metadata.CompanyName="Chia Network" --win32metadata.ProductName="Chia Wallet" `
            --app-copyright="Chia Network 2020"
if ($LastExitCode) { exit $LastExitCode }

$tempName = "electron-packager-files"
$packageName = "$env:walletProductName-$env:version.msi"

# this generates package-files.wxs from the contents of the electron packager folder
Write-Host "Creating manifest of electron files"
heat dir $electronPackagerDir -cg ChiaWalletFiles -nologo -gg -scom -sreg -sfrag -srd -dr INSTALLDIR -out "$buildDir\$tempName.wxs"
if ($LastExitCode) { exit $LastExitCode }

# compile the installer
Write-Host "Compiling $packageName"
candle "$buildDir\$tempName.wxs" "$sourceDir\wallet-msi.wxs" -arch x64 -nologo -o "$buildDir\"
if ($LastExitCode) { exit $LastExitCode }

# link the installer
Write-Host "Building $packageName"
light -ext WixUIExtension "$buildDir\$tempName.wixobj" "$buildDir\wallet-msi.wixobj" -nologo -b $electronPackagerDir -o "$buildDir\$packageName" -sw1076
if ($LastExitCode) { exit $LastExitCode }

Sign-Item "$buildDir\$packageName"

Write-Host "Successfully built $packageName"
