# add wix binaries to the path
$env:Path += ";C:\Program Files (x86)\WiX Toolset v3.11\bin"
$env:exename = "chia-wallet" # if you update this make sure to update .gitignore
$env:electronpackagerdir = $env:exename + "-win32-x64"
$env:version = "0.1.6"

# remove any exisitng outputs
Write-Host "Cleaning any previous outputs"
Remove-Item $env:electronpackagerdir -Recurse -Force -ErrorAction Ignore
Remove-Item *.wixobj -Force -ErrorAction Ignore
Remove-Item *.wixpdb -Force -ErrorAction Ignore
Remove-Item *.msi -Force -ErrorAction Ignore
Remove-Item electron-packager-files.wxs -Force -ErrorAction Ignore

# package up the electron stuff and sources
electron-packager src $env:exename --platform=win32

# compile the installer
Write-Host "Compiling installer"

# this generates electron-packager-files.wxs from the contents of the electron packager folder
heat dir $env:electronpackagerdir -cg ChiaFiles -gg -scom -sreg -sfrag -srd -dr INSTALLDIR -out electron-packager-files.wxs

candle electron-packager-files.wxs chia.wxs

# link the installer
Write-Host "Linking Windows Installer database"
light electron-packager-files.wixobj chia.wixobj -b $env:electronpackagerdir -o Chia.msi
