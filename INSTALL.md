## Installation

To install the chia-blockchain node, follow the instructions according to your operating system.
After installing, follow the remaining instructions in [README.md](README.md) to run the software.

### MacOS
Make sure [brew](https://brew.sh/) is available before starting the setup.
```bash
brew upgrade python
brew install npm gmp

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh
. ./activate
```

### Debian/Ubuntu

On Ubuntu 18.04, you need python 3.7. It's not available in the default
repository, so you need to add an alternate source. You can skip this step
if you install in Ubuntu 19.x or higher.

```bash
# for add-apt-repository
sudo apt install software-properties-common -y
sudo add-apt-repository ppa:deadsnakes/ppa -y
```

Install dependencies for Ubuntu 18.04 from above or Ubuntu 19.x or higher.
```bash
sudo apt-get update
sudo apt-get install python3.7-venv python3.7-dev python3-pip git -y

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh

. ./activate
```

### Windows (WSL)
#### Install WSL2 + Ubuntu 18.04 LTS

From an Administrator PowerShell
`dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart`
and then
`dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart`.
This usually requires a reboot. Once that is complete, install Ubuntu 18.04 LTS from the Microsoft Store and run it. Then follow the steps below.
```bash
# add-apt-repository
sudo add-apt-repository ppa:deadsnakes/ppa -y

sudo apt-get -y update
sudo apt-get -y upgrade

sudo apt-get install python3.7-venv python3.7-dev python3-pip git -y

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh
. ./activate
```
You will need to download the Windows native Wallet and unzip into somewhere convenient in Windows.

[main.js-win32-x64.zip](https://hosted.chia.net/beta-1.0-win64-wallet/main.js-win32-x64.zip)

Instead of `chia-start-wallet-ui &` as explained in the [README.md](README.md) you run `chia-websocket-server &` in Ubuntu/WSL 2 to allow the Wallet to connect to the Full Node running in Ubuntu/WSL 2. Once you've enabled `chia-websocket-server` you can run `chia.exe` from the unzipped `chia-win32-x64` directory.

### Amazon Linux 2

```bash
sudo yum update
sudo yum install python3 python3-devel git

# Install npm and node
curl -sL https://rpm.nodesource.com/setup_10.x | sudo bash -
sudo yum install nodejs

# uPnP and setproctitle require compiling
sudo yum install gcc

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh

. ./activate
```

### CentOS 7.7 or newer

```bash
sudo yum update
sudo yum install gcc openssl-devel bzip2-devel libffi libffi-devel
sudo yum install libsqlite3x-devel

# Install python 3.7
wget https://www.python.org/ftp/python/3.7.7/Python-3.7.7.tgz
tar -zxvf Python-3.7.7.tgz ; cd Python-3.7.7
./configure --enable-optimizations; sudo make install; cd ..

# Install npm and node
curl -sL https://rpm.nodesource.com/setup_10.x | sudo bash -
sudo yum install nodejs

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh
. ./activate
```
