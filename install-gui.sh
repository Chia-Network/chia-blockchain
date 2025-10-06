#!/usr/bin/env bash

set -o errexit

export NODE_OPTIONS="--max-old-space-size=3000"

SCRIPT_DIR=$(
  cd -- "$(dirname -- "$0")"
  pwd
)

if [ "${SCRIPT_DIR}" != "$(pwd)" ]; then
  echo "Please change working directory by the command below"
  echo "  cd ${SCRIPT_DIR}"
  exit 1
fi

if [ -z "$VIRTUAL_ENV" ]; then
  echo "This requires the chia python virtual environment."
  echo "Execute '. ./activate' before running."
  exit 1
fi

if [ "$(id -u)" = 0 ]; then
  echo "The Chia Blockchain GUI can not be installed or run by the root user."
  exit 1
fi

# Allows overriding the branch or commit to build in chia-blockchain-gui
SUBMODULE_BRANCH=$1

do_check_npm_install() {
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm is not installed. Please install NodeJS>=20 and npm>=10 manually"
    exit 1
  fi

  if ! command -v node >/dev/null 2>&1; then
    echo "NodeJS is not installed. Please install NodeJS>=20 and npm>=10 manually"
    exit 1
  fi

  NODEJS_VERSION="$(node -v | cut -d'.' -f 1 | sed -e 's/^v//')"
  NPM_VERSION="$(npm -v | cut -d'.' -f 1)"

  if [ "$NODEJS_VERSION" -lt "20" ] || [ "$NPM_VERSION" -lt "10" ]; then
    if [ "$NODEJS_VERSION" -lt "20" ]; then
      echo "Current NodeJS version($(node -v)) is less than 20. GUI app requires NodeJS>=20."
    fi
    if [ "$NPM_VERSION" -lt "10" ]; then
      echo "Current npm version($(npm -v)) is less than 10. GUI app requires npm>=10."
    fi

    echo "Please install NodeJS>=20 and/or npm>=10 manually"
    exit 1
  else
    echo "Found NodeJS $(node -v)"
    echo "Found npm $(npm -v)"
  fi
}

# Work around for inconsistent `npm` exec path issue
# https://github.com/Chia-Network/chia-blockchain/pull/10460#issuecomment-1054492495
patch_inconsistent_npm_issue() {
  node_module_dir=$1
  if [ ! -d "$node_module_dir" ]; then
    mkdir "$node_module_dir"
  fi
  if [ ! -d "${node_module_dir}/.bin" ]; then
    mkdir "${node_module_dir}/.bin"
  fi
  if [ -e "${node_module_dir}/.bin/npm" ]; then
    rm -f "${node_module_dir}/.bin/npm"
  fi
  ln -s "$(command -v npm)" "${node_module_dir}/.bin/npm"
}

do_check_npm_install

echo ""

# For Mac and Windows, we will set up node.js on GitHub Actions and Azure
# Pipelines directly, so skip unless you are completing a source/developer install.
# Ubuntu special cases above.
if [ ! "$CI" ]; then
  echo "Running git submodule update --init --recursive."
  echo ""
  git submodule update --init --recursive
  echo "Running git submodule update."
  echo ""
  git submodule update
  cd chia-blockchain-gui

  if [ "$SUBMODULE_BRANCH" ]; then
    git fetch --all
    git reset --hard "$SUBMODULE_BRANCH"
    echo ""
    echo "Building the GUI with branch $SUBMODULE_BRANCH"
    echo ""
  fi

  # Work around for inconsistent `npm` exec path issue
  # https://github.com/Chia-Network/chia-blockchain/pull/10460#issuecomment-1054492495
  patch_inconsistent_npm_issue "../node_modules"

  npm ci
  npm audit fix || true
  npm run build

  # Set modified output of `chia version` to version property of GUI's package.json
  python ../installhelper.py
else
  echo "Skipping node.js in install.sh on MacOS ci."
fi

echo ""
echo "Chia blockchain install-gui.sh completed."
echo ""
echo "Type 'bash start-gui.sh &' to start the GUI."
