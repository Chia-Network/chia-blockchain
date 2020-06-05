# The environment variable CHIA_VERSION needs to be defined
# $env:path should contain a path to editbin.exe

if (-not (Test-Path env:CHIA_VERSION)) { $env:CHIA_VERSION = '0.0.0' }
Write-Output "Chia Version is: $env:CHIA_VERSION";

cd ..

mkdir build_scripts\win_build
cd build_scripts\win_build

Write-Output "   ---";
Write-Output "curl miniupnpc, setprotitle";
Write-Output "   ---";
curl -OL --show-error --fail https://download.chia.net/simple/miniupnpc/miniupnpc-2.1-cp37-cp37m-win_amd64.whl
curl -OL --show-error --fail https://download.chia.net/simple/setproctitle/setproctitle-1.1.10-cp37-cp37m-win_amd64.whl

Write-Output "   ---";
Write-Output "Install pip/python prerequisites";
Write-Output "   ---";
cd ..\..
python -m pip install --upgrade pip
pip install pep517 wheel

Write-Output "   ---";
Write-Output "Build chia-blockchain wheels";
Write-Output "   ---";
pip wheel --use-pep517 --only-binary cbor2 --extra-index-url https://download.chia.net/simple/ -f . --wheel-dir=.\build_scripts\win_build .

Write-Output "   ---";
Write-Output "Create venv - python3.7 or 3.8 is required in PATH";
Write-Output "   ---";
python -m venv venv
. .\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install wheel
pip install pywin32 pyinstaller

Write-Output "   ---";
Write-Output "Install chia-blockchain wheels into venv with pip";
Write-Output "   ---";

Write-Output "pip install miniupnpc";
cd build_scripts
pip install --no-index --find-links=.\win_build\ miniupnpc
Write-Output "pip install setproctitle";
pip install --no-index --find-links=.\win_build\ setproctitle
Write-Output "pip install chia-blockchain";
pip install --no-index --find-links=.\win_build\ chia-blockchain

Write-Output "   ---";
Write-Output "Use pyinstaller to create chia .exe's";
Write-Output "   ---";
pyinstaller --log-level INFO daemon_windows.spec

Write-Output "   ---";
Write-Output "Copy chia executables to electron-react/";
Write-Output "   ---";
cp -r dist/daemon ../electron-react/
cd ../electron-react

Write-Output "   ---";
Write-Output "Prepare Electron package";
Write-Output "   ---";
npm install --save-dev electron-winstaller
npm install -g electron-packager
npm install

Write-Output "   ---";
Write-Output "Electron package Windows Installer";
Write-Output "   ---";
npm run build

Write-Output "   ---";
Write-Output "Increase the stack for chiapos";
# editbin.exe needs to be in your path
Start-Process "editbin.exe" -ArgumentList "/STACK:8000000 daemon/create_plots.exe" -Wait
Write-Output "   ---";

$packageName = "Chia-$env:CHIA_VERSION"
electron-packager . $packageName --asar.unpack="**/daemon/**" --overwrite --icon=./src/assets/img/chia.ico
node winstaller.js

Write-Output "   ---";
Write-Output "Windows Installer complete";
Write-Output "   ---";
