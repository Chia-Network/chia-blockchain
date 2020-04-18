## Installation

To install the chia-blockchain node, follow the instructions according to your operating system.
After installing, follow the remaining instructions in [README.md](README.md) to run the software.

### MacOS
Currently Catalina (10.15.x) is required.
Make sure [brew](https://brew.sh/) is available before starting the setup.
```bash
git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh
. ./activate
```

### Debian/Ubuntu

Install dependencies for Ubuntu 18.04, Ubuntu 19.x or newer.
```bash
sudo apt-get update
sudo apt-get install python3.7-venv python3.7-distutils git -y

# Either checkout the source and install
git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh

. ./activate

# Or install chia-blockchain as a binary package
python3.7 -m venv venv
ln -s venv/bin/activate
. ./activate
pip install --upgrade pip
pip install -i https://download.chia.net/simple/ miniupnpc==2.1 setproctitle==1.1.10 cbor2==5.1.0

pip install chia-blockchain==1.0.beta3
```

### Windows (WSL)
#### Install WSL2 + Ubuntu 18.04 LTS

From an Administrator PowerShell
```
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all
```
You will be prompted to reboot. Once that is complete, install Ubuntu 18.04 LTS from the Microsoft Store and run it and complete its initial install steps. You now have linux bash shell that can run linux native software on Windows.

Then follow the steps below which are the same as the usual Ubuntu instructions above.
```bash
sudo apt-get update
sudo apt-get install python3.7-venv python3.7-distutils git -y

# Either checkout the source and install
git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh

. ./activate

# Or install chia-blockchain as a binary package
python3.7 -m venv venv
ln -s venv/bin/activate
. ./activate
pip install --upgrade pip
pip install -i https://download.chia.net/simple/ miniupnpc==2.1 setproctitle==1.1.10 cbor2==5.1.0

pip install chia-blockchain==1.0.beta3
```
You will need to download the Windows native Wallet and unzip into somewhere convenient in Windows. You may have to choose "More Info" and "Run Anyway" to be able to run the currently unsigned installer. This will place a Chia icon in your Start menu and on your Desktop that starts the Wallet UI.

[Download: Chia-Wallet-Install-0.1.3](https://download.chia.net/beta-1.3-win64-wallet/Chia-Wallet-Install-0.1.3.msi)

Instead of `chia-start-wallet-ui &` as explained in the [README.md](README.md) you run `chia-start-wallet-server &` in Ubuntu/WSL 2 to allow the Wallet to connect to the Full Node running in Ubuntu/WSL 2. Once you've enabled `chia-start-wallet-server &` you can run "Chia" from the Start menu or your Desktop.

### Amazon Linux 2

```bash
sudo yum update -y
sudo yum install python3 git -y

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh

. ./activate

# Or install chia-blockchain as a binary package
curl -sL https://rpm.nodesource.com/setup_10.x | sudo bash -
sudo yum install -y nodejs

python3.7 -m venv venv
ln -s venv/bin/activate
. ./activate
pip install --upgrade pip
pip install -i https://download.chia.net/simple/ miniupnpc==2.1 setproctitle==1.1.10 cbor2==5.1.0

pip install chia-blockchain==1.0.beta3
```

### CentOS/RHEL 7.7 or newer

```bash
sudo yum update -y

# Compiling python 3.7 is generally required on CentOS 7.7 and newer
sudo yum install gcc openssl-devel bzip2-devel libffi libffi-devel -y
sudo yum install libsqlite3x-devel -y

wget https://www.python.org/ftp/python/3.7.7/Python-3.7.7.tgz
tar -zxvf Python-3.7.7.tgz ; cd Python-3.7.7
./configure --enable-optimizations; sudo make install; cd ..

# Download and install the source version
git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh
. ./activate

# Or install from binary wheels
curl -sL https://rpm.nodesource.com/setup_10.x | sudo bash -
sudo yum install -y nodejs

python3.7 -m venv venv
ln -s venv/bin/activate
. ./activate
pip install --upgrade pip
pip install -i https://download.chia.net/simple/ miniupnpc==2.1 setproctitle==1.1.10 cbor2==5.1.0

pip install chia-blockchain==1.0.beta3
```
