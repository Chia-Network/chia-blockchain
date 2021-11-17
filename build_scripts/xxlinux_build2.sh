#!/bin/bash

if [[ x$1 == x ]]; then
	echo "need a version!!!!!"
	return
fi

# echo  ========================================================================"
#sudo apt-get update
#sudo apt install python3-venv
#sudo apt install build-essential
#sudo apt install zlib1g-dev

#sudo apt install node
#sudo apt install npm
#sudo apt install jq

cd chia-blockchain-gui
# echo "Installing npm and electron packagers ========================================"
#npm config set production true
#npm config set registry https://registry.npm.taobao.org
#npm config set registry http://registry.npmjs.org
#sudo npm install electron-packager -g
#sudo npm install electron-installer-debian -g



echo "Build ========================================================================"
npm install
#npm audit fix
#npm audit fix --only=prod
npm run build
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "npm run build failed!"
	exit $LAST_EXIT_CODE
fi


APP_VERSION=$1
APP_BUNDLEID="net.silicoin.blockchain"
APP_NAME="SIT"
DMG_NAME="$APP_NAME-$APP_VERSION"

PLATFORM="amd64"
#PLATFORM="arm64"
if [ "$PLATFORM" = "amd64" ]; then
	APP_DIR=$APP_NAME-linux-x64
else
	APP_DIR=$APP_NAME-linux-arm64
fi


echo "Deal package.json =============================================================="
cp package.json package.json.orig
jq --arg VER "$APP_VERSION" '.version=$VER' package.json > temp.json && mv temp.json package.json

rm -rf $APP_DIR
rm -rf final_installer

echo "Package ========================================================================"
electron-packager . $APP_NAME --asar.unpack="**/daemon/**" --platform=linux \
--icon=src/assets/img/chia_circle.png --overwrite --app-bundle-id=$APP_BUNDLEID \
--appVersion=$APP_VERSION
LAST_EXIT_CODE=$?

mv package.json.orig package.json
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-packager failed!"
	exit $LAST_EXIT_CODE
fi


echo "Create $DMG_NAME.deb ==============================================================="
mkdir final_installer
electron-installer-debian --src $APP_DIR/ --dest final_installer/ \
--arch "$PLATFORM" --options.version $APP_VERSION
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-installer-debian failed!"
	exit $LAST_EXIT_CODE
fi

cd ../





