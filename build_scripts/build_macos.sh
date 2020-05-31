#!/bin/bash
echo "Installing npm and electron packagers"
npm install electron-installer-dmg -g
npm install electron-packager -g
npm install electron/electron-osx-sign#master --save-dev -g

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
electron-packager . Chia --asar.unpack="**/daemon/**" --platform=darwin --icon=src/assets/img/Chia.icns --overwrite --app-bundle-id=straya.domain.chia
electron-osx-sign Chia-darwin-x64/Chia.app --no-gatekeeper-assess  --platform=darwin  --hardened-runtime --provisioning-profile=embedded.provisionprofile --entitlements=entitlements.mac.plist --entitlements-inherit=entitlements.mac.plist
mv Chia-darwin-x64 ../build_scripts/dist/
cd ../build_scripts

echo "Create .dmg"
electron-installer-dmg dist/Chia-darwin-x64/Chia.app Chia-0.1.6 --overwrite
ls -l
