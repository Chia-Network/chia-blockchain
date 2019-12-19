#!/bin/bash
set -e

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

cd lib/chiavdf/fast_vdf && sh install.sh

echo ""
echo "Chia blockchain install_timelord.sh complete."
echo "For assistance join us on Keybase in the #testnet chat channel"
echo "https://keybase.io/team/chia_network.public"
