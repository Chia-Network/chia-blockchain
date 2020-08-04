#!/bin/bash
set -e

find_python() {
    set +e
    unset BEST_VERSION
    for V in 37 3.7 38 3.8 3
    do
        if which python$V > /dev/null
        then
            if [ x"$BEST_VERSION" = x ]
            then
                BEST_VERSION=$V
            fi
        fi
    done
    echo $BEST_VERSION
    set -e
}

if [ x"$INSTALL_PYTHON_VERSION" = x ]
then
  INSTALL_PYTHON_VERSION=$(find_python)
fi

UBUNTU=false
# Manage npm and other install requirements on an OS specific basis
if [ "$(uname)" = "Linux" ]; then
  #LINUX=1
  if type apt-get; then
    # Debian/Ubuntu
    UBUNTU=true
    sudo apt-get install -y npm nodejs
  elif type yum && [ ! -f "/etc/redhat-release" ] && [ ! -f "/etc/centos-release" ]; then
    # AMZN 2
    echo "Installing on Amazon Linux 2"
    sudo yum install -y python3 git
    curl -sL https://rpm.nodesource.com/setup_10.x | sudo bash -
    sudo yum install -y nodejs
  elif type yum && [ -f /etc/redhat-release ] || [ -f /etc/centos-release ]; then
    # CentOS or Redhat
    echo "Installing on CentOS/Redhat"
    curl -sL https://rpm.nodesource.com/setup_10.x | sudo bash -
    sudo yum install -y nodejs
  fi
elif [ "$(uname)" = "Darwin" ] && type brew && ! npm version>/dev/null 2>&1; then
  # Install npm if not installed
  brew install npm
elif [ "$(uname)" = "Darwin" ] && ! type brew >/dev/null 2>&1; then
  echo "Installation currently requires brew on MacOS - https://brew.sh/"
elif [ "$(uname)" = "OpenBSD" ]; then
  export MAKE=${MAKE:-gmake}
  export BUILD_VDF_CLIENT=${BUILD_VDF_CLIENT:-N}
elif [ "$(uname)" = "FreeBSD" ]; then
  export MAKE=${MAKE:-gmake}
  export BUILD_VDF_CLIENT=${BUILD_VDF_CLIENT:-N}
fi

# this fancy syntax sets INSTALL_PYTHON_PATH to "python3.7" unless INSTALL_PYTHON_VERSION is defined
# if INSTALL_PYTHON_VERSION=3.8, then INSTALL_PYTHON_PATH becomes python3.8

INSTALL_PYTHON_PATH=python${INSTALL_PYTHON_VERSION:-3.7}

$INSTALL_PYTHON_PATH -m venv venv
if [ ! -f "activate" ]; then
    ln -s venv/bin/activate .
fi
echo "Python version is $INSTALL_PYTHON_VERSION"
# shellcheck disable=SC1091
. ./activate
# pip 20.x+ supports Linux binary wheels
pip install --upgrade pip
pip install wheel
#if [ "$INSTALL_PYTHON_VERSION" = "3.8" ]; then
# This remains in case there is a diversion of binary wheels
pip install --extra-index-url https://download.chia.net/simple/ miniupnpc==2.1 setproctitle==1.1.10 cbor2==5.1.2
pip install -e .

# Ubuntu before 20.04LTS has an ancient node.js
echo ""
UBUNTU_PRE_2004=false
if $UBUNTU; then
  UBUNTU_PRE_2004=$(python -c 'import subprocess; process = subprocess.run(["lsb_release", "-rs"], stdout=subprocess.PIPE); print(float(process.stdout) < float(20.04))')
fi

if [ "$UBUNTU_PRE_2004" = "True" ]; then
  echo "Installing on Ubuntu older than 20.04 LTS: Ugrading node.js to stable"
  UBUNTU_PRE_2004=true  # Unfortunately Python returns True when shell expects true
  sudo npm install -g n
  sudo n stable
  export PATH="$PATH"
fi

if [ "$UBUNTU" = "true" ] && [ "$UBUNTU_PRE_2004" = "False" ]; then
  echo "Installing on Ubuntu 20.04 LTS or newer: Using installed node.js version"
fi

# We will set up node.js on GitHub Actions and Azure Pipelines directly
# for Mac and Windows so skip unless completing a source/developer install
# Ubuntu special cases above
if [ ! "$CI" ]; then
  cd ./electron-react
  npm install
  npm audit fix
else
  echo "Skipping node.js in install.sh on MacOS ci"
fi

echo ""
echo "Chia blockchain install.sh complete."
echo "For assistance join us on Keybase in the #testnet chat channel"
echo "https://keybase.io/team/chia_network.public"
echo ""
echo "Try the Quick Start Guide to running chia-blockchain"
echo "https://github.com/Chia-Network/chia-blockchain/wiki/Quick-Start-Guide"
echo ""
echo "Type '. ./activate' and then 'chia init' to begin"
