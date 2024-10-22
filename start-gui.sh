#!/bin/bash

set -o errexit

export NODE_OPTIONS="--max-old-space-size=3000"

SCRIPT_DIR=$(
  cd -- "$(dirname -- "$0")"
  pwd
)

echo "### Checking GUI dependencies"

if [ -d "${SCRIPT_DIR}/.n" ]; then
  export N_PREFIX="${SCRIPT_DIR}/.n"
  export PATH="${N_PREFIX}/bin:${PATH}"
  echo "Loading nodejs/npm from"
  echo "  ${N_PREFIX}"
fi

if [ -z "$VIRTUAL_ENV" ]; then
  echo "This requires the chia python virtual environment."
  echo "Execute '. ./activate' before running."
  exit 1
fi

if ! npm version >/dev/null 2>&1; then
  echo "Please install GUI dependencies by:"
  echo "  sh install-gui.sh"
  echo "on ${SCRIPT_DIR}"
  exit 1
fi

NPM_VERSION="$(npm -v | cut -d'.' -f 1)"
if [ "$NPM_VERSION" -lt "9" ]; then
  echo "Current npm version($(npm -v)) is less than 9. GUI app requires npm>=9."
  exit 1
else
  echo "Found npm $(npm -v)"
fi

echo "### Checking GUI build"
GUI_BUILD_PATH="${SCRIPT_DIR}/chia-blockchain-gui/packages/gui/build/electron/main.js"
if [ ! -e "$GUI_BUILD_PATH" ]; then
  echo "Error: GUI build was not found"
  echo "It is expected at $GUI_BUILD_PATH"
  echo "Please build GUI software by:"
  echo "  sh install-gui.sh"
  exit 1
else
  echo "Found $GUI_BUILD_PATH"
fi

echo "### Starting GUI"
cd "${SCRIPT_DIR}/chia-blockchain-gui/"
echo "npm run electron"
npm run electron
