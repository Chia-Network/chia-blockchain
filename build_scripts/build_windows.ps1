# $env:path should contain a path to editbin.exe and signtool.exe

mkdir build_scripts\win_build
cd build_scripts\win_build

Write-Output "   ---"
Write-Output "curl miniupnpc, setprotitle"
Write-Output "   ---"
curl -OL --show-error --fail https://download.chia.net/simple/miniupnpc/miniupnpc-2.1-cp37-cp37m-win_amd64.whl
curl -OL --show-error --fail https://download.chia.net/simple/setproctitle/setproctitle-1.1.10-cp37-cp37m-win_amd64.whl
cd ..\..

Write-Output "   ---"
Write-Output "Create venv - python3.7 or 3.8 is required in PATH"
Write-Output "   ---"
python -m venv venv
. .\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install wheel pep517
pip install pywin32 pyinstaller
pip install setuptools_scm

Write-Output "   ---"
Write-Output "Get CHIA_INSTALLER_VERSION"
# The environment variable CHIA_INSTALLER_VERSION needs to be defined
$env:CHIA_INSTALLER_VERSION = python .\build_scripts\installer-version.py -win

if (-not (Test-Path env:CHIA_INSTALLER_VERSION)) {
  $env:CHIA_INSTALLER_VERSION = '0.0.0'
  Write-Output "WARNING: No environment variable CHIA_INSTALLER_VERSION set. Using 0.0.0"
  }
Write-Output "Chia Version is: $env:CHIA_INSTALLER_VERSION"
Write-Output "   ---"

Write-Output "   ---"
Write-Output "Build chia-blockchain wheels"
Write-Output "   ---"
pip wheel --use-pep517 --only-binary cbor2 --extra-index-url https://download.chia.net/simple/ -f . --wheel-dir=.\build_scripts\win_build .

Write-Output "   ---"
Write-Output "Install chia-blockchain wheels into venv with pip"
Write-Output "   ---"

Write-Output "pip install miniupnpc"
cd build_scripts
pip install --no-index --find-links=.\win_build\ miniupnpc
Write-Output "pip install setproctitle"
pip install --no-index --find-links=.\win_build\ setproctitle
Write-Output "pip install chia-blockchain"
pip install --no-index --find-links=.\win_build\ chia-blockchain

Write-Output "   ---"
Write-Output "Use pyinstaller to create chia .exe's"
Write-Output "   ---"
pyinstaller --log-level INFO daemon_windows.spec

Write-Output "   ---"
Write-Output "Copy chia executables to electron-react/"
Write-Output "   ---"
cp -r dist/daemon ../electron-react/
cd ../electron-react

Write-Output "   ---"
Write-Output "Prepare Electron packager"
Write-Output "   ---"
npm install --save-dev electron-winstaller
npm install -g electron-packager
npm install

Write-Output "   ---"
Write-Output "Electron package Windows Installer"
Write-Output "   ---"
npm run build

Write-Output "   ---"
Write-Output "Increase the stack for chiapos"
# editbin.exe needs to be in the path
#Start-Process "editbin.exe" -ArgumentList "/STACK:8000000 daemon\create_plots.exe" -Wait
editbin.exe /STACK:8000000 daemon\create_plots.exe
Write-Output "   ---"

$packageVersion = "$env:CHIA_INSTALLER_VERSION"
$packageName = "Chia-$packageVersion"

Write-Output "packageName is $packageName"

Write-Output "   ---"
Write-Output "electron-packager"
electron-packager . Chia --asar.unpack="**/daemon/**" --overwrite --icon=.\src\assets\img\chia.ico --app-version=$packageVersion
Write-Output "   ---"

Write-Output "   ---"
Write-Output "node winstaller.js"
node winstaller.js
Write-Output "   ---"

If ($env:HAS_SECRETS) {
   Write-Output "   ---"
   Write-Output "Add timestamp and verify signature"
   Write-Output "   ---"
   signtool.exe timestamp /v /t http://timestamp.comodoca.com/ .\release-builds\windows-installer\ChiaSetup-$packageVersion.exe
   signtool.exe verify /v /pa .\release-builds\windows-installer\ChiaSetup-$packageVersion.exe
   }   Else    {
   Write-Output "Skipping timestamp and verify signatures - no authorization to install certificates"
}

Write-Output "   ---"
Write-Output "Windows Installer complete"
Write-Output "   ---"
