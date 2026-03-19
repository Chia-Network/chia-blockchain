#!/usr/bin/env bash

set -o errexit

cd ../ || exit 1
git submodule update --init chia-blockchain-gui

cd ./chia-blockchain-gui || exit 1

echo "npm build"
npx lerna clean -y # Removes packages/*/node_modules
npm ci
# Audit fix does not currently work with Lerna. See https://github.com/lerna/lerna/issues/1663
# npm audit fix
npm run build
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
  echo >&2 "npm run build failed!"
  exit $LAST_EXIT_CODE
fi

# Webpack already bundled all JS into build/. Clear production dependencies from
# package.json so electron-builder v26's node module collector doesn't fail when
# it can't find workspace packages that are removed below for cache optimization.
echo "Clearing dependencies from packages/gui/package.json for electron-builder"
node -e "
  const fs = require('fs');
  const p = JSON.parse(fs.readFileSync('./packages/gui/package.json', 'utf8'));
  p.dependencies = {};
  fs.writeFileSync('./packages/gui/package.json', JSON.stringify(p, null, 2) + '\n');
"

# Remove unused packages
rm -rf node_modules

# Other than `chia-blockchain-gui/package/gui`, all other packages are no longer necessary after build.
# Since these unused packages make cache unnecessarily fat, here unused packages are removed.
echo "Remove unused @chia-network packages to make cache slim"
ls -l packages
rm -rf packages/api
rm -rf packages/api-react
rm -rf packages/core
rm -rf packages/icons
rm -rf packages/wallets

# Remove unused fat npm modules from the gui package
cd ./packages/gui/node_modules || exit 1
echo "Remove unused node_modules in the gui package to make cache slim more"
rm -rf electron/dist # ~186MB
rm -rf "@mui"        # ~71MB
rm -rf typescript    # ~63MB

# Remove `packages/gui/node_modules/@chia-network` to save cache space
rm -rf "@chia-network"
