#!/bin/bash
set -e
UBUNTU=false
if [ "$(uname)" = "Linux" ]; then
	#LINUX=1
	if type apt-get; then
		UBUNTU=true
	fi
fi

# Check for non 64 bit ARM64/Raspberry Pi installs
if [ "$(uname -m)" = "armv7l" ]; then
  echo ""
	echo "WARNING:"
	echo "Chia Blockchain requires a 64 bit OS and this is 32 bit armv7l"
	echo "Exiting."
	exit 1
fi

UBUNTU_PRE_2004=false
if $UBUNTU; then
	LSB_RELEASE=$(lsb_release -rs)
	# In case Ubuntu minimal does not come with bc
	if [ "$(which bc |wc -l)" -eq 0 ]; then sudo apt install bc -y; fi
	# Mint 20.04 repsonds with 20 here so 20 instead of 20.04
	UBUNTU_PRE_2004=$(echo "$LSB_RELEASE<20" | bc)
fi

# Manage npm and other install requirements on an OS specific basis
if [ "$(uname)" = "Linux" ]; then
	#LINUX=1
	if [ "$UBUNTU" = "true" ] && [ "$UBUNTU_PRE_2004" = "1" ]; then
		# Debian/Ubuntu
		echo "Installing on Ubuntu/Debian pre 20.04 LTS"
		sudo apt-get update
		sudo apt-get install -y python3.7-venv python3.7-distutils
	elif [ "$UBUNTU" = "true" ] && [ "$UBUNTU_PRE_2004" = "0" ]; then
		echo "Installing on Ubuntu/Debian 20.04 LTS or newer"
		sudo apt-get update
		sudo apt-get install -y python3.8-venv python3-distutils
	elif type yum && [ ! -f "/etc/redhat-release" ] && [ ! -f "/etc/centos-release" ]; then
		# AMZN 2
		echo "Installing on Amazon Linux 2"
		sudo yum install -y python3 git
	elif type yum && [ -f /etc/redhat-release ] || [ -f /etc/centos-release ]; then
		# CentOS or Redhat
		echo "Installing on CentOS/Redhat"
	fi
elif [ "$(uname)" = "Darwin" ] && ! type brew >/dev/null 2>&1; then
	echo "Installation currently requires brew on MacOS - https://brew.sh/"
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
	for V in 37 3.7 38 3.8 39 3.9 3; do
		if which python$V >/dev/null; then
			if [ x"$BEST_VERSION" = x ]; then
				BEST_VERSION=$V
			fi
		fi
	done
	echo $BEST_VERSION
	set -e
}

if [ x"$INSTALL_PYTHON_VERSION" = x ]; then
	INSTALL_PYTHON_VERSION=$(find_python)
fi

# this fancy syntax sets INSTALL_PYTHON_PATH to "python3.7" unless INSTALL_PYTHON_VERSION is defined
# if INSTALL_PYTHON_VERSION=3.8, then INSTALL_PYTHON_PATH becomes python3.8

INSTALL_PYTHON_PATH=python${INSTALL_PYTHON_VERSION:-3.7}

echo "Python version is $INSTALL_PYTHON_VERSION"
$INSTALL_PYTHON_PATH -m venv venv
if [ ! -f "activate" ]; then
	ln -s venv/bin/activate .
fi

# shellcheck disable=SC1091
. ./activate
# pip 20.x+ supports Linux binary wheels
pip install --upgrade pip
pip install wheel
#if [ "$INSTALL_PYTHON_VERSION" = "3.8" ]; then
# This remains in case there is a diversion of binary wheels
pip install --extra-index-url https://download.chia.net/simple/ miniupnpc==2.1
pip install -e . --extra-index-url https://download.chia.net/simple/

echo ""
echo "Chia blockchain install.sh complete."
echo "For assistance join us on Keybase in the #testnet chat channel"
echo "https://keybase.io/team/chia_network.public"
echo ""
echo "Try the Quick Start Guide to running chia-blockchain"
echo "https://github.com/Chia-Network/chia-blockchain/wiki/Quick-Start-Guide"
echo ""
echo "To install the GUI type 'sh install-gui.sh' after '. ./activate'"
echo ""
echo "Type '. ./activate' and then 'chia init' to begin"
