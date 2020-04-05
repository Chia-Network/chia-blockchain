
THE_PATH=`python -c 'import pkg_resources; print( pkg_resources.get_distribution("chiavdf").location)' 2> /dev/null`/vdf_client
CHIAVDF_VERSION=`python -c 'from setup import dependencies; t = [_ for _ in dependencies if _.startswith("chiavdf")][0]; print(t)'`

if [ -e $THE_PATH ]
then
  echo $THE_PATH
  echo "vdf_client already exists, no action taken"
else
  if [ -e venv/bin/python ]
  then
    echo "installing chiavdf from source"
    if [ `uname` = "Linux" ] && type apt-get; then
      echo "Found Ubuntu"
      if ! dpkg -s cmake >/dev/null 2>&1; then
        echo "Cmake requirments not found. Installing them."
        sudo apt-get install cmake libgmp-dev libboost-all-dev -y
      fi
    fi
    echo venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
  else
    echo "no venv created yet, please run install.sh"
  fi
fi
