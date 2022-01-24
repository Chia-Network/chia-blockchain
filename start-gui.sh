#!/bin/bash
set -e
export NODE_OPTIONS="--max-old-space-size=3000"

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
export N_PREFIX="${SCRIPT_DIR}/.n"

cd "${SCRIPT_DIR}/chia-blockchain-gui/"
npm run electron
