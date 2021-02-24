#!/bin/sh

# This hack is a quick way to recompile everything in this directory

#BASE_DIR=`pwd | dirname`

FILES=$(ls ./*.clvm)
echo "$FILES"

INCLUDE_DIR=$(pwd)

for FILE in $FILES
do
  echo "run -d -i $INCLUDE_DIR $FILE > $FILE.hex"
  # run -d -i $INCLUDE_DIR $FILE > $FILE.hex
done

for FILE in $FILES
do
  echo "opd -H $FILE.hex | head -1  > $FILE.hex.sha256tree"
done

echo
echo "Copy & paste the above to the shell to recompile"
