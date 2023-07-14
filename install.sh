#!/bin/bash

set -o errexit

USAGE_TEXT="\
Usage: $0 [-adlsph]

  -a                          automated install, no questions
  -d                          install development dependencies
  -l                          install legacy keyring dependencies (linux only)
  -s                          skip python package installation and just do pip install
  -p                          additional plotters installation
  -h                          display this help and exit
"

usage() {
  echo "${USAGE_TEXT}"
}

PACMAN_AUTOMATED=
EXTRAS=
SKIP_PACKAGE_INSTALL=
PLOTTER_INSTALL=

while getopts adlsph flag
do
  case "${flag}" in
    # automated
    a) PACMAN_AUTOMATED=--noconfirm;;
    # development
    d) EXTRAS=${EXTRAS}dev,;;
    # simple install
    s) SKIP_PACKAGE_INSTALL=1;;
    p) PLOTTER_INSTALL=1;;
    # legacy keyring
    l) EXTRAS=${EXTRAS}legacy_keyring,;;
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

UBUNTU_PRE_20=0
UBUNTU_20=0
UBUNTU_21=0
UBUNTU_22=0

if $UBUNTU; then
  LSB_RELEASE=$(lsb_release -rs)
  # In case Ubuntu minimal does not come with bc
  if ! command -v bc > /dev/null 2>&1; then
    sudo apt install bc -y
  fi
  # Mint 20.04 responds with 20 here so 20 instead of 20.04
  if [ "$(echo "$LSB_RELEASE<20" | bc)" = "1" ]; then
    UBUNTU_PRE_20=1
  elif [ "$(echo "$LSB_RELEASE<21" | bc)" = "1" ]; then
    UBUNTU_20=1
  elif [ "$(echo "$LSB_RELEASE<22" | bc)" = "1" ]; then
    UBUNTU_21=1
  else
    UBUNTU_22=1
  fi
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

# You can specify preferred python version by exporting `INSTALL_PYTHON_VERSION`
# e.g. `export INSTALL_PYTHON_VERSION=3.8`
INSTALL_PYTHON_PATH=
PYTHON_MAJOR_VER=
PYTHON_MINOR_VER=
SQLITE_VERSION=
SQLITE_MAJOR_VER=
SQLITE_MINOR_VER=
OPENSSL_VERSION_STRING=
OPENSSL_VERSION_INT=

find_python() {
  set +e
  unset BEST_VERSION
  for V in 311 3.11 310 3.10 39 3.9 38 3.8 37 3.7 3; do
    if command -v python$V >/dev/null; then
      if [ "$BEST_VERSION" = "" ]; then
        BEST_VERSION=$V
      fi
    fi
  done

  if [ -n "$BEST_VERSION" ]; then
    INSTALL_PYTHON_VERSION="$BEST_VERSION"
    INSTALL_PYTHON_PATH=python${INSTALL_PYTHON_VERSION}
    PY3_VER=$($INSTALL_PYTHON_PATH --version | cut -d ' ' -f2)
    PYTHON_MAJOR_VER=$(echo "$PY3_VER" | cut -d'.' -f1)
    PYTHON_MINOR_VER=$(echo "$PY3_VER" | cut -d'.' -f2)
  fi
  set -e
}

find_sqlite() {
  set +e
  if [ -n "$INSTALL_PYTHON_PATH" ]; then
    # Check sqlite3 version bound to python
    SQLITE_VERSION=$($INSTALL_PYTHON_PATH -c 'import sqlite3; print(sqlite3.sqlite_version)')
    SQLITE_MAJOR_VER=$(echo "$SQLITE_VERSION" | cut -d'.' -f1)
    SQLITE_MINOR_VER=$(echo "$SQLITE_VERSION" | cut -d'.' -f2)
  fi
  set -e
}

find_openssl() {
  set +e
  if [ -n "$INSTALL_PYTHON_PATH" ]; then
    # Check openssl version python will use
    OPENSSL_VERSION_STRING=$($INSTALL_PYTHON_PATH -c 'import ssl; print(ssl.OPENSSL_VERSION)')
    OPENSSL_VERSION_INT=$($INSTALL_PYTHON_PATH -c 'import ssl; print(ssl.OPENSSL_VERSION_NUMBER)')
  fi
  set -e
}

# Manage npm and other install requirements on an OS specific basis
if [ "$SKIP_PACKAGE_INSTALL" = "1" ]; then
  echo "Skipping system package installation"
elif [ "$(uname)" = "Linux" ]; then
  #LINUX=1
  if [ "$UBUNTU_PRE_20" = "1" ]; then
    # Ubuntu
    echo "Installing on Ubuntu pre 20.*."
    sudo apt-get update
    # distutils must be installed as well to avoid a complaint about ensurepip while
    # creating the venv.  This may be related to a mis-check while using or
    # misconfiguration of the secondary Python version 3.7.  The primary is Python 3.6.
    sudo apt-get install -y python3.7-venv python3.7-distutils openssl
  elif [ "$UBUNTU_20" = "1" ]; then
    echo "Installing on Ubuntu 20.*."
    sudo apt-get update
    sudo apt-get install -y python3.8-venv openssl
  elif [ "$UBUNTU_21" = "1" ]; then
    echo "Installing on Ubuntu 21.*."
    sudo apt-get update
    sudo apt-get install -y python3.9-venv openssl
  elif [ "$UBUNTU_22" = "1" ]; then
    echo "Installing on Ubuntu 22.* or newer."
    sudo apt-get update
    sudo apt-get install -y python3.10-venv openssl
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
fi

if [ "$(uname)" = "OpenBSD" ]; then
  export MAKE=${MAKE:-gmake}
  export BUILD_VDF_CLIENT=${BUILD_VDF_CLIENT:-N}
elif [ "$(uname)" = "FreeBSD" ]; then
  export MAKE=${MAKE:-gmake}
  export BUILD_VDF_CLIENT=${BUILD_VDF_CLIENT:-N}
fi

if [ "$INSTALL_PYTHON_VERSION" = "" ]; then
  echo "Searching available python executables..."
  find_python
else
  echo "Python $INSTALL_PYTHON_VERSION is requested"
  INSTALL_PYTHON_PATH=python${INSTALL_PYTHON_VERSION}
  PY3_VER=$($INSTALL_PYTHON_PATH --version | cut -d ' ' -f2)
  PYTHON_MAJOR_VER=$(echo "$PY3_VER" | cut -d'.' -f1)
  PYTHON_MINOR_VER=$(echo "$PY3_VER" | cut -d'.' -f2)
fi

if ! command -v "$INSTALL_PYTHON_PATH" >/dev/null; then
  echo "${INSTALL_PYTHON_PATH} was not found"
  exit 1
fi

if [ "$PYTHON_MAJOR_VER" -ne "3" ] || [ "$PYTHON_MINOR_VER" -lt "7" ] || [ "$PYTHON_MINOR_VER" -ge "12" ]; then
  echo "Chia requires Python version >= 3.7 and  < 3.12.0" >&2
  echo "Current Python version = $INSTALL_PYTHON_VERSION" >&2
  # If Arch, direct to Arch Wiki
  if type pacman >/dev/null 2>&1 && [ -f "/etc/arch-release" ]; then
    echo "Please see https://wiki.archlinux.org/title/python#Old_versions for support." >&2
  fi

  exit 1
fi
echo "Python version is $INSTALL_PYTHON_VERSION"

find_sqlite
echo "SQLite version for Python is ${SQLITE_VERSION}"
if [ "$SQLITE_MAJOR_VER" -lt "3" ] || [ "$SQLITE_MAJOR_VER" = "3" ] && [ "$SQLITE_MINOR_VER" -lt "8" ]; then
  echo "Only sqlite>=3.8 is supported"
  exit 1
fi

# There is also ssl.OPENSSL_VERSION_INFO returning a tuple
# 1.1.1n corresponds to 269488367 as an integer
find_openssl
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

if [ -n "$PLOTTER_INSTALL" ]; then
  set +e
  PREV_VENV="$VIRTUAL_ENV"
  export VIRTUAL_ENV="venv"
  ./install-plotter.sh bladebit
  ./install-plotter.sh madmax
  export VIRTUAL_ENV="$PREV_VENV"
  set -e
fi

echo ""
echo "Chia blockchain install.sh complete."
echo "For assistance join us on Discord in the #support chat channel:"
echo "https://discord.gg/chia"
echo ""
echo "Try the Quick Start Guide to running chia-blockchain:"
echo "https://github.com/Chia-Network/chia-blockchain/wiki/Quick-Start-Guide"
echo ""
echo "To install the GUI run '. ./activate' then 'sh install-gui.sh'."
echo ""
echo "Type '. ./activate' and then 'chia init' to begin."
