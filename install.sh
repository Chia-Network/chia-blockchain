#!/bin/bash

set -o errexit

USAGE_TEXT="\
Usage: $0 [-d]

  -a                          automated install, no questions
  -d                          install development dependencies
  -h                          display this help and exit
"

usage() {
  echo "${USAGE_TEXT}"
}

PACMAN_AUTOMATED=
EXTRAS=

while getopts adh flag
do
  case "${flag}" in
    # automated
    a) PACMAN_AUTOMATED=--noconfirm;;
    # development
    d) EXTRAS=${EXTRAS}dev,;;
    h) usage; exit 0;;
    *) echo; usage; exit 1;;
  esac
done

UBUNTU=false
DEBIAN=false
if [ "$(uname)" = "Linux" ]; then
  #LINUX=1
  if command -v apt-get >/dev/null; then
    OS_ID=$(lsb_release -is)
    if [ "$OS_ID" = "Debian" ]; then
      DEBIAN=true
    else
      UBUNTU=true
    fi
  fi
fi

# Check for non 64 bit ARM64/Raspberry Pi installs
if [ "$(uname -m)" = "armv7l" ]; then
  echo ""
  echo "WARNING:"
  echo "The Chia Blockchain requires a 64 bit OS and this is 32 bit armv7l"
  echo "For more information, see"
  echo "https://github.com/Chia-Network/chia-blockchain/wiki/Raspberry-Pi"
  echo "Exiting."
  exit 1
fi
# Get submodules
git submodule update --init mozilla-ca

UBUNTU_PRE_2004=false
if $UBUNTU; then
  LSB_RELEASE=$(lsb_release -rs)
  # In case Ubuntu minimal does not come with bc
  if ! command -v bc > /dev/null 2>&1; then
    sudo apt install bc -y
  fi
  # Mint 20.04 responds with 20 here so 20 instead of 20.04
  UBUNTU_PRE_2004=$(echo "$LSB_RELEASE<20" | bc)
  UBUNTU_2100=$(echo "$LSB_RELEASE>=21" | bc)
fi

install_python3_and_sqlite3_from_source_with_yum() {
  CURRENT_WD=$(pwd)
  TMP_PATH=/tmp

  # Preparing installing Python
  echo 'yum groupinstall -y "Development Tools"'
  sudo yum groupinstall -y "Development Tools"
  echo "sudo yum install -y openssl-devel openssl libffi-devel bzip2-devel wget"
  sudo yum install -y openssl-devel openssl libffi-devel bzip2-devel wget

  echo "cd $TMP_PATH"
  cd "$TMP_PATH"
  # Install sqlite>=3.37
  # yum install sqlite-devel brings sqlite3.7 which is not compatible with chia
  echo "wget https://www.sqlite.org/2022/sqlite-autoconf-3370200.tar.gz"
  wget https://www.sqlite.org/2022/sqlite-autoconf-3370200.tar.gz
  tar xf sqlite-autoconf-3370200.tar.gz
  echo "cd sqlite-autoconf-3370200"
  cd sqlite-autoconf-3370200
  echo "./configure --prefix=/usr/local"
  # '| stdbuf ...' seems weird but this makes command outputs stay in single line.
  ./configure --prefix=/usr/local | stdbuf -o0 cut -b1-"$(tput cols)" | sed -u 'i\\o033[2K' | stdbuf -o0 tr '\n' '\r'; echo
  echo "make -j$(nproc)"
  make -j"$(nproc)" | stdbuf -o0 cut -b1-"$(tput cols)" | sed -u 'i\\o033[2K' | stdbuf -o0 tr '\n' '\r'; echo
  echo "sudo make install"
  sudo make install | stdbuf -o0 cut -b1-"$(tput cols)" | sed -u 'i\\o033[2K' | stdbuf -o0 tr '\n' '\r'; echo
  # yum install python3 brings Python3.6 which is not supported by chia
  cd ..
  echo "wget https://www.python.org/ftp/python/3.9.11/Python-3.9.11.tgz"
  wget https://www.python.org/ftp/python/3.9.11/Python-3.9.11.tgz
  tar xf Python-3.9.11.tgz
  echo "cd Python-3.9.11"
  cd Python-3.9.11
  echo "LD_RUN_PATH=/usr/local/lib ./configure --prefix=/usr/local"
  # '| stdbuf ...' seems weird but this makes command outputs stay in single line.
  LD_RUN_PATH=/usr/local/lib ./configure --prefix=/usr/local | stdbuf -o0 cut -b1-"$(tput cols)" | sed -u 'i\\o033[2K' | stdbuf -o0 tr '\n' '\r'; echo
  echo "LD_RUN_PATH=/usr/local/lib make -j$(nproc)"
  LD_RUN_PATH=/usr/local/lib make -j"$(nproc)" | stdbuf -o0 cut -b1-"$(tput cols)" | sed -u 'i\\o033[2K' | stdbuf -o0 tr '\n' '\r'; echo
  echo "LD_RUN_PATH=/usr/local/lib sudo make altinstall"
  LD_RUN_PATH=/usr/local/lib sudo make altinstall | stdbuf -o0 cut -b1-"$(tput cols)" | sed -u 'i\\o033[2K' | stdbuf -o0 tr '\n' '\r'; echo
  cd "$CURRENT_WD"
}

# Manage npm and other install requirements on an OS specific basis
if [ "$(uname)" = "Linux" ]; then
  #LINUX=1
  if [ "$UBUNTU" = "true" ] && [ "$UBUNTU_PRE_2004" = "1" ]; then
    # Ubuntu
    echo "Installing on Ubuntu pre 20.04 LTS."
    sudo apt-get update
    sudo apt-get install -y python3.7-venv python3.7-distutils openssl
  elif [ "$UBUNTU" = "true" ] && [ "$UBUNTU_PRE_2004" = "0" ] && [ "$UBUNTU_2100" = "0" ]; then
    echo "Installing on Ubuntu 20.04 LTS."
    sudo apt-get update
    sudo apt-get install -y python3.8-venv python3-distutils openssl
  elif [ "$UBUNTU" = "true" ] && [ "$UBUNTU_2100" = "1" ]; then
    echo "Installing on Ubuntu 21.04 or newer."
    sudo apt-get update
    sudo apt-get install -y python3.9-venv python3-distutils openssl
  elif [ "$DEBIAN" = "true" ]; then
    echo "Installing on Debian."
    sudo apt-get update
    sudo apt-get install -y python3-venv openssl
  elif type pacman >/dev/null 2>&1 && [ -f "/etc/arch-release" ]; then
    # Arch Linux
    # Arch provides latest python version. User will need to manually install python 3.9 if it is not present
    echo "Installing on Arch Linux."
    case $(uname -m) in
      x86_64|aarch64)
        sudo pacman ${PACMAN_AUTOMATED} -S --needed git openssl
        ;;
      *)
        echo "Incompatible CPU architecture. Must be x86_64 or aarch64."
        exit 1
        ;;
    esac
  elif type yum >/dev/null 2>&1 && [ ! -f "/etc/redhat-release" ] && [ ! -f "/etc/centos-release" ] && [ ! -f "/etc/fedora-release" ]; then
    # AMZN 2
    echo "Installing on Amazon Linux 2."
    if ! command -v python3.9 >/dev/null 2>&1; then
      install_python3_and_sqlite3_from_source_with_yum
    fi
  elif type yum >/dev/null 2>&1 && [ -f "/etc/centos-release" ]; then
    # CentOS
    echo "Install on CentOS."
    if ! command -v python3.9 >/dev/null 2>&1; then
      install_python3_and_sqlite3_from_source_with_yum
    fi
  elif type yum >/dev/null 2>&1 && [ -f "/etc/redhat-release" ] && grep Rocky /etc/redhat-release; then
    echo "Installing on Rocky."
    # TODO: make this smarter about getting the latest version
    sudo yum install --assumeyes python39 openssl
  elif type yum >/dev/null 2>&1 && [ -f "/etc/redhat-release" ] || [ -f "/etc/fedora-release" ]; then
    # Redhat or Fedora
    echo "Installing on Redhat/Fedora."
    if ! command -v python3.9 >/dev/null 2>&1; then
      sudo yum install -y python39 openssl
    fi
  fi
elif [ "$(uname)" = "Darwin" ]; then
  echo "Installing on macOS."
  if ! type brew >/dev/null 2>&1; then
    echo "Installation currently requires brew on macOS - https://brew.sh/"
    exit 1
  fi
  echo "Installing OpenSSL"
  brew install openssl
elif [ "$(uname)" = "OpenBSD" ]; then
  export MAKE=${MAKE:-gmake}
  export BUILD_VDF_CLIENT=${BUILD_VDF_CLIENT:-N}
elif [ "$(uname)" = "FreeBSD" ]; then
  export MAKE=${MAKE:-gmake}
  export BUILD_VDF_CLIENT=${BUILD_VDF_CLIENT:-N}
fi

find_python() {
  set +e
  unset BEST_VERSION
  for V in 310 3.10 39 3.9 38 3.8 37 3.7 3; do
    if command -v python$V >/dev/null; then
      if [ "$BEST_VERSION" = "" ]; then
        BEST_VERSION=$V
        if [ "$BEST_VERSION" = "3" ]; then
          PY3_VERSION=$(python$BEST_VERSION --version | cut -d ' ' -f2)
          if [[ "$PY3_VERSION" =~ 3.11.* ]]; then
            echo "Chia requires Python version < 3.11.0"
            echo "Current Python version = $PY3_VERSION"
            # If Arch, direct to Arch Wiki
            if type pacman >/dev/null 2>&1 && [ -f "/etc/arch-release" ]; then
              echo "Please see https://wiki.archlinux.org/title/python#Old_versions for support."
            fi
            exit 1
          fi
        fi
      fi
    fi
  done
  echo $BEST_VERSION
  set -e
}

if [ "$INSTALL_PYTHON_VERSION" = "" ]; then
  INSTALL_PYTHON_VERSION=$(find_python)
fi

# This fancy syntax sets INSTALL_PYTHON_PATH to "python3.7", unless
# INSTALL_PYTHON_VERSION is defined.
# If INSTALL_PYTHON_VERSION equals 3.8, then INSTALL_PYTHON_PATH becomes python3.8

INSTALL_PYTHON_PATH=python${INSTALL_PYTHON_VERSION:-3.7}

if ! command -v "$INSTALL_PYTHON_PATH" >/dev/null; then
  echo "${INSTALL_PYTHON_PATH} was not found"
  exit 1
fi

echo "Python version is $INSTALL_PYTHON_VERSION"

# Check sqlite3 version bound to python
SQLITE_VERSION=$($INSTALL_PYTHON_PATH -c 'import sqlite3; print(sqlite3.sqlite_version)')
SQLITE_MAJOR_VER=$(echo "$SQLITE_VERSION" | cut -d'.' -f1)
SQLITE_MINOR_VER=$(echo "$SQLITE_VERSION" | cut -d'.' -f2)
echo "SQLite version for Python is ${SQLITE_VERSION}"
if [ "$SQLITE_MAJOR_VER" -lt "3" ] || [ "$SQLITE_MAJOR_VER" = "3" ] && [ "$SQLITE_MINOR_VER" -lt "8" ]; then
  echo "Only sqlite>=3.8 is supported"
  exit 1
fi

# Check openssl version python will use
OPENSSL_VERSION_STRING=$($INSTALL_PYTHON_PATH -c 'import ssl; print(ssl.OPENSSL_VERSION)')
OPENSSL_VERSION_INT=$($INSTALL_PYTHON_PATH -c 'import ssl; print(ssl.OPENSSL_VERSION_NUMBER)')
# There is also ssl.OPENSSL_VERSION_INFO returning a tuple
# 1.1.1n corresponds to 269488367 as an integer
echo "OpenSSL version for Python is ${OPENSSL_VERSION_STRING}"
if [ "$OPENSSL_VERSION_INT" -lt "269488367" ]; then
  echo "WARNING: OpenSSL versions before 3.0.2, 1.1.1n, or 1.0.2zd are vulnerable to CVE-2022-0778"
  echo "Your OS may have patched OpenSSL and not updated the version to 1.1.1n"
fi

# If version of `python` and "$INSTALL_PYTHON_VERSION" does not match, clear old version
VENV_CLEAR=""
if [ -e venv/bin/python ]; then
  VENV_PYTHON_VER=$(venv/bin/python -V)
  TARGET_PYTHON_VER=$($INSTALL_PYTHON_PATH -V)
  if [ "$VENV_PYTHON_VER" != "$TARGET_PYTHON_VER" ]; then
    echo "existing python version in venv is $VENV_PYTHON_VER while target python version is $TARGET_PYTHON_VER"
    echo "Refreshing venv modules..."
    VENV_CLEAR="--clear"
  fi
fi

$INSTALL_PYTHON_PATH -m venv venv $VENV_CLEAR
if [ ! -f "activate" ]; then
  ln -s venv/bin/activate .
fi

EXTRAS=${EXTRAS%,}
if [ -n "${EXTRAS}" ]; then
  EXTRAS=[${EXTRAS}]
fi

# shellcheck disable=SC1091
. ./activate
# pip 20.x+ supports Linux binary wheels
python -m pip install --upgrade pip
python -m pip install wheel
#if [ "$INSTALL_PYTHON_VERSION" = "3.8" ]; then
# This remains in case there is a diversion of binary wheels
python -m pip install --extra-index-url https://pypi.chia.net/simple/ miniupnpc==2.2.2
python -m pip install -e ."${EXTRAS}" --extra-index-url https://pypi.chia.net/simple/

echo ""
echo "Chia blockchain install.sh complete."
echo "For assistance join us on Keybase in the #support chat channel:"
echo "https://keybase.io/team/chia_network.public"
echo ""
echo "Try the Quick Start Guide to running chia-blockchain:"
echo "https://github.com/Chia-Network/chia-blockchain/wiki/Quick-Start-Guide"
echo ""
echo "To install the GUI type 'sh install-gui.sh' after '. ./activate'."
echo ""
echo "Type '. ./activate' and then 'chia init' to begin."
