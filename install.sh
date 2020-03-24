#!/bin/bash
set -e

if [ `uname` = "Linux" ] && type apt-get; then
    # Debian/Ubuntu
    sudo apt-get install -y libgmp3-dev libboost-dev libboost-system-dev npm
fi

python3 -m venv .venv
. .venv/bin/activate
pip install wheel
pip install -e .
pip install -r requirements.txt

make -C lib/chiavdf/fast_vdf
cd ./src/electron-ui
npm install

echo ""
echo "Chia blockchain install.sh complete."
echo "For assistance join us on Keybase in the #testnet chat channel"
echo "https://keybase.io/team/chia_network.public"
