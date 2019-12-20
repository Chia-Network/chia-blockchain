#!/bin/bash
set -e

if [ `uname` = "Linux" ] && type apt-get; then
    # Debian/Ubuntu
    sudo apt-get install -y libgmp3-dev libflint-dev \
        libboost-dev libboost-system-dev
fi

# Install libgmp, libboost, and libflint, and then run the following
# Check for git clone of flint2 on MacOS and install if found
if [ -f flint2/configure ]; then
    cd flint2/
    if [ ! -f Makefile ]; then
       ./configure
    fi
    make -j4
    make install
    cd ../
fi

make -C lib/chiavdf/fast_vdf

echo ""
echo "Chia blockchain install_timelord.sh complete."
echo "For assistance join us on Keybase in the #testnet chat channel"
echo "https://keybase.io/team/chia_network.public"
