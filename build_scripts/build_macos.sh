#!/bin/bash
pip install setuptools_scm
# The environment variable CHIA_INSTALLER_VERSION needs to be defined
CHIA_INSTALLER_VERSION=$(python installer-version.py)

if [ ! "$CHIA_INSTALLER_VERSION" ]; then
	echo "WARNING: No environment variable CHIA_INSTALLER_VERSION set. Using 0.0.0."
	CHIA_INSTALLER_VERSION="0.0.0"
fi
echo "Chia Installer Version is: $CHIA_INSTALLER_VERSION"

echo "Installing npm and electron packagers"
npm install electron-installer-dmg -g
npm install electron-packager -g
npm install electron/electron-osx-sign #master --save-dev -g

echo "Create dist/"
sudo rm -rf dist
mkdir dist

echo "Create executeables with pyinstaller"
pip install pyinstaller==4.0
sudo pyinstaller --log-level=INFO daemon.spec
cp -r dist/daemon ../electron-react
cd .. || exit
cd electron-react || exit

echo "npm build"
npm install
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "npm run build failed!"
	exit $LAST_EXIT_CODE
fi
electron-packager . Chia --asar.unpack="**/daemon/**" --platform=darwin --icon=src/assets/img/Chia.icns --overwrite --app-bundle-id=net.chia.blockchain --appVersion=$CHIA_INSTALLER_VERSION
electron-osx-sign Chia-darwin-x64/Chia.app --platform=darwin --hardened-runtime=true --provisioning-profile=chiablockchain.provisionprofile --entitlements=entitlements.mac.plist --entitlements-inherit=entitlements.mac.plist
mv Chia-darwin-x64 ../build_scripts/dist/
cd ../build_scripts || exit

echo "Create .dmg"
mkdir final_installer
electron-installer-dmg dist/Chia-darwin-x64/Chia.app Chia-$CHIA_INSTALLER_VERSION --overwrite --out final_installer
echo "ls -l"
ls -l
