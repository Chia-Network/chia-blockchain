set -e

find_python() {
    set +e
    unset BEST_VERSION
    for V in 37 3.7 38 3.8 3
    do
        which python$V > /dev/null
        if [ $? = 0 ]
        then
            if [ x$BEST_VERSION = x ]
            then
                BEST_VERSION=$V
            fi
        fi
    done
    echo $BEST_VERSION
    set -e
}

if [ x$INSTALL_PYTHON_VERSION = x ]
then
  INSTALL_PYTHON_VERSION=`find_python`
fi


if [ `uname` = "Linux" ]; then
  #LINUX=1
  if type apt-get; then
    # Debian/Ubuntu
    sudo apt-get install -y npm
  elif type yum; then
    # CentOS or AMZN 2
    sudo yum install -y python3 git
    curl -sL https://rpm.nodesource.com/setup_10.x | sudo bash -
    sudo yum install -y nodejs
  fi
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
pip install -i https://hosted.chia.net/simple/ miniupnpc==0.1.dev5 setproctitle==1.1.10 cbor2==5.0.1
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
