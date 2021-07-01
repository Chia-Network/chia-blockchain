#!/bin/bash
set -e

sudo apt-get install python3 python3-venv

python3 -m venv venv
if [ ! -f "activate" ]; then
	ln -s venv/bin/activate .
fi
. ./activate

pip install --upgrade pip
pip install -i https://hosted.chia.net/simple/ miniupnpc==2.1 setproctitle==1.1.10
pip install git+https://github.com/silicoin-network/silicoin-blockchain.git@v0.0.4
ln -s chia venv/bin/silicoin

echo "Type '. ./activate' to enter the virtual environment"
echo "Type 'silicoin init' to begin"
echo "Type 'silicoin plots add -d /path/to/plots' to plots"
echo "Type 'silicoin start farmer' to start farmer"
