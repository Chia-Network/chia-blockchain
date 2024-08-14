#!/bin/bash

set -o errexit

USAGE_TEXT="\
Usage: $0 [-adilpsh]

  -a                          ignored for compatibility with earlier versions
  -d                          install development dependencies
  -i                          install non-editable
  -l                          install legacy keyring dependencies (linux only)
  -p                          additional plotters installation
  -s                          ignored for compatibility with earlier versions
  -h                          display this help and exit
"

usage() {
  echo "${USAGE_TEXT}"
}

EXTRAS='--extras upnp'
PLOTTER_INSTALL=
EDITABLE=1

while getopts adilpsh flag; do
  case "${flag}" in
  # automated
  a) : ;;
  # development
  d) EXTRAS="${EXTRAS} --extras dev" ;;
  # non-editable
  i) EDITABLE= ;;
  # legacy keyring
  l) EXTRAS="${EXTRAS} --extras legacy-keyring" ;;
  p) PLOTTER_INSTALL=1 ;;
  # simple install
  s) : ;;
  h)
    usage
    exit 0
    ;;
  *)
    echo
    usage
    exit 1
    ;;
  esac
done

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
  for V in 312 3.12 311 3.11 310 3.10 39 3.9 38 3.8 3; do
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

if [ "$PYTHON_MAJOR_VER" -ne "3" ] || [ "$PYTHON_MINOR_VER" -lt "7" ] || [ "$PYTHON_MINOR_VER" -ge "13" ]; then
  echo "Chia requires Python version >= 3.8 and  < 3.13.0" >&2
  echo "Current Python version = $INSTALL_PYTHON_VERSION" >&2
  # If Arch, direct to Arch Wiki
  if type pacman >/dev/null 2>&1 && [ -f "/etc/arch-release" ]; then
    echo "Please see https://wiki.archlinux.org/title/python#Old_versions for support." >&2
  else
    echo "Please install python per your OS instructions." >&2
  fi

  exit 1
fi
echo "Python version is $INSTALL_PYTHON_VERSION"

find_sqlite
echo "SQLite version for Python is ${SQLITE_VERSION}"
if [ "$SQLITE_MAJOR_VER" -lt "3" ] || [ "$SQLITE_MAJOR_VER" = "3" ] && [ "$SQLITE_MINOR_VER" -lt "8" ]; then
  echo "Only sqlite>=3.8 is supported"
  echo "Please install sqlite3 per your OS instructions."
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

./setup-poetry.sh -c "${INSTALL_PYTHON_PATH}"
.penv/bin/poetry env use "${INSTALL_PYTHON_PATH}"
# shellcheck disable=SC2086
.penv/bin/poetry install ${EXTRAS}
ln -s -f .venv venv
if [ ! -f "activate" ]; then
  ln -s venv/bin/activate .
fi

if [ -z "$EDITABLE" ]; then
  .venv/bin/python -m pip install --no-deps .
fi

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
echo "https://docs.chia.net/introduction"
echo ""
echo "To install the GUI run '. ./activate' then 'sh install-gui.sh'."
echo ""
echo "Type '. ./activate' and then 'chia init' to begin."
