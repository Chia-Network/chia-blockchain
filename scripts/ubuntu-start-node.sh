#!/bin/bash
# Downloads and installs and starts a productiuon node of Chinilla blockchain
git clone -b latest --recurse-submodules https://github.com/Chinilla/chinilla-blockchain
cd chinilla-blockchain
. ./activate
sh install.sh
chinilla init
chinilla start node