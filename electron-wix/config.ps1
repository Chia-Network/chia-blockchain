# add wix to path
$env:Path += ";${env:ProgramFiles(x86)}\WiX Toolset v3.11\bin"
$env:walletExeName = "chia-wallet" # if you update this make sure to update .gitignore
$env:version = "0.1.5"
$env:resourceDir = ".\resources"
$electronPackagerDir = $env:walletExeName + "-win32-x64"
$buildDir = ".\build"
$sourceDir = ".\src"