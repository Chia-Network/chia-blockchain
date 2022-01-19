#!/bin/bash
set -e

rm -rf __pycache__
rm -rf chinilla_blockchain.egg-info
rm -rf venv
rm -rf activate
rm -rf chinilla-blockchain-gui/build
rm -rf chinilla-blockchain-gui/node_modules

echo "Virtual environment has been scrubbed."