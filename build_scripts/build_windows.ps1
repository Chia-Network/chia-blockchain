cd ..
mkdir build_scripts\win_build
cd build_scripts\win_build

Write-Output "curl miniupnpc, setprotitle";
curl -OL --show-error --fail https://download.chia.net/simple/miniupnpc/miniupnpc-2.1-cp37-cp37m-win_amd64.whl
curl -OL --show-error --fail https://download.chia.net/simple/setproctitle/setproctitle-1.1.10-cp37-cp37m-win_amd64.whl

Write-Output "\n";
Write-Output "Install pip/python prerequisites\n";
cd ..\..
python -m pip install --upgrade pip
pip install pep517 wheel

Write-Output "\n";
Write-Output "Build chia-blockchain wheels\n";
pip wheel --use-pep517 --only-binary cbor2 --extra-index-url https://download.chia.net/simple/ -f . --wheel-dir=.\build_scripts\win_build .

Write-Output "\n";
Write-Output "\Create venv - python3.7 or 3.8 is required in PATH\n";
python -m venv venv
. .\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install pywin32 pyinstaller

Write-Output "\n";
Write-Output "Install chia-blockchain wheels into venv with install_win.py\n";
cd build_scripts
python install_win.py

Write-Output "\n";
Write-Output "Use pyinstaller to create chia .exe's\n";
pyinstaller daemon_windows.spec

Write-Output "\n";
Write-Output "Copy chia executables to electron-react/\n";
cp -r dist/daemon ../electron-react/
cd ../electron-react

Write-Output "\n";
Write-Output "Prepare Electron package\n";
npm install --save-dev electron-winstaller
npm install -g electron-packager
npm install

Write-Output "\n";
Write-Output "Electron package Windows Installer\n";
npm run build
electron-packager . Chia --asar.unpack="**/daemon/**" --overwrite --icon=./src/assets/img/chia.ico
node winstaller.js

Write-Output "\n";
Write-Output "Done\n";
