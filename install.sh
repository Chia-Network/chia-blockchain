#!/bin/bash
set -e

python3 -m venv .venv
. .venv/bin/activate
pip install wheel
pip install -e .
pip install -r requirements.txt

echo ""
echo "Chia blockchain install.sh complete."
echo "For assistance join us on Keybase in the #testnet chat channel"
echo "https://keybase.io/team/chia_network.public"
