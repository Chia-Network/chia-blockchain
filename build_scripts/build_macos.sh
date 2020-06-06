#!/bin/bash

# The environment variable CHIA_INSTALLER_VERSION needs to be defined
CHIA_INSTALLER_VERSION=$(python installer-version.py)

if [ ! $CHIA_INSTALLER_VERSION ]; then
  echo "WARNING: No environment variable CHIA_INSTALLER_VERSION set. Using 0.0.0."
  CHIA_INSTALLER_VERSION="0.0.0"
fi
echo "Chia Installer Version is: $CHIA_INSTALLER_VERSION"

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
mkdir final_installer
electron-installer-dmg dist/Chia-darwin-x64/Chia.app Chia-$CHIA_INSTALLER_VERSION --overwrite --out final_installer
echo "ls -l"
ls -l
echo "ls -l final_installer"
ls -l final_installer
echo "ls -l dist/Chia-darwin-x64/"
ls -l dist/Chia-darwin-x64/
