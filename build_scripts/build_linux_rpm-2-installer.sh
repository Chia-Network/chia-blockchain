#!/bin/bash

set -o errexit

git status
git submodule

if [ ! "$1" ]; then
  echo "This script requires either amd64 of arm64 as an argument"
	exit 1
elif [ "$1" = "amd64" ]; then
	#PLATFORM="$1"
	REDHAT_PLATFORM="x86_64"
	DIR_NAME="chia-blockchain-linux-x64"
else
	#PLATFORM="$1"
	DIR_NAME="chia-blockchain-linux-arm64"
fi

# If the env variable NOTARIZE and the username and password variables are
# set, this will attempt to Notarize the signed DMG

if [ ! "$CHIA_INSTALLER_VERSION" ]; then
	echo "WARNING: No environment variable CHIA_INSTALLER_VERSION set. Using 0.0.0."
	CHIA_INSTALLER_VERSION="0.0.0"
fi
echo "Chia Installer Version is: $CHIA_INSTALLER_VERSION"

echo "Installing npm and electron packagers"
cd npm_linux_rpm || exit
npm ci
GLOBAL_NPM_ROOT=$(pwd)/node_modules
PATH=$(npm bin):$PATH
cd .. || exit

echo "Create dist/"
rm -rf dist
mkdir dist

echo "Create executables with pyinstaller"
SPEC_FILE=$(python -c 'import chia; print(chia.PYINSTALLER_SPEC_PATH)')
pyinstaller --log-level=INFO "$SPEC_FILE"
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "pyinstaller failed!"
	exit $LAST_EXIT_CODE
fi

# Builds CLI only rpm
CLI_RPM_BASE="chia-blockchain-cli-$CHIA_INSTALLER_VERSION-1.$REDHAT_PLATFORM"
mkdir -p "dist/$CLI_RPM_BASE/opt/chia"
mkdir -p "dist/$CLI_RPM_BASE/usr/bin"
cp -r dist/daemon/* "dist/$CLI_RPM_BASE/opt/chia/"
ln -s ../../opt/chia/chia "dist/$CLI_RPM_BASE/usr/bin/chia"
# This is built into the base build image
# shellcheck disable=SC1091
. /etc/profile.d/rvm.sh
rvm use ruby-3
# /usr/lib64/libcrypt.so.1 is marked as a dependency specifically because newer versions of fedora bundle
# libcrypt.so.2 by default, and the libxcrypt-compat package needs to be installed for the other version
# Marking as a dependency allows yum/dnf to automatically install the libxcrypt-compat package as well
fpm -s dir -t rpm \
  -C "dist/$CLI_RPM_BASE" \
  -p "dist/$CLI_RPM_BASE.rpm" \
  --name chia-blockchain-cli \
  --license Apache-2.0 \
  --version "$CHIA_INSTALLER_VERSION" \
  --architecture "$REDHAT_PLATFORM" \
  --description "Chia is a modern cryptocurrency built from scratch, designed to be efficient, decentralized, and secure." \
  --depends /usr/lib64/libcrypt.so.1 \
  .
# CLI only rpm done

cp -r dist/daemon ../chia-blockchain-gui/packages/gui

# Change to the gui package
cd ../chia-blockchain-gui/packages/gui || exit

# sets the version for chia-blockchain in package.json
cp package.json package.json.orig
jq --arg VER "$CHIA_INSTALLER_VERSION" '.version=$VER' package.json > temp.json && mv temp.json package.json

echo electron-packager
electron-packager . chia-blockchain --asar.unpack="**/daemon/**" --platform=linux \
--icon=src/assets/img/Chia.icns --overwrite --app-bundle-id=net.chia.blockchain \
--appVersion=$CHIA_INSTALLER_VERSION --executable-name=chia-blockchain \
--no-prune --no-deref-symlinks \
--ignore="/node_modules/(?!ws(/|$))(?!@electron(/|$))" --ignore="^/src$" --ignore="^/public$"
LAST_EXIT_CODE=$?
# Note: `node_modules/ws` and `node_modules/@electron/remote` are dynamic dependencies
# which GUI calls by `window.require('...')` at runtime.
# So `ws` and `@electron/remote` cannot be ignored at this time.
ls -l $DIR_NAME/resources

# reset the package.json to the original
mv package.json.orig package.json

if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-packager failed!"
	exit $LAST_EXIT_CODE
fi

mv $DIR_NAME ../../../build_scripts/dist/
cd ../../../build_scripts || exit

if [ "$REDHAT_PLATFORM" = "x86_64" ]; then
	echo "Create chia-blockchain-$CHIA_INSTALLER_VERSION.rpm"

	# Disables build links from the generated rpm so that we dont conflict with other packages. See https://github.com/Chia-Network/chia-blockchain/issues/3846
	# shellcheck disable=SC2086
	sed -i '1s/^/%define _build_id_links none\n%global _enable_debug_package 0\n%global debug_package %{nil}\n%global __os_install_post \/usr\/lib\/rpm\/brp-compress %{nil}\n/' "$GLOBAL_NPM_ROOT/electron-installer-redhat/resources/spec.ejs"

	# Use attr feature of RPM to set the chrome-sandbox permissions
	# adds a %attr line after the %files line
	# The location is based on the existing location inside spec.ej
	sed -i '/^%files/a %attr(4755, root, root) /usr/lib/<%= name %>/chrome-sandbox' "$GLOBAL_NPM_ROOT/electron-installer-redhat/resources/spec.ejs"

	# Updates the requirements for building an RPM on Centos 7 to allow older version of rpm-build and not use the boolean dependencies
	# See https://github.com/electron-userland/electron-installer-redhat/issues/157
	# shellcheck disable=SC2086
	sed -i "s#throw new Error('Please upgrade to RPM 4.13.*#console.warn('You are using RPM < 4.13')\n      return { requires: [ 'gtk3', 'libnotify', 'nss', 'libXScrnSaver', 'libXtst', 'xdg-utils', 'at-spi2-core', 'libdrm', 'mesa-libgbm', 'libxcb' ] }#g" $GLOBAL_NPM_ROOT/electron-installer-redhat/src/dependencies.js

  electron-installer-redhat --src dist/$DIR_NAME/ \
  --arch "$REDHAT_PLATFORM" \
  --options.version $CHIA_INSTALLER_VERSION \
  --config rpm-options.json
  LAST_EXIT_CODE=$?
  if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	  echo >&2 "electron-installer-redhat failed!"
	  exit $LAST_EXIT_CODE
  fi
fi

# Move the cli only rpm into final installers as well, so it gets uploaded as an artifact
mv "dist/$CLI_RPM_BASE.rpm" final_installer/

ls final_installer/
