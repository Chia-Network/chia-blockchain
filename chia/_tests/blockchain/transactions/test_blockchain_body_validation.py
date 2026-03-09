from __future__ import annotations

import platform
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from chia_rs import (
    ConsensusConstants,
    FullBlock,
    G2Element,
    MerkleSet,
    SpendBundle,
    TransactionsInfo,
)
from chia_rs.sized_ints import uint32, uint64

from chia._tests.blockchain.blockchain_test_utils import (
    _validate_and_add_block,
    _validate_and_add_block_multi_error,
    _validate_and_add_block_multi_result,
)
from chia._tests.conftest import ConsensusMode
from chia._tests.core.full_node.test_full_node import find_reward_coin
from chia._tests.util.blockchain import create_blockchain
from chia._tests.util.get_name_puzzle_conditions import get_name_puzzle_conditions
from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.block_rewards import calculate_base_farmer_reward
from chia.consensus.blockchain import AddBlockResult, Blockchain
from chia.consensus.coinbase import create_farmer_coin
from chia.consensus.multiprocess_validation import PreValidationResult, pre_validate_block
from chia.simulator.block_tools import BlockTools
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.generator_types import BlockGenerator
from chia.types.validation_state import ValidationState
from chia.util.casts import int_to_bytes
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.recursive_replace import recursive_replace
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
)


def _is_macos_intel() -> bool:
    """True when running on macOS with an Intel CPU (x86_64). Used to skip slow test params."""
    return platform.system() == "Darwin" and platform.machine() in {"x86_64", "i386"}


@asynccontextmanager
async def make_empty_blockchain(constants: ConsensusConstants) -> AsyncIterator[Blockchain]:
    """
    Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
    """

    async with create_blockchain(constants, 2) as (bc, _):
        yield bc


co = ConditionOpcode
rbr = AddBlockResult


class TestBodyValidation:
    # TODO: add test for
    # ASSERT_COIN_ANNOUNCEMENT,
    # CREATE_COIN_ANNOUNCEMENT,
    # CREATE_PUZZLE_ANNOUNCEMENT,
    # ASSERT_PUZZLE_ANNOUNCEMENT,

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_MY_AMOUNT,
            ConditionOpcode.ASSERT_MY_PUZZLEHASH,
            ConditionOpcode.ASSERT_MY_COIN_ID,
            ConditionOpcode.ASSERT_MY_PARENT_ID,
        ],
    )
    @pytest.mark.parametrize("with_garbage", [True, False])
    async def test_conditions(
        self, empty_blockchain: Blockchain, opcode: ConditionOpcode, with_garbage: bool, bt: BlockTools
    ) -> None:
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            genesis_timestamp=uint64(10_000),
            time_per_block=10,
        )
        await _validate_and_add_block(empty_blockchain, blocks[0])
        await _validate_and_add_block(empty_blockchain, blocks[1])
        await _validate_and_add_block(empty_blockchain, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx1 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)
        coin1: Coin = tx1.additions()[0]

        if opcode == ConditionOpcode.ASSERT_MY_AMOUNT:
            args = [int_to_bytes(coin1.amount)]
        elif opcode == ConditionOpcode.ASSERT_MY_PUZZLEHASH:
            args = [coin1.puzzle_hash]
        elif opcode == ConditionOpcode.ASSERT_MY_COIN_ID:
            args = [coin1.name()]
        elif opcode == ConditionOpcode.ASSERT_MY_PARENT_ID:
            args = [coin1.parent_coin_info]
        # elif opcode == ConditionOpcode.RESERVE_FEE:
        # args = [int_to_bytes(5)]
        # TODO: since we use the production wallet code, we can't (easily)
        # create a transaction with fee without also including a valid
        # RESERVE_FEE condition
        else:
            assert False

        conditions: dict[ConditionOpcode, list[ConditionWithArgs]] = {
            opcode: [ConditionWithArgs(opcode, args + ([b"garbage"] if with_garbage else []))]
        }

        tx2 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin1, condition_dic=conditions)
        assert coin1 in tx2.removals()

        bundles = SpendBundle.aggregate([tx1, tx2])
        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=bundles,
            time_per_block=10,
        )
        ssi = b.constants.SUB_SLOT_ITERS_STARTING
        diff = b.constants.DIFFICULTY_STARTING
        block = blocks[-1]
        future = await pre_validate_block(
            b.constants,
            AugmentedBlockchain(b),
            block,
            b.pool,
            None,
            ValidationState(ssi, diff, None),
        )
        pre_validation_result: PreValidationResult = await future
        # Ignore errors from pre-validation, we are testing block_body_validation
        repl_preval_results = replace(pre_validation_result, error=None, required_iters=uint64(1))
        fork_info = ForkInfo(block.height - 1, block.height - 1, block.prev_header_hash)
        code, err, state_change = await b.add_block(block, repl_preval_results, sub_slot_iters=ssi, fork_info=fork_info)
        assert code == AddBlockResult.NEW_PEAK
        assert err is None
        assert state_change is not None
        assert state_change.fork_height == 2

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "opcode,lock_value,expected",
        [
            # the 3 blocks, starting at timestamp 10000 (and height 0).
            # each block is 10 seconds apart.
            # the 4th block (height 3, time 10030) spends a coin with the condition specified
            # by the test case. The coin was born in height 2 at time 10020
            # MY BIRHT HEIGHT
            (co.ASSERT_MY_BIRTH_HEIGHT, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_HEIGHT, 0x100000000, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_HEIGHT, 2, rbr.NEW_PEAK),  # <- coin birth height
            (co.ASSERT_MY_BIRTH_HEIGHT, 3, rbr.INVALID_BLOCK),
            # MY BIRHT SECONDS
            (co.ASSERT_MY_BIRTH_SECONDS, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 0x10000000000000000, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 10019, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 10020, rbr.NEW_PEAK),  # <- coin birth time
            (co.ASSERT_MY_BIRTH_SECONDS, 10021, rbr.INVALID_BLOCK),
            # SECONDS RELATIVE
            (co.ASSERT_SECONDS_RELATIVE, -2, rbr.NEW_PEAK),
            (co.ASSERT_SECONDS_RELATIVE, -1, rbr.NEW_PEAK),
            (co.ASSERT_SECONDS_RELATIVE, 0, rbr.NEW_PEAK),  # <- birth time
            (co.ASSERT_SECONDS_RELATIVE, 1, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_RELATIVE, 9, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_RELATIVE, 10, rbr.INVALID_BLOCK),  # <- current block time
            (co.ASSERT_SECONDS_RELATIVE, 11, rbr.INVALID_BLOCK),
            # BEFORE SECONDS RELATIVE
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, -2, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 0, rbr.INVALID_BLOCK),  # <- birth time
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 1, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 9, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 10, rbr.NEW_PEAK),  # <- current block time
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 11, rbr.NEW_PEAK),
            # HEIGHT RELATIVE
            (co.ASSERT_HEIGHT_RELATIVE, -2, rbr.NEW_PEAK),
            (co.ASSERT_HEIGHT_RELATIVE, -1, rbr.NEW_PEAK),
            (co.ASSERT_HEIGHT_RELATIVE, 0, rbr.NEW_PEAK),
            (co.ASSERT_HEIGHT_RELATIVE, 1, rbr.INVALID_BLOCK),
            # BEFORE HEIGHT RELATIVE
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, -2, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 0, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 1, rbr.NEW_PEAK),
            # HEIGHT ABSOLUTE
            (co.ASSERT_HEIGHT_ABSOLUTE, 1, rbr.NEW_PEAK),
            (co.ASSERT_HEIGHT_ABSOLUTE, 2, rbr.NEW_PEAK),
            (co.ASSERT_HEIGHT_ABSOLUTE, 3, rbr.INVALID_BLOCK),
            (co.ASSERT_HEIGHT_ABSOLUTE, 4, rbr.INVALID_BLOCK),
            # BEFORE HEIGHT ABSOLUTE
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 1, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 2, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 3, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 4, rbr.NEW_PEAK),
            # SECONDS ABSOLUTE
            # genesis timestamp is 10000 and each block is 10 seconds
            (co.ASSERT_SECONDS_ABSOLUTE, 10019, rbr.NEW_PEAK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10020, rbr.NEW_PEAK),  # <- previous tx-block
            (co.ASSERT_SECONDS_ABSOLUTE, 10021, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10029, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10030, rbr.INVALID_BLOCK),  # <- current block
            (co.ASSERT_SECONDS_ABSOLUTE, 10031, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10032, rbr.INVALID_BLOCK),
            # BEFORE SECONDS ABSOLUTE
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10019, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10020, rbr.INVALID_BLOCK),  # <- previous tx-block
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10021, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10029, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10030, rbr.NEW_PEAK),  # <- current block
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10031, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10032, rbr.NEW_PEAK),
        ],
    )
    async def test_timelock_conditions(
        self, opcode: ConditionOpcode, lock_value: int, expected: AddBlockResult, bt: BlockTools
    ) -> None:
        async with make_empty_blockchain(bt.constants) as b:
            blocks = bt.get_consecutive_blocks(
                3,
                guarantee_transaction_block=True,
                farmer_reward_puzzle_hash=bt.pool_ph,
                genesis_timestamp=uint64(10_000),
                time_per_block=10,
            )
            for bl in blocks:
                await _validate_and_add_block(b, bl)

            wt: WalletTool = bt.get_pool_wallet_tool()

            conditions = {opcode: [ConditionWithArgs(opcode, [int_to_bytes(lock_value)])]}

            coin = find_reward_coin(blocks[-1], bt.pool_ph)
            tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin, condition_dic=conditions)

            blocks = bt.get_consecutive_blocks(
                1,
                block_list_input=blocks,
                guarantee_transaction_block=True,
                transaction_data=tx,
                time_per_block=10,
            )
            ssi = b.constants.SUB_SLOT_ITERS_STARTING
            diff = b.constants.DIFFICULTY_STARTING
            block = blocks[-1]
            future = await pre_validate_block(
                b.constants,
                AugmentedBlockchain(b),
                block,
                b.pool,
                None,
                ValidationState(ssi, diff, None),
            )
            pre_validation_result: PreValidationResult = await future
            fork_info = ForkInfo(block.height - 1, block.height - 1, block.prev_header_hash)
            assert (await b.add_block(block, pre_validation_result, sub_slot_iters=ssi, fork_info=fork_info))[
                0
            ] == expected

            if expected == AddBlockResult.NEW_PEAK:
                # ensure coin was in fact spent
                c = await b.coin_store.get_coin_record(coin.name())
                assert c is not None and c.spent

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.AGG_SIG_ME,
            ConditionOpcode.AGG_SIG_UNSAFE,
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
        ],
    )
    @pytest.mark.parametrize("with_garbage", [True, False])
    async def test_aggsig_garbage(
        self,
        empty_blockchain: Blockchain,
        opcode: ConditionOpcode,
        with_garbage: bool,
        bt: BlockTools,
        consensus_mode: ConsensusMode,
    ) -> None:
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            genesis_timestamp=uint64(10_000),
            time_per_block=10,
        )
        await _validate_and_add_block(empty_blockchain, blocks[0])
        await _validate_and_add_block(empty_blockchain, blocks[1])
        await _validate_and_add_block(empty_blockchain, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx1 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)
        coin1: Coin = tx1.additions()[0]
        secret_key = wt.get_private_key_for_puzzle_hash(coin1.puzzle_hash)
        synthetic_secret_key = calculate_synthetic_secret_key(secret_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        public_key = synthetic_secret_key.get_g1()

        args = [bytes(public_key), b"msg"] + ([b"garbage"] if with_garbage else [])
        conditions = {opcode: [ConditionWithArgs(opcode, args)]}

        tx2 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin1, condition_dic=conditions)
        assert coin1 in tx2.removals()

        bundles = SpendBundle.aggregate([tx1, tx2])
        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=bundles,
            time_per_block=10,
        )
        ssi = b.constants.SUB_SLOT_ITERS_STARTING
        diff = b.constants.DIFFICULTY_STARTING
        block = blocks[-1]
        future = await pre_validate_block(
            b.constants,
            AugmentedBlockchain(b),
            block,
            b.pool,
            None,
            ValidationState(ssi, diff, None),
        )
        pre_validation_result: PreValidationResult = await future
        # Ignore errors from pre-validation, we are testing block_body_validation
        repl_preval_results = replace(pre_validation_result, error=None, required_iters=uint64(1))
        fork_info = ForkInfo(block.height - 1, block.height - 1, block.prev_header_hash)
        res, error, state_change = await b.add_block(
            block, repl_preval_results, sub_slot_iters=ssi, fork_info=fork_info
        )
        assert res == AddBlockResult.NEW_PEAK
        assert error is None
        assert state_change is not None and state_change.fork_height == uint32(2)

    @pytest.mark.anyio
    @pytest.mark.parametrize("with_garbage", [True, False])
    @pytest.mark.parametrize(
        "opcode,lock_value,expected",
        [
            # we don't allow any birth assertions, not
            # relative time locks on ephemeral coins. This test is only for
            # ephemeral coins, so these cases should always fail
            # MY BIRHT HEIGHT
            (co.ASSERT_MY_BIRTH_HEIGHT, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_HEIGHT, 0x100000000, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_HEIGHT, 2, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_HEIGHT, 3, rbr.INVALID_BLOCK),
            # MY BIRHT SECONDS
            (co.ASSERT_MY_BIRTH_SECONDS, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 0x10000000000000000, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 10029, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 10030, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 10031, rbr.INVALID_BLOCK),
            # SECONDS RELATIVE
            # genesis timestamp is 10000 and each block is 10 seconds
            (co.ASSERT_SECONDS_RELATIVE, -2, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_RELATIVE, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_RELATIVE, 0, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_RELATIVE, 1, rbr.INVALID_BLOCK),
            # BEFORE SECONDS RELATIVE
            # relative conditions are not allowed on ephemeral spends
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, -2, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 0, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 10, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 0x10000000000000000, rbr.INVALID_BLOCK),
            # HEIGHT RELATIVE
            (co.ASSERT_HEIGHT_RELATIVE, -2, rbr.INVALID_BLOCK),
            (co.ASSERT_HEIGHT_RELATIVE, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_HEIGHT_RELATIVE, 0, rbr.INVALID_BLOCK),
            (co.ASSERT_HEIGHT_RELATIVE, 1, rbr.INVALID_BLOCK),
            # BEFORE HEIGHT RELATIVE
            # relative conditions are not allowed on ephemeral spends
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, -2, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 0, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 1, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 0x100000000, rbr.INVALID_BLOCK),
            # HEIGHT ABSOLUTE
            (co.ASSERT_HEIGHT_ABSOLUTE, 2, rbr.NEW_PEAK),
            (co.ASSERT_HEIGHT_ABSOLUTE, 3, rbr.INVALID_BLOCK),
            (co.ASSERT_HEIGHT_ABSOLUTE, 4, rbr.INVALID_BLOCK),
            # BEFORE HEIGHT ABSOLUTE
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 2, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 3, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 4, rbr.NEW_PEAK),
            # SECONDS ABSOLUTE
            # genesis timestamp is 10000 and each block is 10 seconds
            (co.ASSERT_SECONDS_ABSOLUTE, 10020, rbr.NEW_PEAK),  # <- previous tx-block
            (co.ASSERT_SECONDS_ABSOLUTE, 10021, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10029, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10030, rbr.INVALID_BLOCK),  # <- current tx-block
            (co.ASSERT_SECONDS_ABSOLUTE, 10031, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10032, rbr.INVALID_BLOCK),
            # BEFORE SECONDS ABSOLUTE
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10020, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10021, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10030, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10031, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10032, rbr.NEW_PEAK),
        ],
    )
    async def test_ephemeral_timelock(
        self, opcode: ConditionOpcode, lock_value: int, expected: AddBlockResult, with_garbage: bool, bt: BlockTools
    ) -> None:
        async with make_empty_blockchain(bt.constants) as b:
            blocks = bt.get_consecutive_blocks(
                3,
                guarantee_transaction_block=True,
                farmer_reward_puzzle_hash=bt.pool_ph,
                genesis_timestamp=uint64(10_000),
                time_per_block=10,
            )
            await _validate_and_add_block(b, blocks[0])
            await _validate_and_add_block(b, blocks[1])
            await _validate_and_add_block(b, blocks[2])

            wt: WalletTool = bt.get_pool_wallet_tool()

            conditions = {
                opcode: [ConditionWithArgs(opcode, [int_to_bytes(lock_value)] + ([b"garbage"] if with_garbage else []))]
            }

            coin = find_reward_coin(blocks[-1], bt.pool_ph)
            tx1 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)
            coin1: Coin = tx1.additions()[0]
            tx2 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin1, condition_dic=conditions)
            assert coin1 in tx2.removals()
            coin2: Coin = tx2.additions()[0]

            bundles = SpendBundle.aggregate([tx1, tx2])
            blocks = bt.get_consecutive_blocks(
                1,
                block_list_input=blocks,
                guarantee_transaction_block=True,
                transaction_data=bundles,
                time_per_block=10,
            )
            ssi = b.constants.SUB_SLOT_ITERS_STARTING
            diff = b.constants.DIFFICULTY_STARTING
            block = blocks[-1]
            future = await pre_validate_block(
                b.constants,
                AugmentedBlockchain(b),
                block,
                b.pool,
                None,
                ValidationState(ssi, diff, None),
            )
            pre_validation_result: PreValidationResult = await future
            fork_info = ForkInfo(block.height - 1, block.height - 1, block.prev_header_hash)
            assert (await b.add_block(block, pre_validation_result, sub_slot_iters=ssi, fork_info=fork_info))[
                0
            ] == expected

            if expected == AddBlockResult.NEW_PEAK:
                # ensure coin1 was in fact spent
                c = await b.coin_store.get_coin_record(coin1.name())
                assert c is not None and c.spent
                # ensure coin2 was NOT spent
                c = await b.coin_store.get_coin_record(coin2.name())
                assert c is not None and not c.spent

    @pytest.mark.anyio
    async def test_not_tx_block_but_has_data(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 1
        blocks = bt.get_consecutive_blocks(1)
        while blocks[-1].foliage_transaction_block is not None:
            await _validate_and_add_block(empty_blockchain, blocks[-1])
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        original_block: FullBlock = blocks[-1]

        block = recursive_replace(original_block, "transactions_generator", SerializedProgram.to(None))
        await _validate_and_add_block(
            empty_blockchain, block, expected_error=Err.NOT_BLOCK_BUT_HAS_DATA, skip_prevalidation=True
        )
        h = std_hash(b"")
        i = uint64(1)
        block = recursive_replace(
            original_block,
            "transactions_info",
            TransactionsInfo(h, h, G2Element(), uint64(1), uint64(1), []),
        )
        await _validate_and_add_block(
            empty_blockchain, block, expected_error=Err.NOT_BLOCK_BUT_HAS_DATA, skip_prevalidation=True
        )

        block = recursive_replace(original_block, "transactions_generator_ref_list", [i])
        await _validate_and_add_block(
            empty_blockchain, block, expected_error=Err.NOT_BLOCK_BUT_HAS_DATA, skip_prevalidation=True
        )

    @pytest.mark.anyio
    async def test_tx_block_missing_data(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 2
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks[0])
        block = recursive_replace(
            blocks[-1],
            "foliage_transaction_block",
            None,
        )
        await _validate_and_add_block_multi_error(
            b, block, [Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA, Err.INVALID_FOLIAGE_BLOCK_PRESENCE]
        )

        block = recursive_replace(
            blocks[-1],
            "transactions_info",
            None,
        )
        with pytest.raises(AssertionError):
            await _validate_and_add_block_multi_error(
                b, block, [Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA, Err.INVALID_FOLIAGE_BLOCK_PRESENCE]
            )

    @pytest.mark.anyio
    async def test_invalid_transactions_info_hash(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 3
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks[0])
        h = std_hash(b"")
        block = recursive_replace(
            blocks[-1],
            "foliage_transaction_block.transactions_info_hash",
            h,
        )
        block = recursive_replace(
            block, "foliage.foliage_transaction_block_hash", std_hash(block.foliage_transaction_block)
        )
        new_m = block.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block = recursive_replace(block, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block, expected_error=Err.INVALID_TRANSACTIONS_INFO_HASH)

    @pytest.mark.anyio
    async def test_invalid_transactions_block_hash(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 4
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks[0])
        h = std_hash(b"")
        block = recursive_replace(blocks[-1], "foliage.foliage_transaction_block_hash", h)
        new_m = block.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block = recursive_replace(block, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block, expected_error=Err.INVALID_FOLIAGE_BLOCK_HASH)

    @pytest.mark.anyio
    async def test_invalid_reward_claims(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 5
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks[0])
        block: FullBlock = blocks[-1]

        # Too few
        assert block.transactions_info is not None
        too_few_reward_claims = block.transactions_info.reward_claims_incorporated[:-1]
        block_2: FullBlock = recursive_replace(
            block, "transactions_info.reward_claims_incorporated", too_few_reward_claims
        )
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )

        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_REWARD_COINS, skip_prevalidation=True)

        # Too many
        h = std_hash(b"")
        too_many_reward_claims = [
            *block.transactions_info.reward_claims_incorporated,
            Coin(h, h, too_few_reward_claims[0].amount),
        ]
        block_2 = recursive_replace(block, "transactions_info.reward_claims_incorporated", too_many_reward_claims)
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_REWARD_COINS, skip_prevalidation=True)

        # Duplicates
        duplicate_reward_claims = [
            *block.transactions_info.reward_claims_incorporated,
            block.transactions_info.reward_claims_incorporated[-1],
        ]
        block_2 = recursive_replace(block, "transactions_info.reward_claims_incorporated", duplicate_reward_claims)
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_REWARD_COINS, skip_prevalidation=True)

    @pytest.mark.anyio
    async def test_invalid_transactions_generator_hash(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 7
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks[0])

        # No tx should have all zeroes
        block: FullBlock = blocks[-1]
        block_2 = recursive_replace(block, "transactions_info.generator_root", bytes([1] * 32))
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(
            b, block_2, expected_error=Err.INVALID_TRANSACTIONS_GENERATOR_HASH, skip_prevalidation=True
        )

        await _validate_and_add_block(b, blocks[1])
        blocks = bt.get_consecutive_blocks(
            2,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[2])
        await _validate_and_add_block(b, blocks[3])

        wt: WalletTool = bt.get_pool_wallet_tool()
        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )

        # Non empty generator hash must be correct
        block = blocks[-1]
        block_2 = recursive_replace(block, "transactions_info.generator_root", bytes([0] * 32))
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)
        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_TRANSACTIONS_GENERATOR_HASH)

    @pytest.mark.anyio
    async def test_invalid_transactions_ref_list(
        self, empty_blockchain: Blockchain, bt: BlockTools, consensus_mode: ConsensusMode
    ) -> None:
        # No generator should have [1]s for the root
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])

        block: FullBlock = blocks[-1]
        block_2 = recursive_replace(block, "transactions_info.generator_refs_root", bytes([0] * 32))
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(
            b, block_2, expected_error=Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, skip_prevalidation=True
        )

        # No generator should have no refs list
        block_2 = recursive_replace(block, "transactions_generator_ref_list", [uint32(0)])

        if consensus_mode < ConsensusMode.HARD_FORK_3_0:
            expected_error = Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT
        else:
            # after the hard fork activation, we no longer allow block references
            expected_error = Err.TOO_MANY_GENERATOR_REFS

        await _validate_and_add_block(b, block_2, expected_error=expected_error, skip_prevalidation=True)

        # Hash should be correct when there is a ref list
        await _validate_and_add_block(b, blocks[-1])
        wt: WalletTool = bt.get_pool_wallet_tool()
        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)
        blocks = bt.get_consecutive_blocks(5, block_list_input=blocks, guarantee_transaction_block=False)
        for block in blocks[-5:]:
            await _validate_and_add_block(b, block)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1])
        assert blocks[-1].transactions_generator is not None

        # after the 3.0 hard fork, we no longer allowe block references, so the
        # block_refs parameter is no longer valid, nor this test
        if consensus_mode < ConsensusMode.HARD_FORK_3_0:
            blocks = bt.get_consecutive_blocks(
                1,
                block_list_input=blocks,
                guarantee_transaction_block=True,
                transaction_data=tx,
                block_refs=[blocks[-1].height],
            )
            block = blocks[-1]
            # once the hard fork activated, we no longer use this form of block
            # compression anymore
            assert len(block.transactions_generator_ref_list) == 0

    @pytest.mark.anyio
    @pytest.mark.skipif(_is_macos_intel(), reason="Slow on macOS Intel")
    async def test_cost_exceeds_max(
        self, empty_blockchain: Blockchain, softfork_height: uint32, bt: BlockTools
    ) -> None:
        # 7
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        condition_dict: dict[ConditionOpcode, list[ConditionWithArgs]] = {ConditionOpcode.CREATE_COIN: []}
        for i in range(7_000):
            output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt.pool_ph, int_to_bytes(i)])
            condition_dict[ConditionOpcode.CREATE_COIN].append(output)

        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin, condition_dic=condition_dict)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )

        assert blocks[-1].transactions_generator is not None
        assert blocks[-1].transactions_info is not None
        block_generator = BlockGenerator(blocks[-1].transactions_generator, [])
        npc_result = get_name_puzzle_conditions(
            block_generator,
            b.constants.MAX_BLOCK_COST_CLVM * 1000,
            mempool_mode=False,
            height=softfork_height,
            constants=bt.constants,
        )
        assert npc_result.conds is not None
        ssi = b.constants.SUB_SLOT_ITERS_STARTING
        diff = b.constants.DIFFICULTY_STARTING
        block = blocks[-1]
        fork_info = ForkInfo(block.height - 1, block.height - 1, block.prev_header_hash)
        err = (
            await b.add_block(
                blocks[-1],
                PreValidationResult(None, uint64(1), npc_result.conds.replace(validated_signature=True), uint32(0)),
                sub_slot_iters=ssi,
                fork_info=fork_info,
            )
        )[1]
        assert err == Err.BLOCK_COST_EXCEEDS_MAX
        future = await pre_validate_block(
            b.constants,
            AugmentedBlockchain(b),
            blocks[-1],
            b.pool,
            None,
            ValidationState(ssi, diff, None),
        )
        result: PreValidationResult = await future
        assert Err(result.error) == Err.BLOCK_COST_EXCEEDS_MAX

    @pytest.mark.anyio
    async def test_clvm_must_not_fail(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 8
        pass

    @pytest.mark.anyio
    async def test_invalid_cost_in_block(
        self, empty_blockchain: Blockchain, softfork_height: uint32, bt: BlockTools
    ) -> None:
        # 9
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]

        # zero
        block_2: FullBlock = recursive_replace(block, "transactions_info.cost", uint64(0))
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)
        assert block_2.transactions_generator is not None
        block_generator = BlockGenerator(block_2.transactions_generator, [])
        assert block.transactions_info is not None
        npc_result = get_name_puzzle_conditions(
            block_generator,
            min(b.constants.MAX_BLOCK_COST_CLVM * 1000, block.transactions_info.cost),
            mempool_mode=False,
            height=softfork_height,
            constants=bt.constants,
        )
        assert npc_result.conds is not None
        ssi = b.constants.SUB_SLOT_ITERS_STARTING
        fork_info = ForkInfo(block_2.height - 1, block_2.height - 1, block_2.prev_header_hash)
        _, err, _ = await b.add_block(
            block_2,
            PreValidationResult(None, uint64(1), npc_result.conds.replace(validated_signature=True), uint32(0)),
            sub_slot_iters=ssi,
            fork_info=fork_info,
        )
        assert err == Err.INVALID_BLOCK_COST

        # too low
        block_2 = recursive_replace(block, "transactions_info.cost", uint64(1))
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)
        assert block_2.transactions_generator is not None
        block_generator = BlockGenerator(block_2.transactions_generator, [])
        assert block.transactions_info is not None
        npc_result = get_name_puzzle_conditions(
            block_generator,
            min(b.constants.MAX_BLOCK_COST_CLVM * 1000, block.transactions_info.cost),
            mempool_mode=False,
            height=softfork_height,
            constants=bt.constants,
        )
        assert npc_result.conds is not None
        fork_info = ForkInfo(block_2.height - 1, block_2.height - 1, block_2.prev_header_hash)
        _, err, _ = await b.add_block(
            block_2,
            PreValidationResult(None, uint64(1), npc_result.conds.replace(validated_signature=True), uint32(0)),
            sub_slot_iters=ssi,
            fork_info=fork_info,
        )
        assert err == Err.INVALID_BLOCK_COST

        # too high
        block_2 = recursive_replace(block, "transactions_info.cost", uint64(1000000))
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        assert block_2.transactions_generator is not None
        block_generator = BlockGenerator(block_2.transactions_generator, [])
        max_cost = (
            min(b.constants.MAX_BLOCK_COST_CLVM * 1000, block.transactions_info.cost)
            if block.transactions_info is not None
            else b.constants.MAX_BLOCK_COST_CLVM * 1000
        )
        npc_result = get_name_puzzle_conditions(
            block_generator,
            max_cost,
            mempool_mode=False,
            height=softfork_height,
            constants=bt.constants,
        )
        assert npc_result.conds is not None
        fork_info = ForkInfo(block_2.height - 1, block_2.height - 1, block_2.prev_header_hash)
        _result, err, _ = await b.add_block(
            block_2,
            PreValidationResult(None, uint64(1), npc_result.conds.replace(validated_signature=True), uint32(0)),
            sub_slot_iters=ssi,
            fork_info=fork_info,
        )
        assert err == Err.INVALID_BLOCK_COST

        # when the CLVM program exceeds cost during execution, it will fail with
        # a general runtime error. The previous test tests this.

    @pytest.mark.anyio
    async def test_max_coin_amount(self, db_version: int, bt: BlockTools) -> None:
        # 10
        # TODO: fix, this is not reaching validation. Because we can't create a block with such amounts due to uint64
        # limit in Coin
        pass
        #
        # with TempKeyring() as keychain:
        #     new_test_constants = bt.constants.replace(
        #         GENESIS_PRE_FARM_POOL_PUZZLE_HASH=bt.pool_ph,
        #         GENESIS_PRE_FARM_FARMER_PUZZLE_HASH=bt.pool_ph,
        #     )
        #     b, db_wrapper = await create_blockchain(new_test_constants, db_version)
        #     bt_2 = await create_block_tools_async(constants=new_test_constants, keychain=keychain)
        #     bt_2.constants = bt_2.constants.replace(
        #         GENESIS_PRE_FARM_POOL_PUZZLE_HASH=bt.pool_ph,
        #         GENESIS_PRE_FARM_FARMER_PUZZLE_HASH=bt.pool_ph,
        #     )
        #     blocks = bt_2.get_consecutive_blocks(
        #         3,
        #         guarantee_transaction_block=True,
        #         farmer_reward_puzzle_hash=bt.pool_ph,
        #     )
        #     assert (await b.add_block(blocks[0]))[0] == AddBlockResult.NEW_PEAK
        #     assert (await b.add_block(blocks[1]))[0] == AddBlockResult.NEW_PEAK
        #     assert (await b.add_block(blocks[2]))[0] == AddBlockResult.NEW_PEAK

        #     wt: WalletTool = bt_2.get_pool_wallet_tool()

        #     condition_dict: dict[ConditionOpcode, list[ConditionWithArgs]] = {ConditionOpcode.CREATE_COIN: []}
        #     output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt_2.pool_ph, int_to_bytes(2 ** 64)])
        #     condition_dict[ConditionOpcode.CREATE_COIN].append(output)

        #     coin = find_reward_coin(blocks[1], bt.pool_ph)
        #     tx = wt.generate_signed_transaction_multiple_coins(
        #         uint64(10),
        #         wt.get_new_puzzlehash(),
        #         coin,
        #         condition_dic=condition_dict,
        #     )
        #     with pytest.raises(Exception):
        #         blocks = bt_2.get_consecutive_blocks(
        #             1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        #         )
        #     await db_wrapper.close()
        #     b.shut_down()

    @pytest.mark.anyio
    async def test_invalid_merkle_roots(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 11
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(empty_blockchain, blocks[0])
        await _validate_and_add_block(empty_blockchain, blocks[1])
        await _validate_and_add_block(empty_blockchain, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]

        merkle_set = MerkleSet([])
        # additions
        block_2 = recursive_replace(block, "foliage_transaction_block.additions_root", merkle_set.get_root())
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(empty_blockchain, block_2, expected_error=Err.BAD_ADDITION_ROOT)

        # removals
        merkle_set = MerkleSet([std_hash(b"1")])
        block_2 = recursive_replace(block, "foliage_transaction_block.removals_root", merkle_set.get_root())
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(empty_blockchain, block_2, expected_error=Err.BAD_REMOVAL_ROOT)

    @pytest.mark.anyio
    async def test_invalid_filter(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 12
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]
        block_2 = recursive_replace(block, "foliage_transaction_block.filter_hash", std_hash(b"3"))
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_TRANSACTIONS_FILTER_HASH)

    @pytest.mark.anyio
    async def test_duplicate_outputs(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 13
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        condition_dict: dict[ConditionOpcode, list[ConditionWithArgs]] = {ConditionOpcode.CREATE_COIN: []}
        for _ in range(2):
            output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt.pool_ph, int_to_bytes(1)])
            condition_dict[ConditionOpcode.CREATE_COIN].append(output)

        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin, condition_dic=condition_dict)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1], expected_error=Err.DUPLICATE_OUTPUT)

    @pytest.mark.anyio
    async def test_duplicate_removals(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 14
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)
        tx_2 = wt.generate_signed_transaction(uint64(11), wt.get_new_puzzlehash(), coin)
        agg = SpendBundle.aggregate([tx, tx_2])

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=agg
        )
        await _validate_and_add_block(b, blocks[-1], expected_error=Err.DOUBLE_SPEND)

    @pytest.mark.anyio
    async def test_double_spent_in_coin_store(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 15
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1])

        tx_2 = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-2].get_included_reward_coins()[0]
        )
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx_2
        )

        await _validate_and_add_block(b, blocks[-1], expected_error=Err.DOUBLE_SPEND)

    @pytest.mark.anyio
    async def test_double_spent_in_reorg(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 15
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1])

        new_coin: Coin = tx.additions()[0]
        tx_2 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), new_coin)
        # This is fine because coin exists
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx_2
        )
        await _validate_and_add_block(b, blocks[-1])
        blocks = bt.get_consecutive_blocks(5, block_list_input=blocks, guarantee_transaction_block=True)
        for block in blocks[-5:]:
            await _validate_and_add_block(b, block)

        blocks_reorg = bt.get_consecutive_blocks(2, block_list_input=blocks[:-7], guarantee_transaction_block=True)
        fork_info = ForkInfo(blocks[-8].height, blocks[-8].height, blocks[-8].header_hash)
        await _validate_and_add_block(
            b, blocks_reorg[-2], expected_result=AddBlockResult.ADDED_AS_ORPHAN, fork_info=fork_info
        )
        await _validate_and_add_block(
            b, blocks_reorg[-1], expected_result=AddBlockResult.ADDED_AS_ORPHAN, fork_info=fork_info
        )

        # Coin does not exist in reorg
        blocks_reorg = bt.get_consecutive_blocks(
            1, block_list_input=blocks_reorg, guarantee_transaction_block=True, transaction_data=tx_2
        )
        peak = b.get_peak()
        assert peak is not None
        await _validate_and_add_block(b, blocks_reorg[-1], expected_error=Err.UNKNOWN_UNSPENT, fork_info=fork_info)

        # Finally add the block to the fork (spending both in same bundle, this is ephemeral)
        agg = SpendBundle.aggregate([tx, tx_2])
        blocks_reorg = bt.get_consecutive_blocks(
            1, block_list_input=blocks_reorg[:-1], guarantee_transaction_block=True, transaction_data=agg
        )

        peak = b.get_peak()
        assert peak is not None
        await _validate_and_add_block(
            b, blocks_reorg[-1], expected_result=AddBlockResult.ADDED_AS_ORPHAN, fork_info=fork_info
        )

        blocks_reorg = bt.get_consecutive_blocks(
            1, block_list_input=blocks_reorg, guarantee_transaction_block=True, transaction_data=tx_2
        )
        peak = b.get_peak()
        assert peak is not None
        await _validate_and_add_block(b, blocks_reorg[-1], expected_error=Err.DOUBLE_SPEND_IN_FORK, fork_info=fork_info)

        rewards_ph = wt.get_new_puzzlehash()
        blocks_reorg = bt.get_consecutive_blocks(
            10,
            block_list_input=blocks_reorg[:-1],
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=rewards_ph,
        )

        peak = b.get_peak()
        assert peak is not None
        for block in blocks_reorg[-10:]:
            await _validate_and_add_block_multi_result(
                b, block, expected_result=[AddBlockResult.ADDED_AS_ORPHAN, AddBlockResult.NEW_PEAK], fork_info=fork_info
            )

        # ephemeral coin is spent
        first_coin = await b.coin_store.get_coin_record(new_coin.name())
        assert first_coin is not None and first_coin.spent
        second_coin = await b.coin_store.get_coin_record(tx_2.additions()[0].name())
        assert second_coin is not None and not second_coin.spent

        farmer_coin = create_farmer_coin(
            blocks_reorg[-1].height,
            rewards_ph,
            calculate_base_farmer_reward(blocks_reorg[-1].height),
            bt.constants.GENESIS_CHALLENGE,
        )
        tx_3 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), farmer_coin)

        blocks_reorg = bt.get_consecutive_blocks(
            1, block_list_input=blocks_reorg, guarantee_transaction_block=True, transaction_data=tx_3
        )
        await _validate_and_add_block(b, blocks_reorg[-1])

        farmer_coin_record = await b.coin_store.get_coin_record(farmer_coin.name())
        assert farmer_coin_record is not None and farmer_coin_record.spent

    @pytest.mark.anyio
    async def test_minting_coin(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 16 Minting coin check
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        spend = find_reward_coin(blocks[-1], bt.pool_ph)
        print("spend=", spend)
        # this create coin will spend all of the coin, so the 10 mojos below
        # will be "minted".
        output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt.pool_ph, int_to_bytes(spend.amount)])
        condition_dict = {ConditionOpcode.CREATE_COIN: [output]}

        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), spend, condition_dic=condition_dict)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1], expected_error=Err.MINTING_COIN)
        # 17 is tested in mempool tests

    @pytest.mark.anyio
    async def test_max_coin_amount_fee(self) -> None:
        # 18 TODO: we can't create a block with such amounts due to uint64
        pass

    @pytest.mark.anyio
    async def test_invalid_fees_in_block(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 19
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]

        # wrong feees
        block_2: FullBlock = recursive_replace(block, "transactions_info.fees", uint64(1239))
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_BLOCK_FEE_AMOUNT)

    @pytest.mark.anyio
    async def test_invalid_agg_sig(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 22
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        coin = find_reward_coin(blocks[-1], bt.pool_ph)
        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin)
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )

        last_block = recursive_replace(blocks[-1], "transactions_info.aggregated_signature", G2Element.generator())
        assert last_block.transactions_info is not None
        last_block = recursive_replace(
            last_block, "foliage_transaction_block.transactions_info_hash", last_block.transactions_info.get_hash()
        )
        assert last_block.foliage_transaction_block is not None
        last_block = recursive_replace(
            last_block, "foliage.foliage_transaction_block_hash", last_block.foliage_transaction_block.get_hash()
        )
        new_m = last_block.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, last_block.reward_chain_block.proof_of_space.plot_public_key)
        last_block = recursive_replace(last_block, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        # Bad signature fails during add_block
        await _validate_and_add_block(b, last_block, expected_error=Err.BAD_AGGREGATE_SIGNATURE)

        # Bad signature also fails in prevalidation
        ssi = b.constants.SUB_SLOT_ITERS_STARTING
        diff = b.constants.DIFFICULTY_STARTING
        future = await pre_validate_block(
            b.constants,
            AugmentedBlockchain(b),
            last_block,
            b.pool,
            None,
            ValidationState(ssi, diff, None),
        )
        preval_result: PreValidationResult = await future
        assert preval_result.error == Err.BAD_AGGREGATE_SIGNATURE.value
