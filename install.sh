python3 -m venv .venv
. .venv/bin/activate
pip install wheel # For building blspy
pip install -e .
pip install -r requirements.txt

# Install libgmp, libboost, and libflint, and then run the following
# Check for git clone of flint2 on MacOS and install if found
if [  -f flint2/configure ]; then
    cd flint2/
    ./configure
    make -j4
    make install
    cd ../
fi

cd lib/chiavdf/fast_vdf && sh install.sh
echo "\nChia blockchain install.sh complete."
echo "For assistance join us on Keybase in the #testnet chat channel"
echo "https://keybase.io/team/chia_network.public"
