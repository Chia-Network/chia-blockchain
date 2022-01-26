#!/bin/bash
set -e
export NODE_OPTIONS="--max-old-space-size=3000"

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")

if [ -d  "${SCRIPT_DIR}/.n" ]; then
  export N_PREFIX="${SCRIPT_DIR}/.n"
  export PATH="${N_PREFIX}/bin:${PATH}"
fi

if ! npm version >/dev/null 2>&1; then
  echo "Please install GUI dependencies by:"
  echo "  sh install-gui.sh"
  echo "on ${SCRIPT_DIR}"
  exit 1
fi

NPM_VERSION="$(npm -v | cut -d'.' -f 1)"
if [ "$NPM_VERSION" -lt "7" ]; then
  echo "Current npm version($(npm -v)) is less than 7. GUI app requires npm>=7."
  exit 1
fi

cd "${SCRIPT_DIR}/chia-blockchain-gui/"
npm run electron
