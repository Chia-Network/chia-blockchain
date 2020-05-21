cd ..
mkdir build_scripts\win_build
cd build_scripts\win_build

curl -OL --show-error --fail https://download.chia.net/simple/miniupnpc/miniupnpc-2.1-cp37-cp37m-win_amd64.whl
curl -OL --show-error --fail https://download.chia.net/simple/setproctitle/setproctitle-1.1.10-cp37-cp37m-win_amd64.whl
# C:\curl\curl.exe -OL --show-error --fail https://download.chia.net/simple/setproctitle/setproctitle-1.1.10-cp37-cp37m-win_amd64.whl
# C:\curl\curl.exe -OL --show-error --fail https://download.chia.net/simple/miniupnpc/miniupnpc-2.1-cp37-cp37m-win_amd64.whl

Write-Output "checkpoint 1";
cd ..\..
python -m pip install --upgrade pip
pip install pep517 wheel
pip wheel --use-pep517 --only-binary cbor2 --extra-index-url https://download.chia.net/simple/ -f . --wheel-dir=.\build_scripts\win_build .
Write-Output "checkpoint 2";

python -m venv venv
. .\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
cd build_scripts
python install_win.py
Write-Output "checkpoint 3";

pip install pywin32
pip install pyinstaller
pyinstaller daemon_windows.spec
Write-Output "checkpoint 4";

cp -r dist/daemon ../electron-react/
cd ../electron-react

Write-Output "checkpoint 5";

npm install --save-dev electron-winstaller
npm install -g electron-packager
npm install
npm run build
electron-packager . Chia --asar.unpack="**/daemon/**" --overwrite --icon=./src/assets/img/chia.ico
node winstaller.js
