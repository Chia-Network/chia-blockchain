# add wix to path
$env:Path += ";${env:ProgramFiles(x86)}\WiX Toolset v3.11\bin"
$env:exename = "chia-wallet" # if you update this make sure to update .gitignore
$env:version = "0.1.9"
$electronpackagerdir = $env:exename + "-win32-x64"

# remove any exisitng outputs
Write-Host "Cleaning any previous outputs"
Remove-Item $electronpackagerdir -Recurse -Force -ErrorAction Ignore
Remove-Item *.wixobj -Force -ErrorAction Ignore
Remove-Item *.wixpdb -Force -ErrorAction Ignore
Remove-Item *.msi -Force -ErrorAction Ignore
Remove-Item electron-packager-files.wxs -Force -ErrorAction Ignore

# package up the electron stuff and sources
electron-packager ../electron-ui $env:exename --platform=win32
if ($? -eq $false) { exit }

# compile the installer
Write-Host "Compiling installer"
# this generates package-files.wxs from the contents of the electron packager folder
heat dir $electronpackagerdir -cg ChiaFiles -gg -scom -sreg -sfrag -srd -dr INSTALLDIR -out electron-packager-files.wxs
if ($? -eq $false) { exit }

candle electron-packager-files.wxs chia.wxs
if ($? -eq $false) { exit }

# link the installer
Write-Host "Linking Windows Installer database"
light -ext WixUIExtension electron-packager-files.wixobj chia.wixobj -b $electronpackagerdir -o $env:exename-$env:version.msi
