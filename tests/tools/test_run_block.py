import json
from pathlib import Path
from typing import List, Tuple

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from tools.run_block import run_json_block

testnet10 = {
    "AGG_SIG_ME_ADDITIONAL_DATA": bytes.fromhex("ae83525ba8d1dd3f09b277de18ca3e43fc0af20d20c4b3e92ef2a48bd291ccb2"),
    "DIFFICULTY_CONSTANT_FACTOR": 10052721566054,
    "DIFFICULTY_STARTING": 30,
    "EPOCH_BLOCKS": 768,
    "GENESIS_CHALLENGE": bytes.fromhex("ae83525ba8d1dd3f09b277de18ca3e43fc0af20d20c4b3e92ef2a48bd291ccb2"),
    "GENESIS_PRE_FARM_FARMER_PUZZLE_HASH": bytes.fromhex(
        "3d8765d3a597ec1d99663f6c9816d915b9f68613ac94009884c4addaefcce6af"
    ),
    "GENESIS_PRE_FARM_POOL_PUZZLE_HASH": bytes.fromhex(
        "d23da14695a188ae5708dd152263c4db883eb27edeb936178d4d988b8f3ce5fc"
    ),
    "MEMPOOL_BLOCK_BUFFER": 10,
    "MIN_PLOT_SIZE": 18,
    "NETWORK_TYPE": 1,
}

constants = DEFAULT_CONSTANTS.replace(**testnet10)
retire_bytes = (
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
)


def find_retirement(tocheck: List[ConditionWithArgs]) -> bool:
    for c in tocheck:
        if c.opcode != ConditionOpcode.CREATE_COIN:
            continue
        if len(c.vars) < 3:
            continue
        if c.vars[2] == retire_bytes:
            return True

    return False


def test_block_no_generator():
    dirname = Path(__file__).parent
    with open(dirname / "300000.json") as f:
        full_block = json.load(f)

    cat_list = run_json_block(full_block, constants)

    assert not cat_list


def test_block_retired_cat_with_memo():
    dirname = Path(__file__).parent
    with open(dirname / "396963.json") as f:
        full_block = json.load(f)

    cat_list = run_json_block(full_block, constants)

    assert cat_list
    assert cat_list[0].tail_hash == "86bf9abe0600edf96b2e0fa928d19435b5aa756a9c9151c4b53c2c3da258502f"
    assert cat_list[0].memo == "Hello, please find me, I'm a memo!"
    first_condition: Tuple[ConditionOpcode, List[ConditionWithArgs]] = cat_list[0].npc.conditions[0]
    assert first_condition[0] == ConditionOpcode.CREATE_COIN
    assert find_retirement(first_condition[1])


def test_block_retired_cat_no_memo():
    dirname = Path(__file__).parent
    with open(dirname / "392111.json") as f:
        full_block = json.load(f)

    cat_list = run_json_block(full_block, constants)

    assert cat_list
    assert cat_list[0].tail_hash == "86bf9abe0600edf96b2e0fa928d19435b5aa756a9c9151c4b53c2c3da258502f"
    assert not cat_list[0].memo
    first_condition: Tuple[ConditionOpcode, List[ConditionWithArgs]] = cat_list[0].npc.conditions[0]
    assert first_condition[0] == ConditionOpcode.CREATE_COIN
    assert find_retirement(first_condition[1])


def test_block_cat():
    dirname = Path(__file__).parent
    with open(dirname / "149988.json") as f:
        full_block = json.load(f)

    cat_list = run_json_block(full_block, constants)

    assert cat_list
    assert cat_list[0].tail_hash == "8829a36776a15477a7f41f8fb6397752922374b60be7d3b2d7881c54b86b32a1"
    assert not cat_list[0].memo
