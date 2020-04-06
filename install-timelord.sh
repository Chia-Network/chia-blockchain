
THE_PATH=`python -c 'import pkg_resources; print( pkg_resources.get_distribution("chiavdf").location)' 2> /dev/null`/vdf_client
CHIAVDF_VERSION=`python -c 'from setup import dependencies; t = [_ for _ in dependencies if _.startswith("chiavdf")][0]; print(t)'`

#echo "This script assumes it is run from the chia venv - '. ./activate' before running."

if [ -e $THE_PATH ]
then
  echo $THE_PATH
  echo "vdf_client already exists, no action taken"
else
  if [ -e venv/bin/python ]
  then
    echo "installing chiavdf from source"
    # Check for development tools
    if [ `uname` = "Linux" ] && type apt-get;
    then
      echo "Found Ubuntu/Debian"
      #BUILD_REQUIREMENTS=(cmake libgmp-dev libboost-python-dev libbost-system-dev)
      #for packages in "${BUILD_REQUIREMENTS[@]}"; do
        #echo "$packages";
      #done
        #if ! dpkg -s $Packages >/dev/null 2>&1; then
          #echo "Installing $Packages."
          #sudo apt-get install $Packages -y
        #fi;
      #done
    fi
    echo venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
    #venv/bin/python -m pip install --force --no-binary chiavdf $CHIAVDF_VERSION
  else
    echo "no venv created yet, please run install.sh"
  fi
fi
