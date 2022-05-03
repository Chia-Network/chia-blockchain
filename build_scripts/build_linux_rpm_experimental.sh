#!/bin/bash

if [ ! "$1" ]; then
  echo "This script requires either amd64 of arm64 as an argument"
	exit 1
elif [ "$1" = "amd64" ]; then
	PLATFORM="$1"
	ELECTRON_BUILDER_OPTS="npx electron-builder build -l rpm --x64 "
else
	PLATFORM="$1"
	ELECTRON_BUILDER_OPTS="npx electron-builder build -l rpm --arm64"
fi

pip install setuptools_scm
# The environment variable CHIA_INSTALLER_VERSION needs to be defined
# If the env variable NOTARIZE and the username and password variables are
# set, this will attempt to Notarize the signed DMG
export CHIA_INSTALLER_VERSION=$(python installer-version.py)

if [ ! "$CHIA_INSTALLER_VERSION" ]; then
	echo "WARNING: No environment variable CHIA_INSTALLER_VERSION set. Using 0.0.0."
	CHIA_INSTALLER_VERSION="0.0.0"
fi
echo "Chia Installer Version is: $CHIA_INSTALLER_VERSION"

echo "Installing npm and electron packagers"
cd npm_linux|| exit
npm ci
PATH=$(npm bin):$PATH
cd .. || exit

echo "Checking for npx"
command -V npx

echo "Create dist/"
rm -rf dist
mkdir dist

echo "Create executables with pyinstaller"
pip install pyinstaller==4.9
SPEC_FILE=$(python -c 'import chia; print(chia.PYINSTALLER_SPEC_PATH)')
pyinstaller --log-level=INFO "$SPEC_FILE"
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "pyinstaller failed!"
	exit $LAST_EXIT_CODE
fi

cp -r dist/daemon ../chia-blockchain-gui/packages/gui
cd .. || exit
cd chia-blockchain-gui || exit

echo "npm build"
lerna clean -y
npm ci
# Audit fix does not currently work with Lerna. See https://github.com/lerna/lerna/issues/1663
# npm audit fix
npm run build
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "npm run build failed!"
	exit $LAST_EXIT_CODE
fi

# Change to the gui package
cd packages/gui || exit

# sets the version for chia-blockchain in package.json
cp package.json package.json.orig
jq --arg VER "$CHIA_INSTALLER_VERSION" '.version=$VER' package.json > temp.json && mv temp.json package.json

echo "Building Linux .deb Electron app"
"$ELECTRON_BUILDER_OPTS"
LAST_EXIT_CODE=$?

# reset the package.json to the original
mv package.json.orig package.json

if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-builder failed!"
	exit $LAST_EXIT_CODE
fi

echo "Listing dist contents"
ls -alh dist/

mv dist/* ../../../build_scripts/dist/
cd ../../../build_scripts || exit

mv dist/chia-"$CHIA_INSTALLER_VERSION".deb dist/chia-"$CHIA_INSTALLER_VERSION"_"$PLATFORM".deb
DEB_NAME=chia-"$CHIA_INSTALLER_VERSION"_"$PLATFORM".deb
rm -rf final_installer
mkdir final_installer
mv dist/"$DEB_NAME" final_installer/
ls final_installer/
