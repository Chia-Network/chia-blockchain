echo "This requires the chia python virtual environment."
echo "Execute '. ./activate' if you have not already, before running."
echo "This version of Timelord requires CMake 3.14+ to compile vdf_client"

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

# this fancy syntax sets PYTHON_VER to "python3.7" unless PYTHON_VER is defined
# if PYTHON_VER=3.8, then PYTHON_VER becomes python3.8

PYTHON_VER=python${PYTHON_VER:-3.7}
echo $PYTHON_VER

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
    sudo apt-get install cmake libgmp-dev libboost-python-dev lib$PYTHON_VER-dev libboost-system-dev -y
    echo venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    ln -s venv/lib/$PYTHON_VER/site-packages/vdf_bench
  elif [ -e venv/bin/python ] && test $MACOS && brew info boost | grep -q 'Not installed'
  then
    echo "Installing chiavdf requirements for MacOS"
    brew install boost
    echo "installing chiavdf from source for MacOS"
    # User needs to provide required packages
    echo venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    ln -s venv/lib/$PYTHON_VER/site-packages/vdf_bench
  elif [ -e venv/bin/python ]
  then
    echo "installing chiavdf from source"
    # User needs to provide required packages
    echo venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    ln -s venv/lib/$PYTHON_VER/site-packages/vdf_bench
  else
    echo "no venv created yet, please run install.sh"
  fi
fi
echo "To see how fast your timelord is likely to be try './vdf_bench square_asm 250000' for an ips estimate"
