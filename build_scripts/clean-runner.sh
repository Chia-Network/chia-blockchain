#!/bin/bash
# Cleans up files/directories that may be left over from previous runs for a clean slate before starting a new build

rm -rf ../venv || true
rm -rf venv || true
rm -rf chia_blockchain.egg-info || true
rm -rf build_scripts/final_installer || true
rm -rf build_scripts/dist || true
rm -rf build_scripts/pyinstaller || true
rm -rf chia-blockchain-gui/build || true
rm -rf chia-blockchain-gui/daemon || true
rm -rf chia-blockchain-gui/node_modules || true

# Do our best to get rid of any globally installed notarize-cli versions so the version in the current build script is
# installed without conflicting with the other version that might be installed
export PATH=$(brew --prefix node@12)/bin:$PATH || true
npm uninstall -g notarize-cli || true
npm uninstall -g @chia-network/notarize-cli || true
