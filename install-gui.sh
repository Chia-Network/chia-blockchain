#!/bin/bash
set -e
export NODE_OPTIONS="--max-old-space-size=3000"

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")"; pwd)

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

nodejs_is_installed(){
  if ! npm version >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

do_install_npm_locally(){
  NPM_VERSION="$(npm -v | cut -d'.' -f 1)"
  if [ "$NPM_VERSION" -lt "7" ]; then
    echo "Current npm version($(npm -v)) is less than 7. GUI app requires npm>=7."

    if [ "$(uname)" = "OpenBSD" ] || [ "$(uname)" = "FreeBSD" ]; then
      # `n` package does not support OpenBSD/FreeBSD
      echo "Please install npm>=7 manually"
      exit 1
    fi

    NPM_GLOBAL="${SCRIPT_DIR}/build_scripts/npm_global"
    # install-gui.sh can be executed
    echo "cd ${NPM_GLOBAL}"
    cd "${NPM_GLOBAL}"
    if [ "$NPM_VERSION" -lt "6" ]; then
      # Ubuntu image of Amazon ec2 instance surprisingly uses nodejs@3.5.2
      # which doesn't support `npm ci` as of 27th Jan, 2022
      echo "npm install"
      npm install
    else
      echo "npm ci"
      npm ci
    fi
    export N_PREFIX=${SCRIPT_DIR}/.n
    PATH="${N_PREFIX}/bin:$(npm bin):${PATH}"
    export PATH
    # `n 16` here installs nodejs@16 under $N_PREFIX directory
    echo "n 16"
    n 16
    echo "Current npm version: $(npm -v)"
    if [ "$(npm -v | cut -d'.' -f 1)" -lt "7" ]; then
      echo "Error: Failed to install npm>=7"
      exit 1
    fi
    cd "${SCRIPT_DIR}"
  else
    echo "Found npm $(npm -v)"
  fi
}

# Manage npm and other install requirements on an OS specific basis
if [ "$(uname)" = "Linux" ]; then
  #LINUX=1
  if type apt-get >/dev/null 2>&1; then
    # Debian/Ubuntu

    # Check if we are running a Raspberry PI 4
    if [ "$(uname -m)" = "aarch64" ] \
    && [ "$(uname -n)" = "raspberrypi" ]; then
      # Check if NodeJS & NPM is installed
      type npm >/dev/null 2>&1 || {
          echo >&2 "Please install NODEJS&NPM manually"
      }
    else
      if ! nodejs_is_installed; then
        echo "nodejs is not installed. Installing..."
        echo "sudo apt-get install -y npm nodejs libxss1"
        sudo apt-get install -y npm nodejs libxss1
      fi
      do_install_npm_locally
    fi
  elif type yum >/dev/null 2>&1 &&  [ ! -f "/etc/redhat-release" ] && [ ! -f "/etc/centos-release" ] && [ ! -f /etc/rocky-release ] && [ ! -f /etc/fedora-release ]; then
    # AMZN 2
    if ! nodejs_is_installed; then
      echo "Installing nodejs on Amazon Linux 2."
      curl -sL https://rpm.nodesource.com/setup_12.x | sudo bash -
      sudo yum install -y nodejs
    fi
    do_install_npm_locally
  elif type yum >/dev/null 2>&1 && [ ! -f /etc/rocky-release ] && [ ! -f /etc/fedora-release ] && [ -f /etc/redhat-release ] || [ -f /etc/centos-release ]; then
    # CentOS or Redhat
    if ! nodejs_is_installed; then
      echo "Installing nodejs on CentOS/Redhat."
      curl -sL https://rpm.nodesource.com/setup_12.x | sudo bash -
      sudo yum install -y nodejs
    fi
    do_install_npm_locally
  elif type yum >/dev/null 2>&1 && [ -f /etc/rocky-release ] || [ -f /etc/fedora-release ]; then
    # RockyLinux
    if ! nodejs_is_installed; then
      echo "Installing nodejs on RockyLinux/Fedora"
      sudo dnf module enable nodejs:12
      sudo dnf install -y nodejs
    fi
    do_install_npm_locally
  fi
elif [ "$(uname)" = "Darwin" ] && type brew >/dev/null 2>&1; then
  # MacOS
  if ! nodejs_is_installed; then
    echo "Installing nodejs on MacOS"
    brew install npm
  fi
  do_install_npm_locally
elif [ "$(uname)" = "OpenBSD" ]; then
  if ! nodejs_is_installed; then
    echo "Installing nodejs"
    pkg_add node
  fi
  do_install_npm_locally
elif [ "$(uname)" = "FreeBSD" ]; then
  if ! nodejs_is_installed; then
    echo "Installing nodejs"
    pkg install node
  fi
  do_install_npm_locally
fi

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

  if [ "$SUBMODULE_BRANCH" ];
  then
    git fetch
    git checkout "$SUBMODULE_BRANCH"
    git pull
    echo ""
    echo "Building the GUI with branch $SUBMODULE_BRANCH"
    echo ""
  fi

  npm ci
  npm audit fix || true
  npm run build
  python ../installhelper.py
else
  echo "Skipping node.js in install.sh on MacOS ci."
fi

echo ""
echo "Chia blockchain install-gui.sh completed."
echo ""
echo "Type 'bash start-gui.sh &' to start the GUI."
