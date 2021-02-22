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
