#!/bin/bash
set -e

USAGE_TEXT="\
Usage: $0 [-d]

  -d                          install development dependencies
  -h                          display this help and exit
"

usage() {
  echo "${USAGE_TEXT}"
}

EXTRAS=

while getopts dh flag
do
  case "${flag}" in
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
	if command -v apt-get &> /dev/null; then
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
	if ! command -v bc &> /dev/null; then
		sudo apt install bc -y
	fi
	# Mint 20.04 repsonds with 20 here so 20 instead of 20.04
	UBUNTU_PRE_2004=$(echo "$LSB_RELEASE<20" | bc)
	UBUNTU_2100=$(echo "$LSB_RELEASE>=21" | bc)
fi

# Manage npm and other install requirements on an OS specific basis
if [ "$(uname)" = "Linux" ]; then
	#LINUX=1
	if [ "$UBUNTU" = "true" ] && [ "$UBUNTU_PRE_2004" = "1" ]; then
		# Ubuntu
		echo "Installing on Ubuntu pre 20.04 LTS."
		sudo apt-get update
		sudo apt-get install -y python3.7-venv python3.7-distutils
	elif [ "$UBUNTU" = "true" ] && [ "$UBUNTU_PRE_2004" = "0" ] && [ "$UBUNTU_2100" = "0" ]; then
		echo "Installing on Ubuntu 20.04 LTS."
		sudo apt-get update
		sudo apt-get install -y python3.8-venv python3-distutils
	elif [ "$UBUNTU" = "true" ] && [ "$UBUNTU_2100" = "1" ]; then
		echo "Installing on Ubuntu 21.04 or newer."
		sudo apt-get update
		sudo apt-get install -y python3.9-venv python3-distutils
	elif [ "$DEBIAN" = "true" ]; then
		echo "Installing on Debian."
		sudo apt-get update
		sudo apt-get install -y python3-venv=3.9*
	elif type pacman && [ -f "/etc/arch-release" ]; then
		# Arch Linux
		echo "Installing on Arch Linux."
		echo "Python <= 3.9.9 is required. Installing python-3.9.9-1"
		case $(uname -m) in
			x86_64)
				sudo pacman -U --needed https://archive.archlinux.org/packages/p/python/python-3.9.9-1-x86_64.pkg.tar.zst
				;;
			aarch64)
				sudo pacman -U --needed http://tardis.tiny-vps.com/aarm/packages/p/python/python-3.9.9-1-aarch64.pkg.tar.xz
				;;
			*)
				echo "Incompatible CPU architecture. Must be x86_64 or aarch64."
				exit 1
				;;
			esac
		sudo pacman -S --needed git
	elif type yum && [ ! -f "/etc/redhat-release" ] && [ ! -f "/etc/centos-release" ] && [ ! -f "/etc/fedora-release" ]; then
		# AMZN 2
		echo "Installing on Amazon Linux 2."
		AMZN2_PY_LATEST=$(yum --showduplicates list python3 | expand | grep -P '(?!.*3.10.*)x86_64|(?!.*3.10.*)aarch64' | tail -n 1 | awk '{print $2}')
		AMZN2_ARCH=$(uname -m)
		sudo yum install -y python3-"$AMZN2_PY_LATEST"."$AMZN2_ARCH" git
	elif type yum && [ -f "/etc/redhat-release" ] || [ -f "/etc/centos-release" ] || [ -f "/etc/fedora-release" ]; then
		# CentOS or Redhat or Fedora
		echo "Installing on CentOS/Redhat/Fedora."
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
	for V in 39 3.9 38 3.8 37 3.7 3; do
		if command -v python$V >/dev/null; then
			if [ "$BEST_VERSION" = "" ]; then
				BEST_VERSION=$V
				if [ "$BEST_VERSION" = "3" ]; then
					PY3_VERSION=$(python$BEST_VERSION --version | cut -d ' ' -f2)
					if [[ "$PY3_VERSION" =~ 3.10.* ]]; then
						echo "Chia requires Python version <= 3.9.9"
						echo "Current Python version = $PY3_VERSION"
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

echo "Python version is $INSTALL_PYTHON_VERSION"
$INSTALL_PYTHON_PATH -m venv venv
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
