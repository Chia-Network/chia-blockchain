#!/bin/bash
set -e

find_python() {
    set +e
    unset BEST_VERSION
    for V in 37 3.7 38 3.8 3
    do
        which python$V > /dev/null
        if [ $? = 0 ]
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

# Manage npm and other install requirements on an OS specific basis
if [ "$(uname)" = "Linux" ]; then
  #LINUX=1
  if type apt-get; then
    # Debian/Ubuntu
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
fi

# this fancy syntax sets INSTALL_PYTHON_PATH to "python3.7" unless INSTALL_PYTHON_VERSION is defined
# if INSTALL_PYTHON_VERSION=3.8, then INSTALL_PYTHON_PATH becomes python3.8

INSTALL_PYTHON_PATH=python${INSTALL_PYTHON_VERSION:-3.7}

$INSTALL_PYTHON_PATH -m venv venv
if [ ! -f "activate" ]; then
    ln -s venv/bin/activate .
fi
echo "Python version is $INSTALL_PYTHON_VERSION"
. ./activate
# pip 20.x+ supports Linux binary wheels
pip install --upgrade pip
pip install wheel
#if [ "$INSTALL_PYTHON_VERSION" = "3.8" ]; then
# This remains in case there is a diversion of binary wheels
pip install -i https://download.chia.net/simple/ miniupnpc==2.1 setproctitle==1.1.10 cbor2==5.1.0
pip install -e .

cd ./electron-react
npm install

echo ""
echo "Chia blockchain install.sh complete."
echo "For assistance join us on Keybase in the #testnet chat channel"
echo "https://keybase.io/team/chia_network.public"
echo ""
echo "Try the Quick Start Guide to running chia-blockchain"
echo "https://github.com/Chia-Network/chia-blockchain/wiki/Quick-Start-Guide"
echo ""
echo "Type '. ./activate' and then 'chia init' to begin"
