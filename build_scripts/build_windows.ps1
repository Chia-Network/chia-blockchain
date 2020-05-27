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
Write-Output "Install chia-blockchain wheels into venv with install_win.py";
Write-Output "   ---";
pip install --only-binary miniupnpc setproctitle
cd build_scripts
pip install --no-index --find-links=.\win_build\ chia-blockchain

Write-Output "   ---";
Write-Output "Use pyinstaller to create chia .exe's";
Write-Output "   ---";
pyinstaller --add-binary daemon_windows.spec

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
electron-packager . Chia-0.1.6 --asar.unpack="**/daemon/**" --overwrite --icon=./src/assets/img/chia.ico
node winstaller.js

Write-Output "   ---";
Write-Output "Windows Installer complete";
Write-Output "   ---";
