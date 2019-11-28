python3 -m venv .venv
. .venv/bin/activate
pip install wheel # For building blspy
pip install -e .
pip install -r requirements.txt

# Install libgmp, libboost, and libflint, and then run the following
# Check for git clone of flint2 on MacOS and install if found
if [  -f flint2/configure ]; then
    cd flint2/
    make -j4
    make install
    cd ../
fi

cd lib/chiavdf/fast_vdf && sh install.sh
