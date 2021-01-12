#!/bin/bash
set -e

echo "This requires the chia python virtual environment."
echo "Execute '. ./activate' if you have not already, before running."

UBUNTU=false
# Manage npm and other install requirements on an OS specific basis
if [ "$(uname)" = "Linux" ]; then
	#LINUX=1
	if type apt-get; then
		# Debian/Ubuntu
		UBUNTU=true
		sudo apt-get install -y npm nodejs libxss1
	elif type yum && [ ! -f "/etc/redhat-release" ] && [ ! -f "/etc/centos-release" ]; then
		# AMZN 2
		echo "Installing on Amazon Linux 2"
		curl -sL https://rpm.nodesource.com/setup_10.x | sudo bash -
		sudo yum install -y nodejs
	elif type yum && [ -f /etc/redhat-release ] || [ -f /etc/centos-release ]; then
		# CentOS or Redhat
		echo "Installing on CentOS/Redhat"
		curl -sL https://rpm.nodesource.com/setup_10.x | sudo bash -
		sudo yum install -y nodejs
	fi
elif [ "$(uname)" = "Darwin" ] && type brew && ! npm version >/dev/null 2>&1; then
	# Install npm if not installed
	brew install npm
elif [ "$(uname)" = "OpenBSD" ]; then
	pkg_add node
elif [ "$(uname)" = "FreeBSD" ]; then
	pkg install node
fi

# Ubuntu before 20.04LTS has an ancient node.js
echo ""
UBUNTU_PRE_2004=false
if $UBUNTU; then
	UBUNTU_PRE_2004=$(python -c 'import subprocess; process = subprocess.run(["lsb_release", "-rs"], stdout=subprocess.PIPE); print(float(process.stdout) < float(20.04))')
fi

if [ "$UBUNTU_PRE_2004" = "True" ]; then
	echo "Installing on Ubuntu older than 20.04 LTS: Ugrading node.js to stable"
	UBUNTU_PRE_2004=true # Unfortunately Python returns True when shell expects true
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
	npm run locale:extract
	npm run locale:compile
	npm run build
else
	echo "Skipping node.js in install.sh on MacOS ci"
fi

echo ""
echo "Chia blockchain install-gui.sh complete."
echo ""
echo "Type 'cd electron-react' and then 'npm run electron &' to start the GUI"
