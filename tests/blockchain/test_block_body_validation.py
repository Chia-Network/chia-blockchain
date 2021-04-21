# flake8: noqa: F811, F401
import asyncio
import logging
import time

import pytest
from blspy import G2Element
from clvm.casts import int_to_bytes

from chia.consensus.blockchain import ReceiveBlockResult
from chia.full_node.bundle_tools import detect_potential_template_generator
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.foliage import TransactionsInfo
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.full_block import FullBlock
from chia.types.spend_bundle import SpendBundle
from chia.util.block_tools import BlockTools
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.ints import uint64, uint32
from chia.util.merkle_set import MerkleSet
from chia.util.recursive_replace import recursive_replace
from chia.util.wallet_tools import WalletTool
from tests.core.fixtures import default_400_blocks, create_blockchain  # noqa: F401; noqa: F401
from tests.core.fixtures import default_1000_blocks  # noqa: F401
from tests.core.fixtures import default_10000_blocks  # noqa: F401
from tests.core.fixtures import default_10000_blocks_compact  # noqa: F401
from tests.core.fixtures import empty_blockchain  # noqa: F401
from tests.setup_nodes import bt, test_constants

log = logging.getLogger(__name__)
bad_element = ClassgroupElement.from_bytes(b"\x00")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestBodyValidation:
    @pytest.mark.asyncio
    async def test_not_tx_block_but_has_data(self, empty_blockchain):
        # 1
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(1)
        while blocks[-1].foliage_transaction_block is not None:
            assert (await b.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        original_block: FullBlock = blocks[-1]

        block = recursive_replace(original_block, "transactions_generator", SerializedProgram())
        assert (await b.receive_block(block))[1] == Err.NOT_BLOCK_BUT_HAS_DATA
        h = std_hash(b"")
        i = uint64(1)
        block = recursive_replace(
            original_block,
            "transactions_info",
            TransactionsInfo(h, h, G2Element(), uint64(1), uint64(1), []),
        )
        assert (await b.receive_block(block))[1] == Err.NOT_BLOCK_BUT_HAS_DATA

        block = recursive_replace(original_block, "transactions_generator_ref_list", [i])
        assert (await b.receive_block(block))[1] == Err.NOT_BLOCK_BUT_HAS_DATA

    @pytest.mark.asyncio
    async def test_tx_block_missing_data(self, empty_blockchain):
        # 2
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block = recursive_replace(
            blocks[-1],
            "foliage_transaction_block",
            None,
        )
        err = (await b.receive_block(block))[1]
        assert err == Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA or err == Err.INVALID_FOLIAGE_BLOCK_PRESENCE

        block = recursive_replace(
            blocks[-1],
            "transactions_info",
            None,
        )
        try:
            err = (await b.receive_block(block))[1]
        except AssertionError:
            return
        assert err == Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA or err == Err.INVALID_FOLIAGE_BLOCK_PRESENCE

    @pytest.mark.asyncio
    async def test_invalid_transactions_info_hash(self, empty_blockchain):
        # 3
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
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
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block = recursive_replace(block, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block))[1]
        assert err == Err.INVALID_TRANSACTIONS_INFO_HASH

    @pytest.mark.asyncio
    async def test_invalid_transactions_block_hash(self, empty_blockchain):
        # 4
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        h = std_hash(b"")
        block = recursive_replace(blocks[-1], "foliage.foliage_transaction_block_hash", h)
        new_m = block.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block = recursive_replace(block, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block))[1]
        assert err == Err.INVALID_FOLIAGE_BLOCK_HASH

    @pytest.mark.asyncio
    async def test_invalid_reward_claims(self, empty_blockchain):
        # 5
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block: FullBlock = blocks[-1]

        # Too few
        too_few_reward_claims = block.transactions_info.reward_claims_incorporated[:-1]
        block_2: FullBlock = recursive_replace(
            block, "transactions_info.reward_claims_incorporated", too_few_reward_claims
        )
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block_2))[1]
        assert err == Err.INVALID_REWARD_COINS

        # Too many
        h = std_hash(b"")
        too_many_reward_claims = block.transactions_info.reward_claims_incorporated + [
            Coin(h, h, too_few_reward_claims[0].amount)
        ]
        block_2 = recursive_replace(block, "transactions_info.reward_claims_incorporated", too_many_reward_claims)
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block_2))[1]
        assert err == Err.INVALID_REWARD_COINS

        # Duplicates
        duplicate_reward_claims = block.transactions_info.reward_claims_incorporated + [
            block.transactions_info.reward_claims_incorporated[-1]
        ]
        block_2 = recursive_replace(block, "transactions_info.reward_claims_incorporated", duplicate_reward_claims)
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block_2))[1]
        assert err == Err.INVALID_REWARD_COINS

    @pytest.mark.asyncio
    async def test_initial_freeze(self, empty_blockchain):
        # 6
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            pool_reward_puzzle_hash=bt.pool_ph,
            farmer_reward_puzzle_hash=bt.pool_ph,
            genesis_timestamp=time.time() - 1000,
        )
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK
        wt: WalletTool = bt.get_pool_wallet_tool()
        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[2].get_included_reward_coins())[0]
        )
        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=tx,
        )
        err = (await b.receive_block(blocks[-1]))[1]
        assert err == Err.INITIAL_TRANSACTION_FREEZE

    @pytest.mark.asyncio
    async def test_invalid_transactions_generator_hash(self, empty_blockchain):
        # 7
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

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
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block_2))[1]
        assert err == Err.INVALID_TRANSACTIONS_GENERATOR_HASH

        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        blocks = bt.get_consecutive_blocks(
            2,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[3]))[0] == ReceiveBlockResult.NEW_PEAK

        wt: WalletTool = bt.get_pool_wallet_tool()
        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )
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
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block_2))[1]
        assert err == Err.INVALID_TRANSACTIONS_GENERATOR_HASH

    @pytest.mark.asyncio
    async def test_invalid_transactions_ref_list(self, empty_blockchain):
        # No generator should have [1]s for the root
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK

        block: FullBlock = blocks[-1]
        block_2 = recursive_replace(block, "transactions_info.generator_refs_root", bytes([0] * 32))
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block_2))[1]
        assert err == Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT

        # No generator should have no refs list
        block_2 = recursive_replace(block, "transactions_generator_ref_list", [uint32(0)])

        err = (await b.receive_block(block_2))[1]
        assert err == Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT

        # Hash should be correct when there is a ref list
        assert (await b.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK
        wt: WalletTool = bt.get_pool_wallet_tool()
        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )
        blocks = bt.get_consecutive_blocks(5, block_list_input=blocks, guarantee_transaction_block=False)
        for block in blocks[-5:]:
            assert (await b.receive_block(block))[0] == ReceiveBlockResult.NEW_PEAK

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        assert (await b.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK
        generator_arg = detect_potential_template_generator(blocks[-1].height, blocks[-1].transactions_generator)
        assert generator_arg is not None

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=tx,
            previous_generator=generator_arg,
        )
        block = blocks[-1]
        assert len(block.transactions_generator_ref_list) > 0

        block_2 = recursive_replace(block, "transactions_info.generator_refs_root", bytes([1] * 32))
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block_2))[1]
        assert err == Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT

        # Too many heights
        block_2 = recursive_replace(block, "transactions_generator_ref_list", [block.height - 2, block.height - 1])
        err = (await b.receive_block(block_2))[1]
        assert err == Err.GENERATOR_REF_HAS_NO_GENERATOR
        assert (await b.pre_validate_blocks_multiprocessing([block_2], {})) is None

        # Not tx block
        for h in range(0, block.height - 1):
            block_2 = recursive_replace(block, "transactions_generator_ref_list", [h])
            err = (await b.receive_block(block_2))[1]
            assert err == Err.GENERATOR_REF_HAS_NO_GENERATOR or err == Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT
            assert (await b.pre_validate_blocks_multiprocessing([block_2], {})) is None

    @pytest.mark.asyncio
    async def test_cost_exceeds_max(self, empty_blockchain):
        # 7
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK

        wt: WalletTool = bt.get_pool_wallet_tool()

        condition_dict = {ConditionOpcode.CREATE_COIN: []}
        for i in range(7000):
            output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt.pool_ph, int_to_bytes(i)])
            condition_dict[ConditionOpcode.CREATE_COIN].append(output)

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0], condition_dic=condition_dict
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        assert (await b.receive_block(blocks[-1]))[1] == Err.BLOCK_COST_EXCEEDS_MAX

    @pytest.mark.asyncio
    async def test_clvm_must_not_fail(self, empty_blockchain):
        # 8
        pass

    @pytest.mark.asyncio
    async def test_invalid_cost_in_block(self, empty_blockchain):
        # 9
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]

        # zero
        block_2: FullBlock = recursive_replace(block, "transactions_info.cost", uint64(0))
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block_2))[1]
        assert err == Err.INVALID_BLOCK_COST

        # too low
        block_2: FullBlock = recursive_replace(block, "transactions_info.cost", uint64(1))
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)
        err = (await b.receive_block(block_2))[1]
        assert err == Err.GENERATOR_RUNTIME_ERROR

        # too high
        block_2: FullBlock = recursive_replace(block, "transactions_info.cost", uint64(1000000))
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block_2))[1]
        assert err == Err.INVALID_BLOCK_COST

        err = (await b.receive_block(block))[1]
        assert err is None

    @pytest.mark.asyncio
    async def test_max_coin_amount(self):
        # 10
        # TODO: fix, this is not reaching validation. Because we can't create a block with such amounts due to uint64
        # limit in Coin

        new_test_constants = test_constants.replace(
            **{"GENESIS_PRE_FARM_POOL_PUZZLE_HASH": bt.pool_ph, "GENESIS_PRE_FARM_FARMER_PUZZLE_HASH": bt.pool_ph}
        )
        b, connection, db_path = await create_blockchain(new_test_constants)
        bt_2 = BlockTools(new_test_constants)
        bt_2.constants = bt_2.constants.replace(
            **{"GENESIS_PRE_FARM_POOL_PUZZLE_HASH": bt.pool_ph, "GENESIS_PRE_FARM_FARMER_PUZZLE_HASH": bt.pool_ph}
        )
        blocks = bt_2.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK

        wt: WalletTool = bt_2.get_pool_wallet_tool()

        condition_dict = {ConditionOpcode.CREATE_COIN: []}
        output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt_2.pool_ph, int_to_bytes(2 ** 64)])
        condition_dict[ConditionOpcode.CREATE_COIN].append(output)

        tx: SpendBundle = wt.generate_signed_transaction_multiple_coins(
            10,
            wt.get_new_puzzlehash(),
            list(blocks[1].get_included_reward_coins()),
            condition_dic=condition_dict,
        )
        try:
            blocks = bt_2.get_consecutive_blocks(
                1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
            )
            assert False
        except Exception as e:
            pass
        await connection.close()
        b.shut_down()
        db_path.unlink()

    @pytest.mark.asyncio
    async def test_invalid_merkle_roots(self, empty_blockchain):
        # 11
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]

        merkle_set = MerkleSet()
        # additions
        block_2 = recursive_replace(block, "foliage_transaction_block.additions_root", merkle_set.get_root())
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block_2))[1]
        assert err == Err.BAD_ADDITION_ROOT

        # removals
        merkle_set.add_already_hashed(std_hash(b"1"))
        block_2 = recursive_replace(block, "foliage_transaction_block.removals_root", merkle_set.get_root())
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block_2))[1]
        assert err == Err.BAD_REMOVAL_ROOT

    @pytest.mark.asyncio
    async def test_invalid_filter(self, empty_blockchain):
        # 12
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]
        block_2 = recursive_replace(block, "foliage_transaction_block.filter_hash", std_hash(b"3"))
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        err = (await b.receive_block(block_2))[1]
        assert err == Err.INVALID_TRANSACTIONS_FILTER_HASH

    @pytest.mark.asyncio
    async def test_duplicate_outputs(self, empty_blockchain):
        # 13
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK

        wt: WalletTool = bt.get_pool_wallet_tool()

        condition_dict = {ConditionOpcode.CREATE_COIN: []}
        for i in range(2):
            output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt.pool_ph, int_to_bytes(1)])
            condition_dict[ConditionOpcode.CREATE_COIN].append(output)

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0], condition_dic=condition_dict
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        assert (await b.receive_block(blocks[-1]))[1] == Err.DUPLICATE_OUTPUT

    @pytest.mark.asyncio
    async def test_duplicate_removals(self, empty_blockchain):
        # 14
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )
        tx_2: SpendBundle = wt.generate_signed_transaction(
            11, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )
        agg = SpendBundle.aggregate([tx, tx_2])

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=agg
        )
        assert (await b.receive_block(blocks[-1]))[1] == Err.DOUBLE_SPEND

    @pytest.mark.asyncio
    async def test_double_spent_in_coin_store(self, empty_blockchain):
        # 15
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        assert (await b.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK

        tx_2: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-2].get_included_reward_coins())[0]
        )
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx_2
        )

        assert (await b.receive_block(blocks[-1]))[1] == Err.DOUBLE_SPEND

    @pytest.mark.asyncio
    async def test_double_spent_in_reorg(self, empty_blockchain):
        # 15
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        assert (await b.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK

        new_coin: Coin = tx.additions()[0]
        tx_2: SpendBundle = wt.generate_signed_transaction(10, wt.get_new_puzzlehash(), new_coin)
        # This is fine because coin exists
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx_2
        )
        assert (await b.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK
        blocks = bt.get_consecutive_blocks(5, block_list_input=blocks, guarantee_transaction_block=True)
        for block in blocks[-5:]:
            assert (await b.receive_block(block))[0] == ReceiveBlockResult.NEW_PEAK

        blocks_reorg = bt.get_consecutive_blocks(2, block_list_input=blocks[:-7], guarantee_transaction_block=True)
        assert (await b.receive_block(blocks_reorg[-2]))[0] == ReceiveBlockResult.ADDED_AS_ORPHAN
        assert (await b.receive_block(blocks_reorg[-1]))[0] == ReceiveBlockResult.ADDED_AS_ORPHAN

        # Coin does not exist in reorg
        blocks_reorg = bt.get_consecutive_blocks(
            1, block_list_input=blocks_reorg, guarantee_transaction_block=True, transaction_data=tx_2
        )

        assert (await b.receive_block(blocks_reorg[-1]))[1] == Err.UNKNOWN_UNSPENT

        # Finally add the block to the fork (spending both in same bundle, this is ephemeral)
        agg = SpendBundle.aggregate([tx, tx_2])
        blocks_reorg = bt.get_consecutive_blocks(
            1, block_list_input=blocks_reorg[:-1], guarantee_transaction_block=True, transaction_data=agg
        )
        assert (await b.receive_block(blocks_reorg[-1]))[1] is None

        blocks_reorg = bt.get_consecutive_blocks(
            1, block_list_input=blocks_reorg, guarantee_transaction_block=True, transaction_data=tx_2
        )
        assert (await b.receive_block(blocks_reorg[-1]))[1] == Err.DOUBLE_SPEND_IN_FORK
