#!/bin/bash
echo "Installing npm and electron packagers"
npm install electron-installer-dmg -g
npm install electron-packager -g

echo "Create dist/"
sudo rm -rf dist
mkdir dist

echo "Create executeables with pyinstaller"
pip install pyinstaller
sudo pyinstaller daemon.spec
cp -r dist/daemon ../electron-react
cd ..
cd electron-react

echo "npm build"
npm install
npm run build
electron-packager . Chia --overwrite --icon=./src/assets/img/chia.ico
mv Chia-darwin-x64 ../build_scripts/dist/
cd ../build_scripts

echo"Create .dmg"
electron-installer-dmg dist/Chia-darwin-x64/Chia.app Chia --overwrite
ls -l
