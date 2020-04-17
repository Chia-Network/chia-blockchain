echo "This requires the chia python virtual environment."
echo "Execute '. ./activate' if you have not already, before running."
export BUILD_VDF_BENCH=Y # Installs the useful vdf_bench test of CPU squaring speed
THE_PATH=`python -c 'import pkg_resources; print( pkg_resources.get_distribution("chiavdf").location)' 2> /dev/null`/vdf_client
CHIAVDF_VERSION=`python -c 'from setup import dependencies; t = [_ for _ in dependencies if _.startswith("chiavdf")][0]; print(t)'`

if [ `uname` = "Linux" ] && type apt-get;
  then UBUNTU_DEBIAN=true
  echo "Found Ubuntu/Debian"
elif [ `uname` = "Darwin" ];
  then MACOS=true
  echo "Found MacOS"
fi

if [ -e $THE_PATH ] && ! test $MACOS
then
  echo $THE_PATH
  echo "vdf_client already exists, no action taken"
else
  if [ -e venv/bin/python ] && test $UBUNTU_DEBIAN
  then
    echo "Installing chiavdf from source on Ubuntu/Debian"
    # Install needed development tools
    sudo apt-get install cmake libgmp-dev libboost-python-dev libpython3.7-dev libboost-system-dev -y
    echo venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    ln -s venv/lib/python3.7/site-packages/vdf_bench
  elif [ -e venv/bin/python ] && test $MACOS && ! brew info boost>/dev/null 2>&1
  then
    echo "Installing chiavdf requirements for MacOS"
    brew install boost
  elif [ -e venv/bin/python ]
  then
    echo "installing chiavdf from source"
    # User needs to provide required packages
    echo venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    ln -s venv/lib/python3.7/site-packages/vdf_bench
  else
    echo "no venv created yet, please run install.sh"
  fi
fi
