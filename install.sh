set -e

if [ `uname` = "Linux" ] && type apt-get; then
    # Debian/Ubuntu
    sudo apt-get install -y npm python3-dev
fi

# this fancy syntax sets INSTALL_PYTHON_PATH to "python3.7" unless INSTALL_PYTHON_VERSION is defined
# if INSTALL_PYTHON_VERSION=3.8, then INSTALL_PYTHON_PATH becomes python3.8

INSTALL_PYTHON_PATH=python${INSTALL_PYTHON_VERSION:-3.7}

$INSTALL_PYTHON_PATH -m venv venv
if [ ! -f "activate" ]; then
    ln -s venv/bin/activate
fi
. ./activate
# pip 20.x+ supports Linux binary wheels
pip install --upgrade pip
pip install -e .

cd ./electron-ui
npm install

echo ""
echo "Chia blockchain install.sh complete."
echo "For assistance join us on Keybase in the #testnet chat channel"
echo "https://keybase.io/team/chia_network.public"
echo ""
echo "Return to the README.md to start running the Chia blockchain"
echo "https://github.com/Chia-Network/chia-blockchain/blob/master/README.md"
echo "Type '. ./activate' to use Chia"
