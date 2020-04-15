# Include required files
$ScriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
try {
    . ("$ScriptDirectory\config.ps1")
}
catch {
    Write-Host "Error while loading supporting PowerShell Scripts" 
    exit 1
}

# package up the electron stuff and sources
electron-packager ../electron-ui $env:exename --platform=win32 --arch=x64 --icon="$env:resourceDir\icon.ico" --app-version="$env:version" --win32metadata.CompanyName="Chia Network" --win32metadata.ProductName="Chia Wallet" --app-copyright="Chia Network 2020"
if ($LastExitCode) { exit $LastExitCode }

$tempName = "electron-packager-files"
$msiName = "$env:exename-$env:version.msi"

# this generates package-files.wxs from the contents of the electron packager folder
heat dir $electronpackagerdir -cg ChiaFiles -gg -scom -sreg -sfrag -srd -dr INSTALLDIR -out "$buildDir\$tempName.wxs"
if ($LastExitCode) { exit $LastExitCode }

# compile the installer
candle "$buildDir\$tempName.wxs" "$sourceDir\wallet-msi.wxs" -o "$buildDir\"
if ($LastExitCode) { exit $LastExitCode }

# link the installer
light -ext WixUIExtension "$buildDir\$tempName.wixobj" "$buildDir\wallet-msi.wixobj" -b $electronpackagerdir -o "$buildDir\$msiName" -sw1076
if ($LastExitCode) { exit $LastExitCode }

Write-Host "Successfully built $msiName"
