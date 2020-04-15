# add wix to path
$env:Path += ";${env:ProgramFiles(x86)}\WiX Toolset v3.11\bin"
$env:exename = "chia-wallet" # if you update this make sure to update .gitignore
$env:version = "0.1.5"
$env:resourceDir = ".\resources"
$electronpackagerdir = $env:exename + "-win32-x64"
$buildDir = ".\build"
$sourceDir = ".\src"