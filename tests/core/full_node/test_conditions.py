"""
These are quick-to-run test that check spends can be added to the blockchain when they're valid
or that they're failing for the right reason when they're invalid.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import pytest
from blspy import G2Element
from clvm_tools.binutils import assemble

from chia.simulator.block_tools import BlockTools
from chia.simulator.keyring import TempKeyring
from chia.types.announcement import Announcement
from chia.types.blockchain_format.program import Program
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.full_block import FullBlock
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.util.ints import uint32

from ...blockchain.blockchain_test_utils import _validate_and_add_block
from .ram_db import create_ram_blockchain


def cleanup_keyring(keyring: TempKeyring):
    keyring.cleanup()


log = logging.getLogger(__name__)


# This puzzle simply returns the solution as conditions.
# We call it the `EASY_PUZZLE` because it's pretty easy to solve.

EASY_PUZZLE = Program.to(assemble("1"))
EASY_PUZZLE_HASH = EASY_PUZZLE.get_tree_hash()


async def initial_blocks(bt, block_count: int = 4) -> List[FullBlock]:
    blocks = bt.get_consecutive_blocks(
        block_count,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=EASY_PUZZLE_HASH,
        pool_reward_puzzle_hash=EASY_PUZZLE_HASH,
        genesis_timestamp=10000,
        time_per_block=10,
    )
    return blocks


async def check_spend_bundle_validity(
    bt: BlockTools,
    blocks: List[FullBlock],
    spend_bundle: SpendBundle,
    expected_err: Optional[Err] = None,
    softfork2: bool = False,
) -> Tuple[List[CoinRecord], List[CoinRecord]]:
    """
    This test helper create an extra block after the given blocks that contains the given
    `SpendBundle`, and then invokes `receive_block` to ensure that it's accepted (if `expected_err=None`)
    or fails with the correct error code.
    """
    if softfork2:
        constants = bt.constants.replace(SOFT_FORK2_HEIGHT=0)
    else:
        constants = bt.constants

    db_wrapper, blockchain = await create_ram_blockchain(constants)
    try:
        for block in blocks:
            await _validate_and_add_block(blockchain, block)

        additional_blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=spend_bundle,
        )
        newest_block = additional_blocks[-1]

        if expected_err is None:
            await _validate_and_add_block(blockchain, newest_block)
            coins_added = await blockchain.coin_store.get_coins_added_at_height(uint32(len(blocks)))
            coins_removed = await blockchain.coin_store.get_coins_removed_at_height(uint32(len(blocks)))
        else:
            await _validate_and_add_block(blockchain, newest_block, expected_error=expected_err)
            coins_added = []
            coins_removed = []

        return coins_added, coins_removed

    finally:
        # if we don't close the db_wrapper, the test process doesn't exit cleanly
        await db_wrapper.close()

        # we must call `shut_down` or the executor in `Blockchain` doesn't stop
        blockchain.shut_down()


async def check_conditions(
    bt: BlockTools,
    condition_solution: Program,
    expected_err: Optional[Err] = None,
    spend_reward_index: int = -2,
    softfork2: bool = False,
):
    blocks = await initial_blocks(bt)
    coin = list(blocks[spend_reward_index].get_included_reward_coins())[0]

    coin_spend = CoinSpend(coin, EASY_PUZZLE, condition_solution)
    spend_bundle = SpendBundle([coin_spend], G2Element())

    # now let's try to create a block with the spend bundle and ensure that it doesn't validate

    await check_spend_bundle_validity(bt, blocks, spend_bundle, expected_err=expected_err, softfork2=softfork2)


co = ConditionOpcode


class TestConditions:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("softfork2", [True, False])
    @pytest.mark.parametrize(
        "opcode,value,expected",
        [
            # the chain has 4 blocks, the spend is happening in the 5th block
            # the coin being spent was created in the 3rd block (i.e. block 2)
            # ensure invalid heights fail and pass correctly, depending on
            # which end of the range they exceed
            (co.ASSERT_MY_BIRTH_HEIGHT, -1, Err.ASSERT_MY_BIRTH_HEIGHT_FAILED),
            (co.ASSERT_MY_BIRTH_HEIGHT, 0x100000000, Err.ASSERT_MY_BIRTH_HEIGHT_FAILED),
            (co.ASSERT_MY_BIRTH_HEIGHT, 3, Err.ASSERT_MY_BIRTH_HEIGHT_FAILED),
            (co.ASSERT_MY_BIRTH_HEIGHT, 2, None),
            # genesis timestamp is 10000 and each block is 10 seconds
            (co.ASSERT_MY_BIRTH_SECONDS, -1, Err.ASSERT_MY_BIRTH_SECONDS_FAILED),
            (co.ASSERT_MY_BIRTH_SECONDS, 0x10000000000000000, Err.ASSERT_MY_BIRTH_SECONDS_FAILED),
            (co.ASSERT_MY_BIRTH_SECONDS, 10019, Err.ASSERT_MY_BIRTH_SECONDS_FAILED),
            (co.ASSERT_MY_BIRTH_SECONDS, 10020, None),
            (co.ASSERT_MY_BIRTH_SECONDS, 10021, Err.ASSERT_MY_BIRTH_SECONDS_FAILED),
            (co.ASSERT_HEIGHT_RELATIVE, -1, None),
            (co.ASSERT_HEIGHT_RELATIVE, 0, None),
            (co.ASSERT_HEIGHT_RELATIVE, 0x100000000, Err.ASSERT_HEIGHT_RELATIVE_FAILED),
            (co.ASSERT_HEIGHT_ABSOLUTE, -1, None),
            (co.ASSERT_HEIGHT_ABSOLUTE, 0, None),
            (co.ASSERT_HEIGHT_ABSOLUTE, 0x100000000, Err.ASSERT_HEIGHT_ABSOLUTE_FAILED),
            (co.ASSERT_SECONDS_RELATIVE, -1, None),
            (co.ASSERT_SECONDS_RELATIVE, 0, None),
            (co.ASSERT_SECONDS_RELATIVE, 0x10000000000000000, Err.ASSERT_SECONDS_RELATIVE_FAILED),
            (co.ASSERT_SECONDS_ABSOLUTE, -1, None),
            (co.ASSERT_SECONDS_ABSOLUTE, 0, None),
            (co.ASSERT_SECONDS_ABSOLUTE, 0x10000000000000000, Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
            # test boundary values
            (co.ASSERT_HEIGHT_RELATIVE, 2, Err.ASSERT_HEIGHT_RELATIVE_FAILED),
            (co.ASSERT_HEIGHT_RELATIVE, 1, None),
            (co.ASSERT_HEIGHT_ABSOLUTE, 4, Err.ASSERT_HEIGHT_ABSOLUTE_FAILED),
            (co.ASSERT_HEIGHT_ABSOLUTE, 3, None),
            # genesis timestamp is 10000 and each block is 10 seconds
            (co.ASSERT_SECONDS_ABSOLUTE, 10049, Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
            (co.ASSERT_SECONDS_ABSOLUTE, 10000, None),
            (co.ASSERT_SECONDS_RELATIVE, 30, Err.ASSERT_SECONDS_RELATIVE_FAILED),
            (co.ASSERT_SECONDS_RELATIVE, 0, None),
        ],
    )
    async def test_condition(self, opcode, value, expected, bt, softfork2):
        conditions = Program.to(assemble(f"(({opcode[0]} {value}))"))

        # when soft fork 2 is not active, these conditions are also not active,
        # and never constrain the block
        if not softfork2 and opcode in [
            co.ASSERT_MY_BIRTH_HEIGHT,
            co.ASSERT_MY_BIRTH_SECONDS,
        ]:
            expected = None

        await check_conditions(bt, conditions, expected_err=expected, softfork2=softfork2)

    @pytest.mark.asyncio
    async def test_invalid_my_id(self, bt):
        blocks = await initial_blocks(bt)
        coin = list(blocks[-2].get_included_reward_coins())[0]
        wrong_name = bytearray(coin.name())
        wrong_name[-1] ^= 1
        conditions = Program.to(assemble(f"(({ConditionOpcode.ASSERT_MY_COIN_ID[0]} 0x{wrong_name.hex()}))"))
        await check_conditions(bt, conditions, expected_err=Err.ASSERT_MY_COIN_ID_FAILED)

    @pytest.mark.asyncio
    async def test_valid_my_id(self, bt):
        blocks = await initial_blocks(bt)
        coin = list(blocks[-2].get_included_reward_coins())[0]
        conditions = Program.to(assemble(f"(({ConditionOpcode.ASSERT_MY_COIN_ID[0]} 0x{coin.name().hex()}))"))
        await check_conditions(bt, conditions)

    @pytest.mark.asyncio
    async def test_invalid_coin_announcement(self, bt):
        blocks = await initial_blocks(bt)
        coin = list(blocks[-2].get_included_reward_coins())[0]
        announce = Announcement(coin.name(), b"test_bad")
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.CREATE_COIN_ANNOUNCEMENT[0]} 'test')"
                f"({ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT[0]} 0x{announce.name().hex()}))"
            )
        )
        await check_conditions(bt, conditions, expected_err=Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

    @pytest.mark.asyncio
    async def test_valid_coin_announcement(self, bt):
        blocks = await initial_blocks(bt)
        coin = list(blocks[-2].get_included_reward_coins())[0]
        announce = Announcement(coin.name(), b"test")
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.CREATE_COIN_ANNOUNCEMENT[0]} 'test')"
                f"({ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT[0]} 0x{announce.name().hex()}))"
            )
        )
        await check_conditions(bt, conditions)

    @pytest.mark.asyncio
    async def test_invalid_puzzle_announcement(self, bt):
        announce = Announcement(EASY_PUZZLE_HASH, b"test_bad")
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT[0]} 'test')"
                f"({ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT[0]} 0x{announce.name().hex()}))"
            )
        )
        await check_conditions(bt, conditions, expected_err=Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

    @pytest.mark.asyncio
    async def test_valid_puzzle_announcement(self, bt):
        announce = Announcement(EASY_PUZZLE_HASH, b"test")
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT[0]} 'test')"
                f"({ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT[0]} 0x{announce.name().hex()}))"
            )
        )
        await check_conditions(bt, conditions)
