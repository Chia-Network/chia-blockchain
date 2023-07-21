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
from chia.util.ints import uint32, uint64
from tests.conftest import Mode

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
) -> Tuple[List[CoinRecord], List[CoinRecord], FullBlock]:
    """
    This test helper create an extra block after the given blocks that contains the given
    `SpendBundle`, and then invokes `add_block` to ensure that it's accepted (if `expected_err=None`)
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
            genesis_timestamp=uint64(10000),
            time_per_block=10,
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

        return coins_added, coins_removed, newest_block

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
) -> Tuple[List[CoinRecord], List[CoinRecord], FullBlock]:
    blocks = await initial_blocks(bt)
    coin = list(blocks[spend_reward_index].get_included_reward_coins())[0]

    coin_spend = CoinSpend(coin, EASY_PUZZLE, condition_solution)
    spend_bundle = SpendBundle([coin_spend], G2Element())

    # now let's try to create a block with the spend bundle and ensure that it doesn't validate

    return await check_spend_bundle_validity(bt, blocks, spend_bundle, expected_err=expected_err, softfork2=softfork2)


co = ConditionOpcode


class TestConditions:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "opcode, expected_cost",
        [
            (0x100, 100),
            (0x101, 106),
            (0x102, 112),
            (0x103, 119),
            (0x107, 152),
            (0x1F0, 208000000),
            # the pattern repeats for every leading byte
            (0x400, 100),
            (0x401, 106),
            (0x4F0, 208000000),
            (0x4000, 100),
            (0x4001, 106),
            (0x40F0, 208000000),
        ],
    )
    async def test_unknown_conditions_with_cost(
        self,
        opcode: int,
        expected_cost: int,
        bt,
        consensus_mode: Mode,
    ):
        conditions = Program.to(assemble(f"(({opcode} 1337))"))
        additions, removals, new_block = await check_conditions(bt, conditions)

        if consensus_mode != Mode.HARD_FORK_2_0:
            # before the hard fork, all unknown conditions have 0 cost
            expected_cost = 0

        block_base_cost = 761056
        assert new_block.transactions_info is not None
        assert new_block.transactions_info.cost - block_base_cost == expected_cost

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "condition, expected_cost",
        [
            ("((90 1337))", 13370000),
            ("((90 30000))", 300000000),
        ],
    )
    async def test_softfork_condition(
        self,
        condition: str,
        expected_cost: int,
        bt,
        consensus_mode: Mode,
    ):
        conditions = Program.to(assemble(condition))
        additions, removals, new_block = await check_conditions(bt, conditions)

        if consensus_mode != Mode.HARD_FORK_2_0:
            # the SOFTFORK condition is not recognized before the hard fork
            expected_cost = 0

        # this includes the cost of the bytes for the condition with 2 bytes
        # argument. This test works as long as the conditions it's parameterized
        # on has the same size
        block_base_cost = 737056
        assert new_block.transactions_info is not None
        assert new_block.transactions_info.cost - block_base_cost == expected_cost

    @pytest.mark.asyncio
    @pytest.mark.parametrize("softfork2", [True, False])
    @pytest.mark.parametrize(
        "opcode,value,expected",
        [
            # the chain has 4 blocks, the spend is happening in the 5th block
            # the coin being spent was created in the 3rd block (i.e. block 2)
            # ensure invalid heights fail and pass correctly, depending on
            # which end of the range they exceed
            # genesis timestamp is 10000 and each block is 10 seconds
            # MY BIRTH HEIGHT
            (co.ASSERT_MY_BIRTH_HEIGHT, -1, Err.ASSERT_MY_BIRTH_HEIGHT_FAILED),
            (co.ASSERT_MY_BIRTH_HEIGHT, 0x100000000, Err.ASSERT_MY_BIRTH_HEIGHT_FAILED),
            (co.ASSERT_MY_BIRTH_HEIGHT, 3, Err.ASSERT_MY_BIRTH_HEIGHT_FAILED),
            (co.ASSERT_MY_BIRTH_HEIGHT, 2, None),
            # MY BIRTH SECONDS
            (co.ASSERT_MY_BIRTH_SECONDS, -1, Err.ASSERT_MY_BIRTH_SECONDS_FAILED),
            (co.ASSERT_MY_BIRTH_SECONDS, 0x10000000000000000, Err.ASSERT_MY_BIRTH_SECONDS_FAILED),
            (co.ASSERT_MY_BIRTH_SECONDS, 10019, Err.ASSERT_MY_BIRTH_SECONDS_FAILED),
            (co.ASSERT_MY_BIRTH_SECONDS, 10020, None),
            (co.ASSERT_MY_BIRTH_SECONDS, 10021, Err.ASSERT_MY_BIRTH_SECONDS_FAILED),
            # HEIGHT RELATIVE
            (co.ASSERT_HEIGHT_RELATIVE, -1, None),
            (co.ASSERT_HEIGHT_RELATIVE, 0, None),
            (co.ASSERT_HEIGHT_RELATIVE, 1, None),
            (co.ASSERT_HEIGHT_RELATIVE, 2, Err.ASSERT_HEIGHT_RELATIVE_FAILED),
            (co.ASSERT_HEIGHT_RELATIVE, 0x100000000, Err.ASSERT_HEIGHT_RELATIVE_FAILED),
            # BEFORE HEIGHT RELATIVE
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, -1, Err.ASSERT_BEFORE_HEIGHT_RELATIVE_FAILED),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 0, Err.ASSERT_BEFORE_HEIGHT_RELATIVE_FAILED),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 1, Err.ASSERT_BEFORE_HEIGHT_RELATIVE_FAILED),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 2, None),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 0x100000000, None),
            # HEIGHT ABSOLUTE
            (co.ASSERT_HEIGHT_ABSOLUTE, -1, None),
            (co.ASSERT_HEIGHT_ABSOLUTE, 0, None),
            (co.ASSERT_HEIGHT_ABSOLUTE, 3, None),
            (co.ASSERT_HEIGHT_ABSOLUTE, 4, Err.ASSERT_HEIGHT_ABSOLUTE_FAILED),
            (co.ASSERT_HEIGHT_ABSOLUTE, 0x100000000, Err.ASSERT_HEIGHT_ABSOLUTE_FAILED),
            # BEFORE HEIGHT ABSOLUTE
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, -1, Err.ASSERT_BEFORE_HEIGHT_ABSOLUTE_FAILED),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 0, Err.IMPOSSIBLE_HEIGHT_ABSOLUTE_CONSTRAINTS),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 3, Err.ASSERT_BEFORE_HEIGHT_ABSOLUTE_FAILED),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 4, None),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 0x100000000, None),
            # SECONDS RELATIVE
            (co.ASSERT_SECONDS_RELATIVE, -1, None),
            (co.ASSERT_SECONDS_RELATIVE, 0, None),
            (co.ASSERT_SECONDS_RELATIVE, 10, None),
            (co.ASSERT_SECONDS_RELATIVE, 11, Err.ASSERT_SECONDS_RELATIVE_FAILED),
            (co.ASSERT_SECONDS_RELATIVE, 20, Err.ASSERT_SECONDS_RELATIVE_FAILED),
            (co.ASSERT_SECONDS_RELATIVE, 21, Err.ASSERT_SECONDS_RELATIVE_FAILED),
            (co.ASSERT_SECONDS_RELATIVE, 30, Err.ASSERT_SECONDS_RELATIVE_FAILED),
            (co.ASSERT_SECONDS_RELATIVE, 0x10000000000000000, Err.ASSERT_SECONDS_RELATIVE_FAILED),
            # BEFORE SECONDS RELATIVE
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, -1, Err.ASSERT_BEFORE_SECONDS_RELATIVE_FAILED),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 0, Err.ASSERT_BEFORE_SECONDS_RELATIVE_FAILED),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 10, Err.ASSERT_BEFORE_SECONDS_RELATIVE_FAILED),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 11, None),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 20, None),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 21, None),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 30, None),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 0x100000000000000, None),
            # SECONDS ABSOLUTE
            (co.ASSERT_SECONDS_ABSOLUTE, -1, None),
            (co.ASSERT_SECONDS_ABSOLUTE, 0, None),
            (co.ASSERT_SECONDS_ABSOLUTE, 10000, None),
            (co.ASSERT_SECONDS_ABSOLUTE, 10030, None),
            (co.ASSERT_SECONDS_ABSOLUTE, 10031, Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
            (co.ASSERT_SECONDS_ABSOLUTE, 10039, Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
            (co.ASSERT_SECONDS_ABSOLUTE, 10040, Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
            (co.ASSERT_SECONDS_ABSOLUTE, 10041, Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
            (co.ASSERT_SECONDS_ABSOLUTE, 0x10000000000000000, Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
            # BEFORE SECONDS ABSOLUTE
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, -1, Err.ASSERT_BEFORE_SECONDS_ABSOLUTE_FAILED),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 0, Err.IMPOSSIBLE_SECONDS_ABSOLUTE_CONSTRAINTS),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10000, Err.ASSERT_BEFORE_SECONDS_ABSOLUTE_FAILED),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10030, Err.ASSERT_BEFORE_SECONDS_ABSOLUTE_FAILED),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10031, None),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10039, None),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10040, None),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10041, None),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 0x100000000, None),
        ],
    )
    async def test_condition(self, opcode, value, expected, bt, softfork2):
        conditions = Program.to(assemble(f"(({opcode[0]} {value}))"))

        # when soft fork 2 is not active, these conditions are also not active,
        # and never constrain the block
        if not softfork2 and opcode in [
            co.ASSERT_MY_BIRTH_HEIGHT,
            co.ASSERT_MY_BIRTH_SECONDS,
            co.ASSERT_BEFORE_SECONDS_RELATIVE,
            co.ASSERT_BEFORE_SECONDS_ABSOLUTE,
            co.ASSERT_BEFORE_HEIGHT_RELATIVE,
            co.ASSERT_BEFORE_HEIGHT_ABSOLUTE,
        ]:
            expected = None

        if not softfork2:
            # before soft-fork 2, the timestamp we compared against was the
            # current block's timestamp as opposed to the previous tx-block's
            # timestamp. These conditions used to be valid, before the soft-fork
            if opcode == ConditionOpcode.ASSERT_SECONDS_RELATIVE and value > 10 and value <= 20:
                expected = None

            if opcode == ConditionOpcode.ASSERT_SECONDS_ABSOLUTE and value > 10030 and value <= 10040:
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

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "prefix, condition, num, expect_err",
        [
            # CREATE_COIN_ANNOUNCEMENT
            ("", "(60 'test')", 1024, None),
            ("", "(60 'test')", 1025, Err.TOO_MANY_ANNOUNCEMENTS),
            # CREATE_PUZZLE_ANNOUNCEMENT
            ("", "(62 'test')", 1024, None),
            ("", "(62 'test')", 1025, Err.TOO_MANY_ANNOUNCEMENTS),
            # ASSERT_PUZZLE_ANNOUNCEMENT
            ("(62 'test')", "(63 {pann})", 1023, None),
            ("(62 'test')", "(63 {pann})", 1024, Err.TOO_MANY_ANNOUNCEMENTS),
            # ASSERT_COIN_ANNOUNCEMENT
            ("(60 'test')", "(61 {cann})", 1023, None),
            ("(60 'test')", "(61 {cann})", 1024, Err.TOO_MANY_ANNOUNCEMENTS),
            # ASSERT_CONCURRENT_SPEND
            ("", "(64 {coin})", 1024, None),
            ("", "(64 {coin})", 1025, Err.TOO_MANY_ANNOUNCEMENTS),
            # ASSERT_CONCURRENT_PUZZLE
            ("", "(65 {ph})", 1024, None),
            ("", "(65 {ph})", 1025, Err.TOO_MANY_ANNOUNCEMENTS),
        ],
    )
    async def test_announce_conditions_limit(
        self,
        consensus_mode: Mode,
        prefix: str,
        condition: str,
        num: int,
        expect_err: Optional[Err],
        bt: BlockTools,
    ):
        """
        Test that the condition checker accepts more announcements than the new per puzzle limit
        pre-v2-softfork, and rejects more than the announcement limit afterward.
        """

        if consensus_mode != Mode.SOFT_FORK3:
            # before softfork 3, there was no limit on the number of
            # announcements
            expect_err = None

        blocks = await initial_blocks(bt)
        coin = list(blocks[-2].get_included_reward_coins())[0]
        coin_announcement = Announcement(coin.name(), b"test")
        puzzle_announcement = Announcement(EASY_PUZZLE_HASH, b"test")

        conditions = b""
        if prefix != "":
            conditions += b"\xff" + assemble(prefix).as_bin()

        cond = condition.format(
            coin="0x" + coin.name().hex(),
            ph="0x" + EASY_PUZZLE_HASH.hex(),
            cann="0x" + coin_announcement.name().hex(),
            pann="0x" + puzzle_announcement.name().hex(),
        )

        conditions += (b"\xff" + assemble(cond).as_bin()) * num
        conditions += b"\x80"
        conditions_program = Program.from_bytes(conditions)

        await check_conditions(bt, conditions_program, expected_err=expect_err, softfork2=True)
