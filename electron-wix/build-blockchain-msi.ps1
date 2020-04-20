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
$blockchainDir = "$buildDir\blockchain"

$tempName = "blockchain-files"
$packageName = "$env:blockchainProductName-$env:version.msi"

# copy blockchain stuff into the build dir
New-Item -ItemType Directory -Path "$blockchainDir" -Force
New-Item -ItemType Directory -Path "$blockchainDir\wheels" -Force
Copy-Item ".\blockchain\install.ps1" "$blockchainDir" -Force
Copy-Item ".\blockchain\readme.txt" "$blockchainDir" -Force
Copy-Item ".\blockchain\*.whl" "$blockchainDir\wheels" -Force

# generate the script that will install all the wheels on the target machine
#$text = ""
#Get-ChildItem "$blockchainDir\wheels" -Filter *.whl |
#Foreach-Object {
#    $name = $_.Name
#    $text += "pip install .\wheels\$name`n"
#}
#New-Item "$blockchainDir\wheels.ps1" -Force
#Set-Content "$blockchainDir\wheels.ps1" $text

# this generates package-files.wxs from the contents of the electron packager folder
Write-Host "Creating manifest of python environment files"
heat dir $blockchainDir -cg ChiaBlockchainFiles -nologo -gg -scom -sreg -sfrag -srd -dr INSTALLDIR -out "$buildDir\$tempName.wxs"
if ($LastExitCode) { exit $LastExitCode }

# compile the installer
Write-Host "Compiling $packageName"
candle "$buildDir\$tempName.wxs" "$sourceDir\blockchain-msi.wxs" -nologo -arch x64 -o "$buildDir\"  -ext WixUtilExtension
if ($LastExitCode) { exit $LastExitCode }

# link the installer
Write-Host "Building $packageName"
light -ext WixUIExtension "$buildDir\$tempName.wixobj" "$buildDir\blockchain-msi.wixobj" -nologo -b $blockchainDir -o "$buildDir\$packageName"  -ext WixUtilExtension
if ($LastExitCode) { exit $LastExitCode }

Sign-Item "$buildDir\$packageName"

Write-Host "Successfully built $packageName"
