## Installation

To install the chia-blockchain node, follow the instructions according to your operating system.
After installing, follow the remaining instructions in [README.md](README.md) to run the software.

### MacOS
Make sure [brew](https://brew.sh/) is available before starting the setup.
```bash
brew upgrade python
brew install cmake gmp boost openssl

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
`Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux`
and then
`Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform`.
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

### Amazon Linux 2

```bash
sudo yum update
sudo yum install gcc-c++ cmake3 wget git openssl openssl-devel
sudo yum install python3 python3-devel libffi-devel gmp-devel

sudo amazon-linux-extras install epel
sudo yum install mpfr-devel

# CMake - add a symlink for cmake3 - required by blspy
sudo ln -s /usr/bin/cmake3 /usr/local/bin/cmake

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh

. ./activate
```

### CentOS 7

```bash
sudo yum update
sudo yum install centos-release-scl-rh epel-release
sudo yum install devtoolset-8-toolchain cmake3 libffi-devel
sudo yum install gmp-devel libsqlite3x-devel
sudo yum install wget git openssl openssl-devel

sudo amazon-linux-extras install epel
sudo yum install mpfr-devel

# CMake - add a symlink for cmake3 - required by blspy
sudo ln -s /usr/bin/cmake3 /usr/local/bin/cmake

scl enable devtoolset-8 bash

# Install Python 3.7.5 (current rpm's are 3.6.x)
wget https://www.python.org/ftp/python/3.7.5/Python-3.7.5.tgz
tar -zxvf Python-3.7.5.tgz; cd Python-3.7.5
./configure --enable-optimizations; sudo make install; cd ..

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh
. ./activate
```
