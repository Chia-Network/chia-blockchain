#!/bin/bash

# This script assumes that the user has a testnet profile at the directory in $CHIA_ROOT
# unsigned_request.json is the first request from the client, that describes the transaction we
#   want the wallet to create for us.

export CHIA_ROOT=~/.chia/testnet10

chia stop all -d
chia start -r wallet && sleep 3

# TODO: rename to testnet10_unsigned_request.json
chia rpc wallet create_unsigned_transaction -j unsigned_request.json | tee unsigned_tx.json
chia rpc wallet blind_sign_transaction -j unsigned_tx.json | tee signed_tx.json
chia rpc wallet push_tx -j signed_tx.json
