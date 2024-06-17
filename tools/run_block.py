#!/usr/bin/env python

"""
run_block: Convert an encoded FullBlock from the Chia blockchain into a list of transactions

As input, takes a file containing a [FullBlock](../chia/types/full_block.py) in json format

```
curl --insecure --cert $config_root/config/ssl/full_node/private_full_node.crt \
     --key $config_root/config/ssl/full_node/private_full_node.key \
     -d '{ "header_hash": "'$hash'" }' -H "Content-Type: application/json" \
     -X POST https://localhost:$port/get_block

$ca_root is the directory containing your current Chia config files
$hash is the header_hash of the [BlockRecord](../chia/consensus/block_record.py)
$port is the Full Node RPC API port
```

The `transactions_generator` and `transactions_generator_ref_list` fields of a `FullBlock`
contain the information necessary to produce transaction record details.

`transactions_generator` is CLVM bytecode
`transactions_generator_ref_list` is a list of block heights as `uint32`

When this CLVM code is run in the correct environment, it produces information that can
then be verified by the consensus rules, or used to view some aspects of transaction history.

The information for each spend is an "NPC" (Name, Puzzle, Condition):
        "coin_name": a unique 32 byte identifier
        "conditions": a list of condition expressions, as in [condition_opcodes.py](../chia/types/condition_opcodes.py)
        "puzzle_hash": the sha256 of the CLVM bytecode that controls spending this coin

Condition Opcodes, such as AGG_SIG_ME, or CREATE_COIN are created by running the "puzzle", i.e. the CLVM bytecode
associated with the coin being spent. Condition Opcodes are verified by every client on the network for every spend,
and in this way they control whether a spend is valid or not.

"""
from __future__ import annotations

import json
from pathlib import Path

import click

from chia._tests.util.run_block import run_json_block
from chia.consensus.constants import replace_str_to_bytes
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH


@click.command()
@click.argument("filename", type=click.Path(exists=True), default="testnet10.396963.json")
def cmd_run_json_block_file(filename):
    """`file` is a file containing a FullBlock in JSON format"""
    return run_json_block_file(Path(filename))


def run_json_block_file(filename: Path):
    full_block = json.load(filename.open("rb"))
    # pull in current constants from config.yaml
    _, constants = get_config_and_constants()

    cat_list = run_json_block(full_block, filename.parent.absolute(), constants)

    cat_list_json = json.dumps([cat.cat_to_dict() for cat in cat_list])
    print(cat_list_json)


def get_config_and_constants():
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    network = config["selected_network"]
    overrides = config["network_overrides"]["constants"][network]
    updated_constants = replace_str_to_bytes(DEFAULT_CONSTANTS, **overrides)
    return config, updated_constants


if __name__ == "__main__":
    cmd_run_json_block_file()  # pylint: disable=no-value-for-parameter
