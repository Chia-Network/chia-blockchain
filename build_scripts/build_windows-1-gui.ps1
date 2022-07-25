# $env:path should contain a path to editbin.exe and signtool.exe

$ErrorActionPreference = "Stop"

git status
git submodule

Write-Output "   ---"
Write-Output "Setup npm packager"
Write-Output "   ---"
Set-Location -Path ".\npm_windows" -PassThru
npm ci
$Env:Path = $(npm bin) + ";" + $Env:Path
Set-Location -Path "..\" -PassThru

Set-Location -Path "..\chia-blockchain-gui" -PassThru

Write-Output "   ---"
Write-Output "Build GUI npm modules"
Write-Output "   ---"
$Env:NODE_OPTIONS = "--max-old-space-size=3000"

Write-Output "lerna clean -y"
lerna clean -y
Write-Output "npm ci"
npm ci
# Audit fix does not currently work with Lerna. See https://github.com/lerna/lerna/issues/1663
# npm audit fix

git status

Write-Output "npm run build"
npm run build
If ($LastExitCode -gt 0){
    Throw "npm run build failed!"
}
