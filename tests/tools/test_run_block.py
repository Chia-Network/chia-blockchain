from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import List

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.util.ints import uint32, uint64, uint128
from tools.run_block import run_json_block

constants = dataclasses.replace(
    DEFAULT_CONSTANTS,
    AGG_SIG_ME_ADDITIONAL_DATA=bytes.fromhex("ae83525ba8d1dd3f09b277de18ca3e43fc0af20d20c4b3e92ef2a48bd291ccb2"),
    DIFFICULTY_CONSTANT_FACTOR=uint128(10052721566054),
    DIFFICULTY_STARTING=uint64(30),
    EPOCH_BLOCKS=uint32(768),
    GENESIS_CHALLENGE=bytes32.fromhex("ae83525ba8d1dd3f09b277de18ca3e43fc0af20d20c4b3e92ef2a48bd291ccb2"),
    GENESIS_PRE_FARM_FARMER_PUZZLE_HASH=bytes32.fromhex(
        "3d8765d3a597ec1d99663f6c9816d915b9f68613ac94009884c4addaefcce6af"
    ),
    GENESIS_PRE_FARM_POOL_PUZZLE_HASH=bytes32.fromhex(
        "d23da14695a188ae5708dd152263c4db883eb27edeb936178d4d988b8f3ce5fc"
    ),
    MEMPOOL_BLOCK_BUFFER=10,
    MIN_PLOT_SIZE=18,
)
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

    cat_list = run_json_block(full_block, dirname, constants)

    assert not cat_list


def test_block_retired_cat_with_memo():
    dirname = Path(__file__).parent
    with open(dirname / "1315630.json") as f:
        full_block = json.load(f)

    cat_list = run_json_block(full_block, dirname, constants)

    assert cat_list
    assert cat_list[0].asset_id == "c2808f37e758b713150da4860091dd94a90a781bc4f18377d20de6291b3d506d"
    assert cat_list[0].memo == "Hello, please find me, I'm a memo!"
    assert cat_list[0].npc.coin_name.hex() == "cc6dca2748865d77eb411e3a44827ad970a0cd8488ad26f6a83842fe4e0e4054"
    assert cat_list[0].npc.puzzle_hash.hex() == "c621cd597aa525338d3e4e499a34e0d0b1040304a2f4766b48a368aa57d3ab6f"
    found = False
    for cond in cat_list[0].npc.conditions:
        if cond[0] != ConditionOpcode.CREATE_COIN:
            continue
        found |= find_retirement(cond[1])
    assert found


def test_block_retired_cat_no_memo():
    dirname = Path(__file__).parent
    with open(dirname / "1315544.json") as f:
        full_block = json.load(f)

    cat_list = run_json_block(full_block, dirname, constants)

    assert cat_list
    assert cat_list[0].asset_id == "c2808f37e758b713150da4860091dd94a90a781bc4f18377d20de6291b3d506d"
    assert not cat_list[0].memo
    assert cat_list[0].npc.coin_name.hex() == "90941ac42b92aad0ed1de5d599d854072fcf1f4bb82cd37e365852f0a730cf5d"
    assert cat_list[0].npc.puzzle_hash.hex() == "20a2284ec41cdcc3c54e6b44f8801db2dc28f3aa01c115674b598757d62f09a6"

    found = False
    for cond in cat_list[0].npc.conditions:
        if cond[0] != ConditionOpcode.CREATE_COIN:
            continue
        found |= find_retirement(cond[1])
    assert found


def test_block_cat():
    dirname = Path(__file__).parent
    with open(dirname / "1315537.json") as f:
        full_block = json.load(f)

    cat_list = run_json_block(full_block, dirname, constants)

    assert cat_list
    assert cat_list[0].asset_id == "c2808f37e758b713150da4860091dd94a90a781bc4f18377d20de6291b3d506d"
    assert not cat_list[0].memo
    assert cat_list[0].npc.coin_name.hex() == "6fb12ab32556537803112badcfaf828bfe1b79eb4181b3adc5d571680295ce6c"
    assert cat_list[0].npc.puzzle_hash.hex() == "20a2284ec41cdcc3c54e6b44f8801db2dc28f3aa01c115674b598757d62f09a6"


def test_generator_ref():
    """Run a block containing a back reference without error"""
    dirname = Path(__file__).parent
    with open(dirname / "466212.json") as f:
        full_block = json.load(f)

    cat_list = run_json_block(full_block, dirname, constants)

    assert cat_list == []
