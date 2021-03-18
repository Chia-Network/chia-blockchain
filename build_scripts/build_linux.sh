#!/bin/bash
pip install setuptools_scm
# The environment variable CHIA_INSTALLER_VERSION needs to be defined
# If the env variable NOTARIZE and the username and password variables are
# set, this will attempt to Notarize the signed DMG
CHIA_INSTALLER_VERSION=$(python installer-version.py)

if [ ! "$CHIA_INSTALLER_VERSION" ]; then
	echo "WARNING: No environment variable CHIA_INSTALLER_VERSION set. Using 0.0.0."
	CHIA_INSTALLER_VERSION="0.0.0"
fi
echo "Chia Installer Version is: $CHIA_INSTALLER_VERSION"

echo "Installing npm and electron packagers"
npm install electron-installer-debian -g
npm install electron-packager -g

echo "Create dist/"
sudo rm -rf dist
mkdir dist

echo "Create executeables with pyinstaller"
pip install pyinstaller==4.2
pyinstaller --log-level=INFO daemon.spec
cp -r dist/daemon ../chia-blockchain-gui
cd .. || exit
cd chia-blockchain-gui || exit

echo "npm build"
npm install
npm audit fix
npm run build
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "npm run build failed!"
	exit $LAST_EXIT_CODE
fi

electron-packager . chia-blockchain --asar.unpack="**/daemon/**" --platform=linux \
--icon=src/assets/img/Chia.icns --overwrite --app-bundle-id=net.chia.blockchain \
--appVersion=$CHIA_INSTALLER_VERSION --arch x64
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-packager failed!"
	exit $LAST_EXIT_CODE
fi

mv chia-linux-x64 ../build_scripts/dist/
cd ../build_scripts || exit

echo "Create chia-$CHIA_INSTALLER_VERSION.deb"
mkdir final_installer
ls -l dist
echo "subdir"
ls -l dist/chia-linux-x64/
electron-installer-debian --src dist/chia-linux-x64/ --dest final_installer/ \
--arch x64 --options.version $CHIA_INSTALLER_VERSION --overwrite
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-installer-debian failed!"
	exit $LAST_EXIT_CODE
fi
ls final_installer/
