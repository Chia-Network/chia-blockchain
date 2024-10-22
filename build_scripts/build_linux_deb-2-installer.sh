#!/bin/bash

set -o errexit

if [ ! "$1" ]; then
  echo "This script requires either amd64 of arm64 as an argument"
  exit 1
elif [ "$1" = "amd64" ]; then
  PLATFORM="amd64"
else
  PLATFORM="arm64"
fi
export PLATFORM

git status
git submodule

# If the env variable NOTARIZE and the username and password variables are
# set, this will attempt to Notarize the signed DMG

if [ ! "$CHIA_INSTALLER_VERSION" ]; then
  echo "WARNING: No environment variable CHIA_INSTALLER_VERSION set. Using 0.0.0."
  CHIA_INSTALLER_VERSION="0.0.0"
fi
echo "Chia Installer Version is: $CHIA_INSTALLER_VERSION"
export CHIA_INSTALLER_VERSION

echo "Installing npm and electron packagers"
cd npm_linux || exit 1
npm ci
NPM_PATH="$(pwd)/node_modules/.bin"
cd .. || exit 1

echo "Create dist/"
rm -rf dist
mkdir dist

echo "Create executables with pyinstaller"
SPEC_FILE=$(python -c 'import sys; from pathlib import Path; path = Path(sys.argv[1]); print(path.absolute().as_posix())' "pyinstaller.spec")
pyinstaller --log-level=INFO "$SPEC_FILE"
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
  echo >&2 "pyinstaller failed!"
  exit $LAST_EXIT_CODE
fi

# Creates a directory of licenses
echo "Building pip and NPM license directory"
pwd
bash ./build_license_directory.sh

# Builds CLI only .deb
# need j2 for templating the control file
format_deb_version_string() {
  version_str=$1
  # Use sed to conform to expected apt versioning conventions:
  # - conditionally insert a hyphen before 'rc' or 'beta' if not already present
  # - replace '.dev' with '-dev'
  echo "$version_str" | sed -E 's/([0-9])(rc|beta)/\1-\2/g; s/\.dev/-dev/g'
}
pip install j2cli
CLI_DEB_BASE="chia-blockchain-cli_$CHIA_INSTALLER_VERSION-1_$PLATFORM"
mkdir -p "dist/$CLI_DEB_BASE/opt/chia"
mkdir -p "dist/$CLI_DEB_BASE/usr/bin"
mkdir -p "dist/$CLI_DEB_BASE/DEBIAN"
mkdir -p "dist/$CLI_DEB_BASE/etc/systemd/system"
CHIA_DEB_CONTROL_VERSION=$(format_deb_version_string "$CHIA_INSTALLER_VERSION")
export CHIA_DEB_CONTROL_VERSION
j2 -o "dist/$CLI_DEB_BASE/DEBIAN/control" assets/deb/control.j2
cp assets/systemd/*.service "dist/$CLI_DEB_BASE/etc/systemd/system/"
cp -r dist/daemon/* "dist/$CLI_DEB_BASE/opt/chia/"

ln -s ../../opt/chia/chia "dist/$CLI_DEB_BASE/usr/bin/chia"
dpkg-deb --build --root-owner-group "dist/$CLI_DEB_BASE"
# CLI only .deb done

cp -r dist/daemon ../chia-blockchain-gui/packages/gui

# Change to the gui package
cd ../chia-blockchain-gui/packages/gui || exit 1

# sets the version for chia-blockchain in package.json
cp package.json package.json.orig
jq --arg VER "$CHIA_INSTALLER_VERSION" '.version=$VER' package.json >temp.json && mv temp.json package.json

echo "Building Linux(deb) Electron app"
PRODUCT_NAME="chia"
if [ "$PLATFORM" = "arm64" ]; then
  # electron-builder does not work for arm64 as of Aug 16, 2022.
  # This is a temporary fix.
  # https://github.com/jordansissel/fpm/issues/1801#issuecomment-919877499
  # @TODO Consolidates the process to amd64 if the issue of electron-builder is resolved
  sudo apt -y install ruby ruby-dev
  # ERROR:  Error installing fpm:
  #     The last version of dotenv (>= 0) to support your Ruby & RubyGems was 2.8.1. Try installing it with `gem install dotenv -v 2.8.1` and then running the current command again
  #     dotenv requires Ruby version >= 3.0. The current ruby version is 2.7.0.0.
  # @TODO Once ruby 3.0 can be installed on `apt install ruby`, installing dotenv below should be removed.
  sudo gem install dotenv -v 2.8.1
  sudo gem install fpm
  echo USE_SYSTEM_FPM=true npx electron-builder build --linux deb --arm64 \
    --config.extraMetadata.name=chia-blockchain \
    --config.productName="$PRODUCT_NAME" --config.linux.desktop.Name="Chia Blockchain" \
    --config.deb.packageName="chia-blockchain" \
    --config ../../../build_scripts/electron-builder.json
  USE_SYSTEM_FPM=true npx electron-builder build --linux deb --arm64 \
    --config.extraMetadata.name=chia-blockchain \
    --config.productName="$PRODUCT_NAME" --config.linux.desktop.Name="Chia Blockchain" \
    --config.deb.packageName="chia-blockchain" \
    --config ../../../build_scripts/electron-builder.json
  LAST_EXIT_CODE=$?
else
  echo "${NPM_PATH}/electron-builder" build --linux deb --x64 \
    --config.extraMetadata.name=chia-blockchain \
    --config.productName="$PRODUCT_NAME" --config.linux.desktop.Name="Chia Blockchain" \
    --config.deb.packageName="chia-blockchain" \
    --config ../../../build_scripts/electron-builder.json
  "${NPM_PATH}/electron-builder" build --linux deb --x64 \
    --config.extraMetadata.name=chia-blockchain \
    --config.productName="$PRODUCT_NAME" --config.linux.desktop.Name="Chia Blockchain" \
    --config.deb.packageName="chia-blockchain" \
    --config ../../../build_scripts/electron-builder.json
  LAST_EXIT_CODE=$?
fi
ls -l dist/linux*-unpacked/resources

# reset the package.json to the original
mv package.json.orig package.json

if [ "$LAST_EXIT_CODE" -ne 0 ]; then
  echo >&2 "electron-builder failed!"
  exit $LAST_EXIT_CODE
fi

GUI_DEB_NAME=chia-blockchain_${CHIA_INSTALLER_VERSION}_${PLATFORM}.deb
mv "dist/${PRODUCT_NAME}-${CHIA_INSTALLER_VERSION}.deb" "../../../build_scripts/dist/${GUI_DEB_NAME}"
cd ../../../build_scripts || exit 1

echo "Create final installer"
rm -rf final_installer
mkdir final_installer

mv "dist/${GUI_DEB_NAME}" final_installer/
# Move the cli only deb into final installers as well, so it gets uploaded as an artifact
mv "dist/${CLI_DEB_BASE}.deb" final_installer/

ls -l final_installer/
