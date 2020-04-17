# shared configuraiton values used in packaging files
$env:path += ";${env:ProgramFiles(x86)}\WiX Toolset v3.11\bin" # add wix to path
$env:walletProductName = "chia-wallet"
$env:blockchainProductName = "chia-blockchain"
$env:version = "0.1.5" # all packages share the same version
$env:resourceDir = ".\resources" # bitmaps, icons etc
$env:prereqDir = ".\prerequisites" # location for any pre-req installers

$buildDir = ".\build" # where temp and final build output go
$sourceDir = ".\src" # the location of wxs files etc
$electronPackagerDir = $env:walletProductName + "-win32-x64" # the folder that electron-packager creates
