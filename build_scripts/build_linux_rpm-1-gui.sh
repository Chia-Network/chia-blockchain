#!/bin/bash

set -o errexit

echo "Installing global npm packages"
cd npm_linux_rpm || exit
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
