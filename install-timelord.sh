
THE_PATH=`python -c 'import pkg_resources; print( pkg_resources.get_distribution("chiavdf").location)' 2> /dev/null`/vdf_client

if [ -e $THE_PATH ]
then
  echo $THE_PATH
  echo "vdf_client already exists, no action taken"
else
  if [ -e venv/bin/python ]
  then
    echo "installing chiavdf from source"
    echo venv/bin/python -m pip install --force --no-binary chiavdf chiavdf==0.12.2
    venv/bin/python -m pip install --force --no-binary chiavdf chiavdf==0.12.2
  else
    echo "no venv created yet, please run install.sh"
  fi
fi
