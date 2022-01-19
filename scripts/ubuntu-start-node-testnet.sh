#!/bin/bash
# Downloads and installs and starts a testnet11 node of Chinilla blockchain
cd /home/chinilla
git clone -b chinilla --recurse-submodules https://github.com/Chinilla/chinilla-blockchain
cd chinilla-blockchain
. ./activate
sh install.sh
chinilla init
chinilla init --testnet
chinilla start node