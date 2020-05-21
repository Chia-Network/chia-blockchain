cd ..
mkdir build_scripts\win_build
cd build_scripts\win_build

C:\curl\curl.exe -OL --show-error --fail https://download.chia.net/simple/miniupnpc/miniupnpc-2.1-cp37-cp37m-win_amd64.whl
C:\curl\curl.exe -OL --show-error --fail https://download.chia.net/simple/setproctitle/setproctitle-1.1.10-cp37-cp37m-win_amd64.whl
# C:\curl\curl.exe -OL --show-error --fail https://download.chia.net/simple/setproctitle/setproctitle-1.1.10-cp37-cp37m-win_amd64.whl
# C:\curl\curl.exe -OL --show-error --fail https://download.chia.net/simple/miniupnpc/miniupnpc-2.1-cp37-cp37m-win_amd64.whl


cd ..\..
mkdir .\build_scripts\win_build
python -m pip install --upgrade pip
pip install pep517 wheel
pip wheel --use-pep517 --only-binary cbor2 --extra-index-url https://download.chia.net/simple/ -f . --wheel-dir=.\build_scripts\win_build .

Start-Process "$env:HOMEDRIVE$env:HOMEPATH\AppData\Local\Programs\Python\Python37\python.exe" -ArgumentList "-m venv venv" -Wait
. .\venv\Scripts\Activate.ps1
cd build_scripts
python install_win.py

pip install pywin32
pip install pyinstaller
pyinstaller daemon_windows.spec

cp -r dist/daemon ../electron-react/
cd ../electron-react


npm install -g electron-installer-windows
npm install -g electron-packager
npm install
npm build
electron-packager . Chia --overwrite --icon=./src/assets/img/chia.png
electron-installer-windows --src chia-win32-x64 --dest ..\build_scripts\installers
