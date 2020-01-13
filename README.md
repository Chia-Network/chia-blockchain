# chia-blockchain
Please check out the [wiki](https://github.com/Chia-Network/chia-blockchain/wiki) for information on this project.

Python 3.7 is required. Make sure your default python version is >=3.7 by typing python3.

You will need to enable [UPnP](https://www.homenethowto.com/ports-and-nat/upnp-automatic-port-forward/) on your router or add a NAT (for IPv4 but not IPv6) and firewall rule to allow TCP port 8444 access to your peer. These methods tend to be router make/model specific.

For alpha testnet most should only install harvesters, farmers, plotter and full nodes. Building timelords and VDFs is for sophisticated users in most environments. Chia Network and additional volunteers are running sufficient time lords for testnet consensus.

## Step 1: Install harvester, farmer, plotter, and full node

### Debian/Ubuntu

```bash
sudo apt-get update
sudo apt-get install build-essential cmake python3-dev python3-venv libssl-dev libffi-dev --no-install-recommends

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh

. .venv/bin/activate
```
### Amazon Linux 2

```bash
sudo yum update
sudo yum install gcc-c++ cmake3 wget git openssl openssl-devel
sudo yum install python3 python3-devel libffi-devel

# CMake - add a symlink for cmake3 - required by blspy
sudo ln -s /usr/bin/cmake3 /usr/local/bin/cmake

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh

. .venv/bin/activate
```
### CentOS 7

```bash
sudo yum update
sudo yum install centos-release-scl-rh epel-release
sudo yum install devtoolset-8-toolchain cmake3 libffi-devel
sudo yum install wget git openssl openssl-devel

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
. .venv/bin/activate
```

### Windows (WSL + Ubuntu)
#### Install WSL + Ubuntu 18.04 LTS, upgrade to Ubuntu 19.x

This will require multiple reboots. From an Administrator PowerShell
`Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux`
and then
`Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform`.
Once that is complete, install Ubuntu 18.04 LTS from the Windows Store.
```bash
# Upgrade to 19.x
sudo nano /etc/update-manager/release-upgrades
# Change "Prompt=lts" to "Prompt=normal" save and exit

sudo apt-get -y update
sudo apt-get -y upgrade
sudo do-release-upgrade

sudo apt-get install -y build-essential cmake python3-dev python3-venv software-properties-common --no-install-recommends

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sudo sh install.sh
. .venv/bin/activate
```

#### Alternate method for Ubuntu 18.04 LTS
In `./install.sh`:
Change `python3` to `python3.7`
Each line that starts with `pip ...` becomes `python -m pip ...`

```bash
sudo apt-get -y update
sudo apt-get install -y build-essential cmake python3-dev python3-venv software-properties-common --no-install-recommends

# Install python3.7 with ppa
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get -y update
sudo apt-get install -y python3.7 python3.7-venv python3.7-dev

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sudo sh install.sh
. .venv/bin/activate
```

### MacOS
Make sure [brew](https://brew.sh/) is available before starting the setup.
```bash
brew upgrade python
brew install cmake

git clone https://github.com/Chia-Network/chia-blockchain.git
cd chia-blockchain

sh install.sh
. .venv/bin/activate
```


## Step 2: Install timelord (optional)
Note: this step is needed only if you intend to run a timelord or a local simulation.
These assume you've already successfully installed harvester, farmer, plotting, and full node above.
### Ubuntu/Debian
```bash
cd chia-blockchain

sh install_timelord.sh
```
### Amazon Linux 2 and CentOS 7
```bash
#Only for Amazon Linux 2
sudo amazon-linux-extras install epel

sudo yum install gmp-devel mpfr-devel

# Install Boost 1.72.0
wget https://dl.bintray.com/boostorg/release/1.72.0/source/boost_1_72_0.tar.gz
tar -zxvf boost_1_72_0.tar.gz
cd boost_1_72_0
./bootstrap.sh --prefix=/usr/local
sudo ./b2 install --prefix=/usr/local --with=all; cd ..

# Install Flint2
git clone https://github.com/wbhart/flint2
cd flint2; ./configure; sudo make install; cd ..
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/lib

cd chia-blockchain

sh install_timelord.sh
```

### Windows (WSL + Ubuntu)
#### Install WSL + Ubuntu upgraded to 19.x
```bash
cd chia-blockchain

sh install_timelord.sh
```
#### Alternate method for Ubuntu 18.04
```bash
# Install boost 1.70 with ppa
sudo add-apt-repository -y ppa:mhier/libboost-latest
sudo apt-get update
sudo apt-get install libboost1.70 libboost1.70-dev
```

### MacOS
```bash
brew install boost gmp mpir mpfr

cd chia-blockchain

git clone https://github.com/wbhart/flint2

sh install_timelord.sh
```

## Step 3: Generate keys
First, create some keys by running the following script:
```bash
python -m scripts.regenerate_keys
```

## Step 4a: Run a full node
To run a full node on port 8002, and connect to the testnet, run the following command.
This wil also start an ssh server in port 8222 for the UI, which you can connect to
to see the state of the node.
```bash
python -m src.server.start_full_node "127.0.0.1" 8444 -id 1 -r 8555 &
ssh -p 8222 localhost
```

## Step 4b: Run a farmer + full node
Instead of running only a full node (as in 4a), you can also run a farmer.
Farmers are entities in the network who use their hard drive space to try to create
blocks (like Bitcoin's miners), and earn block rewards. First, you must generate some hard drive plots, which
can take a long time depending on the size of the plots (the k variable). Then, run the farmer + full node with
the following script. A full node is also started, which you can ssh into to view the node UI (previous ssh command).
```bash
python -m scripts.create_plots -k 20 -n 10
sh ./scripts/run_farming.sh
```

## Step 4c: Run a timelord + full node
Timelords execute sequential verifiable delay functions (proofs of time), that get added to
blocks to make them valid. This requires fast CPUs and a lot of memory as well as completing
both install steps above.
```bash
sh ./scripts/run_timelord.sh
```

## Tips
When running the servers on Mac OS, allow the application to accept incoming connections.

Ubuntu 19.xx, Amazon Linux 2, and CentOS 7.7 or newer are the easiest linux install environments currently.

UPnP is enabled by default, to open the port for incoming connections. If this causes issues,
you can disable it in the configuration. Some routers may require port forwarding, or enabling
UPnP in the router configuration.

Due to the nature of proof of space lookups by the harvester you should limit the number of plots
on a physical drive to 50 or less. This limit should significantly increase before beta.

You can also run the simulation, which runs all servers and multiple full nodes, locally, at once.
If you want to run the simulation, change the introducer ip in ./config/config.yaml so that the
full node points to the local introducer (127.0.0.1:8445).

Note the the simulation is local only and requires installation of timelords and VDFs.

The introducer will only know the local ips of the full nodes, so it cannot broadcast the correct
ips to external peers.

```bash
sh ./scripts/run_all_simulation.sh
```
