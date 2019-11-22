python3 -m venv .venv
. .venv/bin/activate
pip install wheel # For building blspy
pip install -e .
pip install -r requirements.txt

# Install libgmp, libboost, and libflint, and then run the following
cd lib/chiavdf/fast_vdf && sh install.sh