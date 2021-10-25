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
import click
import json
from typing import List, Tuple, TextIO

from chia.consensus.constants import ConsensusConstants
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.full_block import FullBlock
from chia.types.name_puzzle_condition import NPC
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint32
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.generator_types import BlockGenerator, GeneratorArg
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.util.errors import ConsensusError, Err


def condition_with_args_to_dict(condition_with_args: ConditionWithArgs):
    return {
        "condition_opcode": condition_with_args.opcode.name,
        "arguments": [arg.hex() for arg in condition_with_args.vars],
    }


def condition_list_to_dict(condition_list: Tuple[ConditionOpcode, List[ConditionWithArgs]]):
    assert all([condition_list[0] == cwa.opcode for cwa in condition_list[1]])
    return [condition_with_args_to_dict(cwa) for cwa in condition_list[1]]


def npc_to_dict(npc: NPC):
    return {
        "coin_name": npc.coin_name.hex(),
        "conditions": [{"condition_type": c[0].name, "conditions": condition_list_to_dict(c)} for c in npc.conditions],
        "puzzle_hash": npc.puzzle_hash.hex(),
    }


def run_generator(block_generator: BlockGenerator, constants: ConsensusConstants) -> List[NPC]:
    npc_result = get_name_puzzle_conditions(
        block_generator,
        constants.MAX_BLOCK_COST_CLVM,  # min(self.constants.MAX_BLOCK_COST_CLVM, block.transactions_info.cost),
        cost_per_byte=constants.COST_PER_BYTE,
        safe_mode=False,
    )
    if npc_result.error is not None:
        raise ConsensusError(Err(npc_result.error))

    return npc_result.npc_list


def ref_list_to_args(ref_list: List[uint32]):
    args = []
    for height in ref_list:
        with open(f"testnet10.{height}.json", "r") as f:
            program_str = json.load(f)["block"]["transactions_generator"]
            arg = GeneratorArg(height, SerializedProgram.fromhex(program_str))
            args.append(arg)
    return args


def run_full_block(block: FullBlock, constants: ConsensusConstants) -> List[NPC]:
    generator_args = ref_list_to_args(block.transactions_generator_ref_list)
    if block.transactions_generator is None:
        raise RuntimeError("transactions_generator of FullBlock is null")
    block_generator = BlockGenerator(block.transactions_generator, generator_args)
    return run_generator(block_generator, constants)


def run_generator_with_args(
    generator_program_hex: str, generator_args: List[GeneratorArg], constants: ConsensusConstants
) -> List[NPC]:
    generator_program = SerializedProgram.fromhex(generator_program_hex)
    block_generator = BlockGenerator(generator_program, generator_args)
    return run_generator(block_generator, constants)


@click.command()
@click.argument("file", type=click.File("rb"), default=False)
def cmd_run_json_block_file(file):
    """`file` is a file containing a FullBlock in JSON format"""
    return run_json_block_file(file)


def run_json_block_file(file: TextIO):
    config, constants = get_config_and_constants()
    full_block = json.load(file)
    ref_list = full_block["block"]["transactions_generator_ref_list"]
    args = ref_list_to_args(ref_list)
    npc_list = run_generator_with_args(full_block["block"]["transactions_generator"], args, constants)
    npc_list_json = json.dumps([npc_to_dict(n) for n in npc_list])
    print(npc_list_json)


def get_config_and_constants():
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    network = config["selected_network"]
    overrides = config["network_overrides"]["constants"][network]
    updated_constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
    return config, updated_constants


if __name__ == "__main__":
    cmd_run_json_block_file()
