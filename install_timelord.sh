#!/bin/bash
set -e

if [ `uname` = "Linux" ] && type apt-get; then
    # Debian/Ubuntu
    sudo apt-get install -y libgmp3-dev libboost-dev libboost-system-dev
fi

make -C lib/chiavdf/fast_vdf

echo ""
echo "Chia blockchain install_timelord.sh complete."
echo "For assistance join us on Keybase in the #testnet chat channel"
echo "https://keybase.io/team/chia_network.public"
