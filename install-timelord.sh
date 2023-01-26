#!/bin/bash

set -o errexit

USAGE_TEXT="\
Usage: $0 [-d]

  -n                          do not install Python development package, Python.h etc
  -h                          display this help and exit
"

usage() {
  echo "${USAGE_TEXT}"
}

INSTALL_PYTHON_DEV=1

while getopts nh flag
do
  case "${flag}" in
    # development
    n) INSTALL_PYTHON_DEV=;;
    h) usage; exit 0;;
    *) echo; usage; exit 1;;
  esac
done

if [ -z "$VIRTUAL_ENV" ]; then
  echo "This requires the chia python virtual environment."
  echo "Execute '. ./activate' before running."
	exit 1
fi

echo "Timelord requires CMake 3.14+ to compile vdf_client."

PYTHON_VERSION=$(python -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python version: $PYTHON_VERSION"

if [ "$INSTALL_PYTHON_DEV" ]; then
  PYTHON_DEV_DEPENDENCY=lib"$PYTHON_VERSION"-dev
else
  PYTHON_DEV_DEPENDENCY=
fi

export BUILD_VDF_BENCH=Y # Installs the useful vdf_bench test of CPU squaring speed
THE_PATH=$(python -c 'import pkg_resources; print( pkg_resources.get_distribution("chiavdf").location)' 2>/dev/null)/vdf_client
CHIAVDF_VERSION=$(python -c 'import os; os.environ["CHIA_SKIP_SETUP"] = "1"; from setup import dependencies; t = [_ for _ in dependencies if _.startswith("chiavdf")][0]; print(t)')

ubuntu_cmake_install() {
	UBUNTU_PRE_2004=$(python -c 'import subprocess; process = subprocess.run(["lsb_release", "-rs"], stdout=subprocess.PIPE); print(float(process.stdout) < float(20.04))')
	if [ "$UBUNTU_PRE_2004" = "True" ]; then
		echo "Installing CMake with snap."
		sudo apt-get install snapd -y
		sudo apt-get remove --purge cmake -y
		hash -r
		sudo snap install cmake --classic
		# shellcheck disable=SC1091
		. /etc/profile
	else
		echo "Ubuntu 20.04LTS and newer support CMake 3.16+"
		sudo apt-get install cmake -y
	fi
}

symlink_vdf_bench() {
	if [ ! -e vdf_bench ] && [ -e venv/lib/"$1"/site-packages/vdf_bench ]; then
		echo ln -s venv/lib/"$1"/site-packages/vdf_bench
		ln -s venv/lib/"$1"/site-packages/vdf_bench .
	elif [ ! -e venv/lib/"$1"/site-packages/vdf_bench ]; then
		echo "ERROR: Could not find venv/lib/$1/site-packages/vdf_bench"
	else
		echo "./vdf_bench link exists."
	fi
}

if [ "$(uname)" = "Linux" ] && type apt-get; then
	UBUNTU_DEBIAN=true
	echo "Found Ubuntu/Debian."
elif [ "$(uname)" = "Linux" ] && type dnf || yum; then
	RHEL_BASED=true
	echo "Found RedHat."
elif [ "$(uname)" = "Darwin" ]; then
	MACOS=true
	echo "Found MacOS."
fi

if [ -e "$THE_PATH" ]; then
	echo "$THE_PATH"
	echo "vdf_client already exists, no action taken"
else
	if [ -e venv/bin/python ] && test "$UBUNTU_DEBIAN"; then
		echo "Installing chiavdf dependencies on Ubuntu/Debian"
		# If Ubuntu version is older than 20.04LTS then upgrade CMake
		ubuntu_cmake_install
		# Install remaining needed development tools - assumes venv and prior run of install.sh
		echo "apt-get install libgmp-dev libboost-python-dev $PYTHON_DEV_DEPENDENCY libboost-system-dev build-essential -y"
		sudo apt-get install libgmp-dev libboost-python-dev "$PYTHON_DEV_DEPENDENCY" libboost-system-dev build-essential -y
		echo "Installing chiavdf from source on Ubuntu/Debian"
		echo venv/bin/python -m pip install --force --no-binary chiavdf "$CHIAVDF_VERSION"
		venv/bin/python -m pip install --force --no-binary chiavdf "$CHIAVDF_VERSION"
		symlink_vdf_bench "$PYTHON_VERSION"
	elif [ -e venv/bin/python ] && test "$RHEL_BASED"; then
		echo "Installing chiavdf dependencies on RedHat/CentOS/Fedora"
		# Install remaining needed development tools - assumes venv and prior run of install.sh
		echo "yum install gcc gcc-c++ gmp-devel $PYTHON_DEV_DEPENDENCY libtool make autoconf automake openssl-devel libevent-devel boost-devel python3 cmake -y"
		sudo yum install gcc gcc-c++ gmp-devel "$PYTHON_DEV_DEPENDENCY" libtool make autoconf automake openssl-devel libevent-devel boost-devel python3 cmake -y
		echo "Installing chiavdf from source on RedHat/CentOS/Fedora"
		echo venv/bin/python -m pip install --force --no-binary chiavdf "$CHIAVDF_VERSION"
		venv/bin/python -m pip install --force --no-binary chiavdf "$CHIAVDF_VERSION"
		symlink_vdf_bench "$PYTHON_VERSION"
	elif [ -e venv/bin/python ] && test "$MACOS"; then
		echo "Installing chiavdf dependencies for MacOS."
		brew install boost cmake gmp
		echo "Installing chiavdf from source."
		# User needs to provide required packages
		echo venv/bin/python -m pip install --force --no-binary chiavdf "$CHIAVDF_VERSION"
		venv/bin/python -m pip install --force --no-binary chiavdf "$CHIAVDF_VERSION"
		symlink_vdf_bench "$PYTHON_VERSION"
	elif [ -e venv/bin/python ]; then
		echo "Installing chiavdf from source."
		# User needs to provide required packages
		echo venv/bin/python -m pip install --force --no-binary chiavdf "$CHIAVDF_VERSION"
		venv/bin/python -m pip install --force --no-binary chiavdf "$CHIAVDF_VERSION"
		symlink_vdf_bench "$PYTHON_VERSION"
	else
		echo "No venv created yet, please run install.sh."
	fi
fi
echo "To estimate a timelord on this CPU try './vdf_bench square_asm 400000' for an ips estimate."
