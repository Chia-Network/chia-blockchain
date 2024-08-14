"""
These are quick-to-run test that check spends can be added to the blockchain when they're valid
or that they're failing for the right reason when they're invalid.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import pytest
from chia_rs import AugSchemeMPL, G2Element
from clvm.casts import int_to_bytes
from clvm_tools.binutils import assemble

from chia._tests.conftest import ConsensusMode
from chia.simulator.block_tools import BlockTools
from chia.simulator.keyring import TempKeyring
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.full_block import FullBlock
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import agg_sig_additional_data
from chia.util.errors import Err
from chia.util.ints import uint32, uint64
from chia.wallet.conditions import AssertCoinAnnouncement, AssertPuzzleAnnouncement

from ...blockchain.blockchain_test_utils import _validate_and_add_block
from .ram_db import create_ram_blockchain


def cleanup_keyring(keyring: TempKeyring) -> None:
    keyring.cleanup()


log = logging.getLogger(__name__)


# This puzzle simply returns the solution as conditions.
# We call it the `EASY_PUZZLE` because it's pretty easy to solve.

EASY_PUZZLE = SerializedProgram.from_bytes(b"\x01")
EASY_PUZZLE_HASH = EASY_PUZZLE.get_tree_hash()


async def initial_blocks(bt: BlockTools, block_count: int = 4) -> List[FullBlock]:
    blocks = bt.get_consecutive_blocks(
        block_count,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=EASY_PUZZLE_HASH,
        pool_reward_puzzle_hash=EASY_PUZZLE_HASH,
        genesis_timestamp=uint64(10000),
        time_per_block=10,
    )
    return blocks


async def check_spend_bundle_validity(
    bt: BlockTools,
    blocks: List[FullBlock],
    spend_bundle: SpendBundle,
    expected_err: Optional[Err] = None,
) -> Tuple[List[CoinRecord], List[CoinRecord], FullBlock]:
    """
    This test helper create an extra block after the given blocks that contains the given
    `SpendBundle`, and then invokes `add_block` to ensure that it's accepted (if `expected_err=None`)
    or fails with the correct error code.
    """

    async with create_ram_blockchain(bt.constants) as (db_wrapper, blockchain):
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


async def check_conditions(
    bt: BlockTools,
    condition_solution: Program,
    expected_err: Optional[Err] = None,
    spend_reward_index: int = -2,
    *,
    aggsig: G2Element = G2Element(),
) -> Tuple[List[CoinRecord], List[CoinRecord], FullBlock]:
    blocks = await initial_blocks(bt)
    coin = blocks[spend_reward_index].get_included_reward_coins()[0]

    coin_spend = make_spend(coin, EASY_PUZZLE, SerializedProgram.from_program(condition_solution))
    spend_bundle = SpendBundle([coin_spend], aggsig)

    # now let's try to create a block with the spend bundle and ensure that it doesn't validate

    return await check_spend_bundle_validity(bt, blocks, spend_bundle, expected_err=expected_err)


co = ConditionOpcode


class TestConditions:
    @pytest.mark.anyio
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
        self, opcode: int, expected_cost: int, bt: BlockTools, consensus_mode: ConsensusMode
    ) -> None:
        conditions = Program.to(assemble(f"(({opcode} 1337))"))
        additions, removals, new_block = await check_conditions(bt, conditions)

        # once the hard fork activates, blocks no longer pay the cost of the ROM
        # generator (which includes hashing all puzzles).
        if consensus_mode >= ConsensusMode.HARD_FORK_2_0:
            block_base_cost = 756064
        else:
            block_base_cost = 761056
        assert new_block.transactions_info is not None
        assert new_block.transactions_info.cost - block_base_cost == expected_cost

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "condition, expected_cost",
        [
            ("((90 1337))", 13370000),
            ("((90 30000))", 300000000),
        ],
    )
    async def test_softfork_condition(
        self, condition: str, expected_cost: int, bt: BlockTools, consensus_mode: ConsensusMode
    ) -> None:
        conditions = Program.to(assemble(condition))
        additions, removals, new_block = await check_conditions(bt, conditions)

        if consensus_mode < ConsensusMode.HARD_FORK_2_0:
            block_base_cost = 737056
        else:
            # once the hard fork activates, blocks no longer pay the cost of the ROM
            # generator (which includes hashing all puzzles).
            block_base_cost = 732064

        # the block_base_cost includes the cost of the bytes for the condition
        # with 2 bytes argument. This test works as long as the conditions it's
        # parameterized on has the same size
        assert new_block.transactions_info is not None
        assert new_block.transactions_info.cost - block_base_cost == expected_cost

    @pytest.mark.anyio
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
    async def test_condition(self, opcode: ConditionOpcode, value: int, expected: Err, bt: BlockTools) -> None:
        conditions = Program.to(assemble(f"(({opcode[0]} {value}))"))
        await check_conditions(bt, conditions, expected_err=expected)

    @pytest.mark.anyio
    async def test_invalid_my_id(self, bt: BlockTools) -> None:
        blocks = await initial_blocks(bt)
        coin = blocks[-2].get_included_reward_coins()[0]
        wrong_name = bytearray(coin.name())
        wrong_name[-1] ^= 1
        conditions = Program.to(assemble(f"(({ConditionOpcode.ASSERT_MY_COIN_ID[0]} 0x{wrong_name.hex()}))"))
        await check_conditions(bt, conditions, expected_err=Err.ASSERT_MY_COIN_ID_FAILED)

    @pytest.mark.anyio
    async def test_valid_my_id(self, bt: BlockTools) -> None:
        blocks = await initial_blocks(bt)
        coin = blocks[-2].get_included_reward_coins()[0]
        conditions = Program.to(assemble(f"(({ConditionOpcode.ASSERT_MY_COIN_ID[0]} 0x{coin.name().hex()}))"))
        await check_conditions(bt, conditions)

    @pytest.mark.anyio
    async def test_invalid_coin_announcement(self, bt: BlockTools) -> None:
        blocks = await initial_blocks(bt)
        coin = blocks[-2].get_included_reward_coins()[0]
        announce = AssertCoinAnnouncement(asserted_id=coin.name(), asserted_msg=b"test_bad")
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.CREATE_COIN_ANNOUNCEMENT[0]} 'test')"
                f"({ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT[0]} 0x{announce.msg_calc.hex()}))"
            )
        )
        await check_conditions(bt, conditions, expected_err=Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

    @pytest.mark.anyio
    async def test_valid_coin_announcement(self, bt: BlockTools) -> None:
        blocks = await initial_blocks(bt)
        coin = blocks[-2].get_included_reward_coins()[0]
        announce = AssertCoinAnnouncement(asserted_id=coin.name(), asserted_msg=b"test")
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.CREATE_COIN_ANNOUNCEMENT[0]} 'test')"
                f"({ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT[0]} 0x{announce.msg_calc.hex()}))"
            )
        )
        await check_conditions(bt, conditions)

    @pytest.mark.anyio
    async def test_invalid_puzzle_announcement(self, bt: BlockTools) -> None:
        announce = AssertPuzzleAnnouncement(asserted_ph=EASY_PUZZLE_HASH, asserted_msg=b"test_bad")
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT[0]} 'test')"
                f"({ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT[0]} 0x{announce.msg_calc.hex()}))"
            )
        )
        await check_conditions(bt, conditions, expected_err=Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

    @pytest.mark.anyio
    async def test_valid_puzzle_announcement(self, bt: BlockTools) -> None:
        announce = AssertPuzzleAnnouncement(asserted_ph=EASY_PUZZLE_HASH, asserted_msg=b"test")
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT[0]} 'test')"
                f"({ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT[0]} 0x{announce.msg_calc.hex()}))"
            )
        )
        await check_conditions(bt, conditions)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "prefix, condition1, condition2, num, expect_err",
        [
            # CREATE_COIN_ANNOUNCEMENT
            ("", "(60 'test')", "", 1024, None),
            ("", "(60 'test')", "", 1025, Err.TOO_MANY_ANNOUNCEMENTS),
            # CREATE_PUZZLE_ANNOUNCEMENT
            ("", "(62 'test')", "", 1024, None),
            ("", "(62 'test')", "", 1025, Err.TOO_MANY_ANNOUNCEMENTS),
            # ASSERT_PUZZLE_ANNOUNCEMENT
            ("(62 'test')", "(63 {pann})", "", 1023, None),
            ("(62 'test')", "(63 {pann})", "", 1024, Err.TOO_MANY_ANNOUNCEMENTS),
            # ASSERT_COIN_ANNOUNCEMENT
            ("(60 'test')", "(61 {cann})", "", 1023, None),
            ("(60 'test')", "(61 {cann})", "", 1024, Err.TOO_MANY_ANNOUNCEMENTS),
            # ASSERT_CONCURRENT_SPEND
            ("", "(64 {coin})", "", 1024, None),
            ("", "(64 {coin})", "", 1025, Err.TOO_MANY_ANNOUNCEMENTS),
            # ASSERT_CONCURRENT_PUZZLE
            ("", "(65 {ph})", "", 1024, None),
            ("", "(65 {ph})", "", 1025, Err.TOO_MANY_ANNOUNCEMENTS),
            # SEND_MESSAGE
            ("", "(66 0x3f {msg} {coin})", "(67 0x3f {msg} {coin})", 512, None),
            ("", "(66 0x3f {msg} {coin})", "(67 0x3f {msg} {coin})", 513, Err.TOO_MANY_ANNOUNCEMENTS),
        ],
    )
    async def test_announce_conditions_limit(
        self,
        consensus_mode: ConsensusMode,
        prefix: str,
        condition1: str,
        condition2: str,
        num: int,
        expect_err: Optional[Err],
        bt: BlockTools,
    ) -> None:
        """
        Test that the condition checker accepts more announcements than the new per puzzle limit
        pre-v2-softfork, and rejects more than the announcement limit afterward.
        """

        blocks = await initial_blocks(bt)
        coin = blocks[-2].get_included_reward_coins()[0]
        coin_announcement = AssertCoinAnnouncement(asserted_id=coin.name(), asserted_msg=b"test")
        puzzle_announcement = AssertPuzzleAnnouncement(asserted_ph=EASY_PUZZLE_HASH, asserted_msg=b"test")

        conditions = b""
        if prefix != "":
            conditions += b"\xff" + assemble(prefix).as_bin()

        [cond1, cond2] = [
            c.format(
                coin="0x" + coin.name().hex(),
                ph="0x" + EASY_PUZZLE_HASH.hex(),
                cann="0x" + coin_announcement.msg_calc.hex(),
                pann="0x" + puzzle_announcement.msg_calc.hex(),
                msg="0x1337",
            )
            for c in [condition1, condition2]
        ]

        conditions += (b"\xff" + assemble(cond1).as_bin()) * num
        if cond2 != "":
            conditions += (b"\xff" + assemble(cond2).as_bin()) * num
        conditions += b"\x80"
        conditions_program = Program.from_bytes(conditions)

        await check_conditions(bt, conditions_program, expected_err=expect_err)

    @pytest.mark.anyio
    async def test_coin_messages(self, bt: BlockTools, consensus_mode: ConsensusMode) -> None:
        blocks = await initial_blocks(bt)
        coin = blocks[-2].get_included_reward_coins()[0]
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.SEND_MESSAGE[0]} 0x3f 'test' 0x{coin.name().hex()})"
                f"({ConditionOpcode.RECEIVE_MESSAGE[0]} 0x3f 'test' 0x{coin.name().hex()}))"
            )
        )
        await check_conditions(bt, conditions)

    @pytest.mark.anyio
    async def test_parent_messages(self, bt: BlockTools, consensus_mode: ConsensusMode) -> None:
        blocks = await initial_blocks(bt)
        coin = blocks[-2].get_included_reward_coins()[0]
        conditions = Program.to(
            assemble(
                f"(({ConditionOpcode.SEND_MESSAGE[0]} 0x24 'test' 0x{coin.parent_coin_info})"
                f"({ConditionOpcode.RECEIVE_MESSAGE[0]} 0x24 'test' 0x{coin.parent_coin_info}))"
            )
        )
        await check_conditions(bt, conditions)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "conds, expected",
        [
            ('(66 0x3f "foobar" {coin}) (67 0x3f "foobar" {coin})', None),
            ('(66 0x3f "foobar" {coin}) (67 0x3f "foo" {coin})', Err.MESSAGE_NOT_SENT_OR_RECEIVED),
            ('(66 0x39 "foo" {coin})', Err.COIN_AMOUNT_EXCEEDS_MAXIMUM),
            ('(67 0x0f "foo" {coin})', Err.COIN_AMOUNT_EXCEEDS_MAXIMUM),
            ('(66 0x3f "foo" {coin}) (67 0x27 "foo" {coin})', Err.MESSAGE_NOT_SENT_OR_RECEIVED),
            ('(66 0x27 "foo" {coin}) (67 0x3f "foo" {coin})', Err.MESSAGE_NOT_SENT_OR_RECEIVED),
            ('(66 0 "foo") (67 0 "foo")', None),
            ('(66 0 "foobar") (67 0 "foo")', Err.MESSAGE_NOT_SENT_OR_RECEIVED),
            ('(66 0x09 "foo" 1750000000000) (67 0x09 "foo" 1750000000000)', None),
            ('(66 -1 "foo")', Err.INVALID_MESSAGE_MODE),
            ('(67 -1 "foo")', Err.INVALID_MESSAGE_MODE),
            ('(66 0x40 "foo")', Err.INVALID_MESSAGE_MODE),
            ('(67 0x40 "foo")', Err.INVALID_MESSAGE_MODE),
        ],
    )
    async def test_message_conditions(
        self, bt: BlockTools, consensus_mode: ConsensusMode, conds: str, expected: Optional[Err]
    ) -> None:
        blocks = await initial_blocks(bt)
        coin = blocks[-2].get_included_reward_coins()[0]
        conditions = Program.to(assemble("(" + conds.format(coin="0x" + coin.name().hex()) + ")"))

        await check_conditions(bt, conditions, expected_err=expected)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
            ConditionOpcode.AGG_SIG_UNSAFE,
            ConditionOpcode.AGG_SIG_ME,
        ],
    )
    async def test_agg_sig_infinity(
        self, opcode: ConditionOpcode, bt: BlockTools, consensus_mode: ConsensusMode
    ) -> None:
        conditions = Program.to(
            assemble(
                f"(({opcode.value[0]} "
                "0xc00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
                ' "foobar"))'
            )
        )

        # infinity is disallowed after soft-fork-5 activates
        if consensus_mode >= ConsensusMode.SOFT_FORK_5:
            expected_error = Err.INVALID_CONDITION
        else:
            expected_error = None
        await check_conditions(bt, conditions, expected_error)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
            ConditionOpcode.AGG_SIG_UNSAFE,
            ConditionOpcode.AGG_SIG_ME,
        ],
    )
    async def test_agg_sig_illegal_suffix(
        self,
        opcode: ConditionOpcode,
        bt: BlockTools,
        consensus_mode: ConsensusMode,
    ) -> None:

        c = bt.constants

        additional_data = agg_sig_additional_data(c.AGG_SIG_ME_ADDITIONAL_DATA)
        assert c.AGG_SIG_ME_ADDITIONAL_DATA == additional_data[ConditionOpcode.AGG_SIG_ME]
        assert c.AGG_SIG_PARENT_ADDITIONAL_DATA == additional_data[ConditionOpcode.AGG_SIG_PARENT]
        assert c.AGG_SIG_PUZZLE_ADDITIONAL_DATA == additional_data[ConditionOpcode.AGG_SIG_PUZZLE]
        assert c.AGG_SIG_AMOUNT_ADDITIONAL_DATA == additional_data[ConditionOpcode.AGG_SIG_AMOUNT]
        assert c.AGG_SIG_PUZZLE_AMOUNT_ADDITIONAL_DATA == additional_data[ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT]
        assert c.AGG_SIG_PARENT_AMOUNT_ADDITIONAL_DATA == additional_data[ConditionOpcode.AGG_SIG_PARENT_AMOUNT]
        assert c.AGG_SIG_PARENT_PUZZLE_ADDITIONAL_DATA == additional_data[ConditionOpcode.AGG_SIG_PARENT_PUZZLE]

        blocks = await initial_blocks(bt)
        if opcode == ConditionOpcode.AGG_SIG_UNSAFE:
            expected_error = Err.INVALID_CONDITION
        else:
            expected_error = None

        sk = AugSchemeMPL.key_gen(b"8" * 32)
        pubkey = sk.get_g1()
        coin = blocks[-2].get_included_reward_coins()[0]
        for msg in [
            c.AGG_SIG_ME_ADDITIONAL_DATA,
            c.AGG_SIG_PARENT_ADDITIONAL_DATA,
            c.AGG_SIG_PUZZLE_ADDITIONAL_DATA,
            c.AGG_SIG_AMOUNT_ADDITIONAL_DATA,
            c.AGG_SIG_PUZZLE_AMOUNT_ADDITIONAL_DATA,
            c.AGG_SIG_PARENT_AMOUNT_ADDITIONAL_DATA,
            c.AGG_SIG_PARENT_PUZZLE_ADDITIONAL_DATA,
        ]:
            print(f"op: {opcode} msg: {msg}")
            message = "0x" + msg.hex()
            if opcode == ConditionOpcode.AGG_SIG_ME:
                suffix = coin.name() + c.AGG_SIG_ME_ADDITIONAL_DATA
            elif opcode == ConditionOpcode.AGG_SIG_PARENT:
                suffix = coin.parent_coin_info + c.AGG_SIG_PARENT_ADDITIONAL_DATA
            elif opcode == ConditionOpcode.AGG_SIG_PUZZLE:
                suffix = coin.puzzle_hash + c.AGG_SIG_PUZZLE_ADDITIONAL_DATA
            elif opcode == ConditionOpcode.AGG_SIG_AMOUNT:
                suffix = int_to_bytes(coin.amount) + c.AGG_SIG_AMOUNT_ADDITIONAL_DATA
            elif opcode == ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT:
                suffix = coin.puzzle_hash + int_to_bytes(coin.amount) + c.AGG_SIG_PUZZLE_AMOUNT_ADDITIONAL_DATA
            elif opcode == ConditionOpcode.AGG_SIG_PARENT_AMOUNT:
                suffix = coin.parent_coin_info + int_to_bytes(coin.amount) + c.AGG_SIG_PARENT_AMOUNT_ADDITIONAL_DATA
            elif opcode == ConditionOpcode.AGG_SIG_PARENT_PUZZLE:
                suffix = coin.parent_coin_info + coin.puzzle_hash + c.AGG_SIG_PARENT_PUZZLE_ADDITIONAL_DATA
            else:
                suffix = b""
            sig = AugSchemeMPL.sign(sk, msg + suffix, pubkey)
            solution = SerializedProgram.to(assemble(f"(({opcode.value[0]} 0x{bytes(pubkey).hex()} {message}))"))
            coin_spend = make_spend(coin, EASY_PUZZLE, solution)
            spend_bundle = SpendBundle([coin_spend], sig)
            await check_spend_bundle_validity(bt, blocks, spend_bundle, expected_err=expected_error)
