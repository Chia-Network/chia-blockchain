
THE_PATH=`python -c 'import pkg_resources; print( pkg_resources.get_distribution("chiavdf").location)' 2> /dev/null`/vdf_client
CHIAVDF_VERSION=`python -c 'from setup import dependencies; t = [_ for _ in dependencies if _.startswith("chiavdf")][0]; print(t)'`

echo "This script assumes it is run from the chia venv - '. ./activate' before running."

if [ -e $THE_PATH ]
then
  echo $THE_PATH
  echo "vdf_client already exists, no action taken"
else
  if [ -e venv/bin/python ]
  then
    echo "installing chiavdf from source"
    # Check for development tools - this takes the shortcut of only checking for CMake
    if [ `uname` = "Linux" ] && type apt-get; then
      # Found Ubuntu
      if ! dpkg -s cmake >/dev/null 2>&1; then
        echo "CMake requirments not found. Installing them."
        sudo apt-get install cmake libgmp-dev libboost-python-dev libboost-system-dev -y
      fi
    fi
    echo venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
  else
    echo "no venv created yet, please run install.sh"
  fi
fi
