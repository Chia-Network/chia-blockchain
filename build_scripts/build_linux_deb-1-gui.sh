#!/bin/bash

set -o errexit

echo "Installing global npm packages"
cd npm_linux_deb || exit
npm ci
PATH=$(npm bin):$PATH

cd ../../ || exit
git submodule update --init chia-blockchain-gui

cd ./chia-blockchain-gui || exit

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

# Remove unused packages
rm -rf node_modules

# Other than `chia-blockchain-gui/package/gui`, all other packages are no longer necessary after build.
# Since these unused packages make cache unnecessarily fat, here unused packages are removed.
echo "Remove unused @chia packages to make cache slim"
ls -l packages
rm -rf packages/api
rm -rf packages/api-react
rm -rf packages/core
rm -rf packages/icons
rm -rf packages/wallets

# Remove unused fat npm modules from the gui package
cd ./packages/gui/node_modules
echo "Remove unused node_modules in the gui package to make cache slim more"
rm -rf electron/dist # ~186MB
rm -rf "@mui" # ~71MB
rm -rf typescript # ~63MB

# Remove `packages/gui/node_modules/@chia` because it causes an error on later `electron-packager` command
rm -rf "@chia"
