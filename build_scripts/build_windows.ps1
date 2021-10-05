# $env:path should contain a path to editbin.exe and signtool.exe

$ErrorActionPreference = "Stop"

mkdir build_scripts\win_build
Set-Location -Path ".\build_scripts\win_build" -PassThru

git status

Write-Output "   ---"
Write-Output "curl miniupnpc"
Write-Output "   ---"
Invoke-WebRequest -Uri "https://pypi.chia.net/simple/miniupnpc/miniupnpc-2.1-cp37-cp37m-win_amd64.whl" -OutFile "miniupnpc-2.1-cp37-cp37m-win_amd64.whl"
Write-Output "Using win_amd64 python 3.7 wheel from https://github.com/miniupnp/miniupnp/pull/475 (2.2.0-RC1)"
If ($LastExitCode -gt 0){
    Throw "Failed to download miniupnpc!"
}
else
{
    Set-Location -Path - -PassThru
    Write-Output "miniupnpc download successful."
}

Write-Output "   ---"
Write-Output "Create venv - python3.7 or 3.8 is required in PATH"
Write-Output "   ---"
python -m venv venv
. .\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install wheel pep517
pip install pywin32
pip install pyinstaller==4.2
pip install setuptools_scm

Write-Output "   ---"
Write-Output "Get FLORA_INSTALLER_VERSION"
# The environment variable FLORA_INSTALLER_VERSION needs to be defined
$env:FLORA_INSTALLER_VERSION = python .\build_scripts\installer-version.py -win

if (-not (Test-Path env:FLORA_INSTALLER_VERSION)) {
  $env:FLORA_INSTALLER_VERSION = '0.0.0'
  Write-Output "WARNING: No environment variable FLORA_INSTALLER_VERSION set. Using 0.0.0"
  }
Write-Output "Flora Version is: $env:FLORA_INSTALLER_VERSION"
Write-Output "   ---"

Write-Output "   ---"
Write-Output "Build flora-blockchain wheels"
Write-Output "   ---"
pip wheel --use-pep517 --extra-index-url https://pypi.chia.net/simple/ -f . --wheel-dir=.\build_scripts\win_build .

Write-Output "   ---"
Write-Output "Install flora-blockchain wheels into venv with pip"
Write-Output "   ---"

Write-Output "pip install miniupnpc"
Set-Location -Path ".\build_scripts" -PassThru
pip install --no-index --find-links=.\win_build\ miniupnpc
# Write-Output "pip install setproctitle"
# pip install setproctitle==1.2.2

Write-Output "pip install flora-blockchain"
pip install --no-index --find-links=.\win_build\ flora-blockchain

Write-Output "   ---"
Write-Output "Use pyinstaller to create flora .exe's"
Write-Output "   ---"
$SPEC_FILE = (python -c 'import flora; print(flora.PYINSTALLER_SPEC_PATH)') -join "`n"
pyinstaller --log-level INFO $SPEC_FILE

Write-Output "   ---"
Write-Output "Copy flora executables to flora-blockchain-gui-dev\"
Write-Output "   ---"
Copy-Item "dist\daemon" -Destination "..\flora-blockchain-gui-dev\" -Recurse
Set-Location -Path "..\flora-blockchain-gui-dev" -PassThru

git status

Write-Output "   ---"
Write-Output "Prepare Electron packager"
Write-Output "   ---"
npm install --save-dev electron-winstaller
npm install -g electron-packager
npm install
npm audit fix

git status

Write-Output "   ---"
Write-Output "Electron package Windows Installer"
Write-Output "   ---"
npm run build
If ($LastExitCode -gt 0){
    Throw "npm run build failed!"
}

Write-Output "   ---"
Write-Output "Increase the stack for flora command for (flora plots create) chiapos limitations"
# editbin.exe needs to be in the path
editbin.exe /STACK:8000000 daemon\flora.exe
Write-Output "   ---"

$packageVersion = "$env:FLORA_INSTALLER_VERSION"
$packageName = "Flora-$packageVersion"

Write-Output "packageName is $packageName"

Write-Output "   ---"
Write-Output "electron-packager"
electron-packager . Flora --asar.unpack="**\daemon\**" --overwrite --icon=.\src\assets\img\flora.ico --app-version=$packageVersion
Write-Output "   ---"

Write-Output "   ---"
Write-Output "node winstaller.js"
node winstaller.js
Write-Output "   ---"

git status

If ($env:HAS_SECRET) {
   Write-Output "   ---"
   Write-Output "Add timestamp and verify signature"
   Write-Output "   ---"
   signtool.exe timestamp /v /t http://timestamp.comodoca.com/ .\release-builds\windows-installer\FloraSetup-$packageVersion.exe
   signtool.exe verify /v /pa .\release-builds\windows-installer\FloraSetup-$packageVersion.exe
   }   Else    {
   Write-Output "Skipping timestamp and verify signatures - no authorization to install certificates"
}

git status

Write-Output "   ---"
Write-Output "Windows Installer complete"
Write-Output "   ---"
