"""
These are quick-to-run test that check spends can be added to the blockchain when they're valid
or that they're failing for the right reason when they're invalid.
"""

import atexit
import logging
import time

from typing import List, Optional, Tuple

import pytest

from blspy import G2Element

from clvm_tools.binutils import assemble

from chia.consensus.constants import ConsensusConstants
from chia.types.announcement import Announcement
from chia.types.blockchain_format.program import Program
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.full_block import FullBlock
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.util.ints import uint32
from tests.block_tools import create_block_tools, test_constants
from tests.util.keyring import TempKeyring

from .ram_db import create_ram_blockchain
from ...blockchain.blockchain_test_utils import _validate_and_add_block


def cleanup_keyring(keyring: TempKeyring):
    keyring.cleanup()


temp_keyring = TempKeyring()
keychain = temp_keyring.get_keychain()
atexit.register(cleanup_keyring, temp_keyring)  # Attempt to cleanup the temp keychain
bt = create_block_tools(constants=test_constants, keychain=keychain)


log = logging.getLogger(__name__)


# This puzzle simply returns the solution as conditions.
# We call it the `EASY_PUZZLE` because it's pretty easy to solve.

EASY_PUZZLE = Program.to(assemble("1"))
EASY_PUZZLE_HASH = EASY_PUZZLE.get_tree_hash()


def initial_blocks(block_count: int = 4) -> List[FullBlock]:
    blocks = bt.get_consecutive_blocks(
        block_count,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=EASY_PUZZLE_HASH,
        pool_reward_puzzle_hash=EASY_PUZZLE_HASH,
    )
    return blocks


async def check_spend_bundle_validity(
    constants: ConsensusConstants,
    blocks: List[FullBlock],
    spend_bundle: SpendBundle,
    expected_err: Optional[Err] = None,
) -> Tuple[List[CoinRecord], List[CoinRecord]]:
    """
    This test helper create an extra block after the given blocks that contains the given
    `SpendBundle`, and then invokes `receive_block` to ensure that it's accepted (if `expected_err=None`)
    or fails with the correct error code.
    """
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
    condition_solution: Program, expected_err: Optional[Err] = None, spend_reward_index: int = -2
):
    blocks = initial_blocks()
    coin = list(blocks[spend_reward_index].get_included_reward_coins())[0]

    coin_spend = CoinSpend(coin, EASY_PUZZLE, condition_solution)
    spend_bundle = SpendBundle([coin_spend], G2Element())

    # now let's try to create a block with the spend bundle and ensure that it doesn't validate

    await check_spend_bundle_validity(bt.constants, blocks, spend_bundle, expected_err=expected_err)


class TestConditions:
    @pytest.mark.asyncio
    async def test_invalid_block_age(self):
        conditions = Program.to(assemble(f"(({ConditionOpcode.ASSERT_HEIGHT_RELATIVE[0]} 2))"))
        await check_conditions(conditions, expected_err=Err.ASSERT_HEIGHT_RELATIVE_FAILED)

    @pytest.mark.asyncio
    async def test_valid_block_age(self):
        conditions = Program.to(assemble(f"(({ConditionOpcode.ASSERT_HEIGHT_RELATIVE[0]} 1))"))
        await check_conditions(conditions)

    @pytest.mark.asyncio
    async def test_invalid_block_height(self):
        conditions = Program.to(assemble(f"(({ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE[0]} 4))"))
        await check_conditions(conditions, expected_err=Err.ASSERT_HEIGHT_ABSOLUTE_FAILED)

    @pytest.mark.asyncio
    async def test_valid_block_height(self):
        conditions = Program.to(assemble(f"(({ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE[0]} 3))"))
        await check_conditions(conditions)

    @pytest.mark.asyncio
    async def test_invalid_my_id(self):
        blocks = initial_blocks()
        coin = list(blocks[-2].get_included_reward_coins())[0]
        wrong_name = bytearray(coin.name())
        wrong_name[-1] ^= 1
        conditions = Program.to(assemble(f"(({ConditionOpcode.ASSERT_MY_COIN_ID[0]} 0x{wrong_name.hex()}))"))
        await check_conditions(conditions, expected_err=Err.ASSERT_MY_COIN_ID_FAILED)

    @pytest.mark.asyncio
    async def test_valid_my_id(self):
        blocks = initial_blocks()
        coin = list(blocks[-2].get_included_reward_coins())[0]
        conditions = Program.to(assemble(f"(({ConditionOpcode.ASSERT_MY_COIN_ID[0]} 0x{coin.name().hex()}))"))
        await check_conditions(conditions)

    @pytest.mark.asyncio
    async def test_invalid_seconds_absolute(self):
        # TODO: make the test suite not use `time.time` so we can more accurately
        # set `time_now` to make it minimal while still failing
        time_now = int(time.time()) + 3000
        conditions = Program.to(assemble(f"(({ConditionOpcode.ASSERT_SECONDS_ABSOLUTE[0]} {time_now}))"))
        await check_conditions(conditions, expected_err=Err.ASSERT_SECONDS_ABSOLUTE_FAILED)

    @pytest.mark.asyncio
    async def test_valid_seconds_absolute(self):
        time_now = int(time.time())
        conditions = Program.to(assemble(f"(({ConditionOpcode.ASSERT_SECONDS_ABSOLUTE[0]} {time_now}))"))
        await check_conditions(conditions)

    @pytest.mark.asyncio
    async def test_invalid_coin_announcement(self):
        blocks = initial_blocks()
        coin = list(blocks[-2].get_included_reward_coins())[0]
        announce = Announcement(coin.name(), b"test_bad")
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.CREATE_COIN_ANNOUNCEMENT[0]} 'test')"
                f"({ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT[0]} 0x{announce.name().hex()}))"
            )
        )
        await check_conditions(conditions, expected_err=Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

    @pytest.mark.asyncio
    async def test_valid_coin_announcement(self):
        blocks = initial_blocks()
        coin = list(blocks[-2].get_included_reward_coins())[0]
        announce = Announcement(coin.name(), b"test")
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.CREATE_COIN_ANNOUNCEMENT[0]} 'test')"
                f"({ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT[0]} 0x{announce.name().hex()}))"
            )
        )
        await check_conditions(conditions)

    @pytest.mark.asyncio
    async def test_invalid_puzzle_announcement(self):
        announce = Announcement(EASY_PUZZLE_HASH, b"test_bad")
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT[0]} 'test')"
                f"({ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT[0]} 0x{announce.name().hex()}))"
            )
        )
        await check_conditions(conditions, expected_err=Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

    @pytest.mark.asyncio
    async def test_valid_puzzle_announcement(self):
        announce = Announcement(EASY_PUZZLE_HASH, b"test")
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT[0]} 'test')"
                f"({ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT[0]} 0x{announce.name().hex()}))"
            )
        )
        await check_conditions(conditions)
