# add wix to path
$env:Path += ";${env:ProgramFiles(x86)}\WiX Toolset v3.11\bin"
$env:exename = "chia-wallet" # if you update this make sure to update .gitignore
$env:version = "0.1.4"
$electronpackagerdir = $env:exename + "-win32-x64"
$buildDir = ".\build"

# remove any exisitng outputs
Write-Host "Cleaning any previous outputs"
Remove-Item $electronpackagerdir -Recurse -Force -ErrorAction Ignore
Remove-Item "$buildDir" -Recurse -Force -ErrorAction Ignore
New-Item -ItemType Directory -Path "$buildDir"

# package up the electron stuff and sources
electron-packager ../electron-ui $env:exename --platform=win32
if ($LastExitCode) { exit $LastExitCode }

$tempName = "electron-packager-files"
$msiName = "$env:exename-$env:version.msi"

# this generates package-files.wxs from the contents of the electron packager folder
heat dir $electronpackagerdir -cg ChiaFiles -gg -scom -sreg -sfrag -srd -dr INSTALLDIR -out "$buildDir\$tempName.wxs"
if ($LastExitCode) { exit $LastExitCode }

# compile the installer
candle "$buildDir\$tempName.wxs" chia.wxs -o "$buildDir\"
if ($LastExitCode) { exit $LastExitCode }

# link the installer
light -ext WixUIExtension "$buildDir\$tempName.wixobj" "$buildDir\chia.wixobj" -b $electronpackagerdir -o "$buildDir\$msiName"
if ($LastExitCode) { exit $LastExitCode }

Write-Host "Successfully built $msiName"
