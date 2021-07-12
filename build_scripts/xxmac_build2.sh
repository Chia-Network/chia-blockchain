#!/bin/bash

if [[ x$1 == x ]]; then
	echo "need a version!!!!!"
	return
fi

cd chia-blockchain-gui

CHIA_INSTALLER_VERSION=$1


# echo "Installing npm and electron packagers ========================================================================"
# npm install electron-installer-dmg -g
# npm install electron-packager -g
# npm install electron/electron-osx-sign -g
# npm install notarize-cli -g

echo "Build ========================================================================"
npm install
npm audit fix
npm run build
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "npm run build failed!"
	exit $LAST_EXIT_CODE
fi


echo "Package ========================================================================"
electron-packager . Silicoin --asar.unpack="**/daemon/**" --platform=darwin \
--icon=src/assets/img/Chia.icns --overwrite --app-bundle-id=net.silicoin.blockchain \
--appVersion=$CHIA_INSTALLER_VERSION
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-packager failed!"
	exit $LAST_EXIT_CODE
fi


# echo "Sign ========================================================================"
# electron-osx-sign Silicoin-darwin-x64/Silicoin.app --platform=darwin \
#   --hardened-runtime=true --provisioning-profile=chiablockchain.provisionprofile \
#   --entitlements=entitlements.mac.plist --entitlements-inherit=entitlements.mac.plist \
#   --no-gatekeeper-assess
#  LAST_EXIT_CODE=$?
# if [ "$LAST_EXIT_CODE" -ne 0 ]; then
# 	echo >&2 "electron-osx-sign failed!"
# 	exit $LAST_EXIT_CODE
# fi


echo "Create DMG ========================================================================"
cd Silicoin-darwin-x64 || exit

DMG_NAME="Silicoin-$CHIA_INSTALLER_VERSION.dmg"

mkdir final_installer

electron-installer-dmg Silicoin.app Silicoin-$CHIA_INSTALLER_VERSION \
--overwrite --out final_installer
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-installer-dmg failed!"
	exit $LAST_EXIT_CODE
fi


# echo "Notarization ========================================================================"
# cd final_installer || exit
# notarize-cli --file=$DMG_NAME --bundle-id net.silicoin.blockchain --username "williejonagvio38@gmail.com" --password "mrdo-yfcr-intb-eyxr"
# echo "Notarization step complete"

cd ../
cd ../