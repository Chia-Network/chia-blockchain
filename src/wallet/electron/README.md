# Install
python3 -m venv .venv
. .venv/bin/activate

pip install zerorpc
pip install pyinstaller

npm install --runtime=electron --target=1.7.6
npm install electron-rebuild && ./node_modules/.bin/electron-rebuild
