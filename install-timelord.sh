#!/bin/bash

if [ -z "$VIRTUAL_ENV" ]; then
  echo "This requires the silicoin python virtual environment."
  echo "Execute '. ./activate' before running."
	exit 1
fi

echo "Timelord requires CMake 3.14+ to compile vdf_client."

PYTHON_VERSION=$(python -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python version: $PYTHON_VERSION"

export BUILD_VDF_BENCH=Y # Installs the useful vdf_bench test of CPU squaring speed
THE_PATH=$(python -c 'import pkg_resources; print( pkg_resources.get_distribution("chiavdf").location)' 2>/dev/null)/vdf_client
CHIAVDF_VERSION=$(python -c 'from setup import dependencies; t = [_ for _ in dependencies if _.startswith("chiavdf")][0]; print(t)')

ubuntu_cmake_install() {
	UBUNTU_PRE_2004=$(python -c 'import subprocess; process = subprocess.run(["lsb_release", "-rs"], stdout=subprocess.PIPE); print(float(process.stdout) < float(20.04))')
	if [ "$UBUNTU_PRE_2004" = "True" ]; then
		echo "Ubuntu version is pre 20.04LTS - installing CMake with snap."
		sudo apt-get install snap -y
		sudo apt-get remove --purge cmake -y
		hash -r
		sudo snap install cmake --classic
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
	if [ -e venv/bin/python ] && test $UBUNTU_DEBIAN; then
		echo "Installing chiavdf from source on Ubuntu/Debian"
		# If Ubuntu version is older than 20.04LTS then upgrade CMake
		ubuntu_cmake_install
		# Install remaining needed development tools - assumes venv and prior run of install.sh
		echo apt-get install libgmp-dev libboost-python-dev lib"$PYTHON_VERSION"-dev libboost-system-dev build-essential -y
		sudo apt-get install libgmp-dev libboost-python-dev lib"$PYTHON_VERSION"-dev libboost-system-dev build-essential -y
		echo venv/bin/python -m pip install --force --no-binary chiavdf "$CHIAVDF_VERSION"
		venv/bin/python -m pip install --force --no-binary chiavdf "$CHIAVDF_VERSION"
		symlink_vdf_bench "$PYTHON_VERSION"
	elif [ -e venv/bin/python ] && test $RHEL_BASED; then
		echo "Installing chiavdf from source on RedHat/CentOS/Fedora"
		# Install remaining needed development tools - assumes venv and prior run of install.sh
		echo yum install gcc gcc-c++ gmp-devel python3-devel libtool make autoconf automake openssl-devel libevent-devel boost-devel python3 -y
		sudo yum install gcc gcc-c++ gmp-devel python3-devel libtool make autoconf automake openssl-devel libevent-devel boost-devel python3 -y
		echo venv/bin/python -m pip install --force --no-binary chiavdf "$CHIAVDF_VERSION"
		venv/bin/python -m pip install --force --no-binary chiavdf "$CHIAVDF_VERSION"
		symlink_vdf_bench "$PYTHON_VERSION"
	elif [ -e venv/bin/python ] && test $MACOS && [ "$(brew info boost | grep -c 'Not installed')" -eq 1 ]; then
		echo "Installing chiavdf requirement boost for MacOS."
		brew install boost
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
