#!/bin/bash
set -e

rm -rf __pycache__
rm -rf chinilla_blockchain.egg-info
rm -rf venv
rm -rf activate
rm -rf chinilla-blockchain-gui/build
rm -rf chinilla-blockchain-gui/node_modules
rm -rf chinilla-blockchain-gui/packages/api/node_modules
rm -rf chinilla-blockchain-gui/packages/api/dist
rm -rf chinilla-blockchain-gui/packages/api-react/node_modules
rm -rf chinilla-blockchain-gui/packages/api-react/dist
rm -rf chinilla-blockchain-gui/packages/core/node_modules
rm -rf chinilla-blockchain-gui/packages/core/dist
rm -rf chinilla-blockchain-gui/packages/gui/node_modules
rm -rf chinilla-blockchain-gui/packages/gui/build
rm -rf chinilla-blockchain-gui/packages/icons/node_modules
rm -rf chinilla-blockchain-gui/packages/icons/dist
rm -rf chinilla-blockchain-gui/packages/wallet/node_modules
rm -rf chinilla-blockchain-gui/packages/wallet/build
rm -rf chinilla-blockchain-gui/packages/wallets/node_modules
rm -rf chinilla-blockchain-gui/packages/wallets/dist

echo "Virtual environment has been scrubbed."
