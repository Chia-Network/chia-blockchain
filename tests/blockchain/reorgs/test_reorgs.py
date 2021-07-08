# flake8: noqa: F811, F401
import asyncio
import logging
import pytest
from chia.consensus.blockchain import ReceiveBlockResult
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from tests.wallet_tools import WalletTool
from tests.core.fixtures import default_400_blocks  # noqa: F401; noqa: F401
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


class TestReorgs:
    @pytest.mark.asyncio
    async def test_basic_reorg(self, empty_blockchain):
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(15)

        for block in blocks:
            assert (await b.receive_block(block))[0] == ReceiveBlockResult.NEW_PEAK
        assert b.get_peak().height == 14

        blocks_reorg_chain = bt.get_consecutive_blocks(7, blocks[:10], seed=b"2")
        for reorg_block in blocks_reorg_chain:
            result, error_code, fork_height = await b.receive_block(reorg_block)
            if reorg_block.height < 10:
                assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.height < 14:
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
            elif reorg_block.height >= 15:
                assert result == ReceiveBlockResult.NEW_PEAK
            assert error_code is None
        assert b.get_peak().height == 16

    @pytest.mark.asyncio
    async def test_long_reorg(self, empty_blockchain, default_10000_blocks):
        # Reorg longer than a difficulty adjustment
        # Also tests higher weight chain but lower height
        b = empty_blockchain
        num_blocks_chain_1 = 3 * test_constants.EPOCH_BLOCKS + test_constants.MAX_SUB_SLOT_BLOCKS + 10
        num_blocks_chain_2_start = test_constants.EPOCH_BLOCKS - 20
        num_blocks_chain_2 = 3 * test_constants.EPOCH_BLOCKS + test_constants.MAX_SUB_SLOT_BLOCKS + 8

        assert num_blocks_chain_1 < 10000
        blocks = default_10000_blocks[:num_blocks_chain_1]

        for block in blocks:
            assert (await b.receive_block(block))[0] == ReceiveBlockResult.NEW_PEAK
        chain_1_height = b.get_peak().height
        chain_1_weight = b.get_peak().weight
        assert chain_1_height == (num_blocks_chain_1 - 1)

        # These blocks will have less time between them (timestamp) and therefore will make difficulty go up
        # This means that the weight will grow faster, and we can get a heavier chain with lower height
        blocks_reorg_chain = bt.get_consecutive_blocks(
            num_blocks_chain_2 - num_blocks_chain_2_start,
            blocks[:num_blocks_chain_2_start],
            seed=b"2",
            time_per_block=8,
        )
        found_orphan = False
        for reorg_block in blocks_reorg_chain:
            result, error_code, fork_height = await b.receive_block(reorg_block)
            if reorg_block.height < num_blocks_chain_2_start:
                assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            if reorg_block.weight <= chain_1_weight:
                if result == ReceiveBlockResult.ADDED_AS_ORPHAN:
                    found_orphan = True
                assert error_code is None
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN or result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.weight > chain_1_weight:
                assert reorg_block.height < chain_1_height
                assert result == ReceiveBlockResult.NEW_PEAK
            assert error_code is None
        assert found_orphan

        assert b.get_peak().weight > chain_1_weight
        assert b.get_peak().height < chain_1_height

    @pytest.mark.asyncio
    async def test_long_compact_blockchain(self, empty_blockchain, default_10000_blocks_compact):
        b = empty_blockchain
        for block in default_10000_blocks_compact:
            assert (await b.receive_block(block))[0] == ReceiveBlockResult.NEW_PEAK
        assert b.get_peak().height == len(default_10000_blocks_compact) - 1

    @pytest.mark.asyncio
    async def test_reorg_from_genesis(self, empty_blockchain):
        b = empty_blockchain
        wallet_a = WalletTool(b.constants)
        WALLET_A_PUZZLE_HASHES = [wallet_a.get_new_puzzlehash() for _ in range(5)]

        blocks = bt.get_consecutive_blocks(15)

        for block in blocks:
            assert (await b.receive_block(block))[0] == ReceiveBlockResult.NEW_PEAK
        assert b.get_peak().height == 14

        # Reorg to alternate chain that is 1 height longer
        found_orphan = False
        blocks_reorg_chain = bt.get_consecutive_blocks(16, [], seed=b"2")
        for reorg_block in blocks_reorg_chain:
            result, error_code, fork_height = await b.receive_block(reorg_block)
            if reorg_block.height < 14:
                if result == ReceiveBlockResult.ADDED_AS_ORPHAN:
                    found_orphan = True
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN or result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.height >= 15:
                assert result == ReceiveBlockResult.NEW_PEAK
            assert error_code is None

        # Back to original chain
        blocks_reorg_chain_2 = bt.get_consecutive_blocks(3, blocks, seed=b"3")

        result, error_code, fork_height = await b.receive_block(blocks_reorg_chain_2[-3])
        assert result == ReceiveBlockResult.ADDED_AS_ORPHAN

        result, error_code, fork_height = await b.receive_block(blocks_reorg_chain_2[-2])
        assert result == ReceiveBlockResult.NEW_PEAK

        result, error_code, fork_height = await b.receive_block(blocks_reorg_chain_2[-1])
        assert result == ReceiveBlockResult.NEW_PEAK
        assert found_orphan
        assert b.get_peak().height == 17

    @pytest.mark.asyncio
    async def test_reorg_transaction(self, empty_blockchain):
        b = empty_blockchain
        wallet_a = WalletTool(b.constants)
        WALLET_A_PUZZLE_HASHES = [wallet_a.get_new_puzzlehash() for _ in range(5)]
        coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
        receiver_puzzlehash = WALLET_A_PUZZLE_HASHES[1]

        blocks = bt.get_consecutive_blocks(10, farmer_reward_puzzle_hash=coinbase_puzzlehash)
        blocks = bt.get_consecutive_blocks(
            2, blocks, farmer_reward_puzzle_hash=coinbase_puzzlehash, guarantee_transaction_block=True
        )

        spend_block = blocks[10]
        spend_coin = None
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                spend_coin = coin
        spend_bundle = wallet_a.generate_signed_transaction(uint64(1000), receiver_puzzlehash, spend_coin)

        blocks = bt.get_consecutive_blocks(
            2,
            blocks,
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=spend_bundle,
            guarantee_transaction_block=True,
        )

        blocks_fork = bt.get_consecutive_blocks(
            1, blocks[:12], farmer_reward_puzzle_hash=coinbase_puzzlehash, seed=b"123", guarantee_transaction_block=True
        )
        blocks_fork = bt.get_consecutive_blocks(
            2,
            blocks_fork,
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=spend_bundle,
            guarantee_transaction_block=True,
            seed=b"1245",
        )
        for block in blocks:
            result, error_code, _ = await b.receive_block(block)
            assert error_code is None and result == ReceiveBlockResult.NEW_PEAK

        for block in blocks_fork:
            result, error_code, _ = await b.receive_block(block)
            assert error_code is None

    @pytest.mark.asyncio
    async def test_get_header_blocks_in_range_tx_filter(self, empty_blockchain):
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            pool_reward_puzzle_hash=bt.pool_ph,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK
        wt: WalletTool = bt.get_pool_wallet_tool()
        tx: SpendBundle = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), list(blocks[2].get_included_reward_coins())[0]
        )
        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=tx,
        )
        err = (await b.receive_block(blocks[-1]))[1]
        assert not err

        blocks_with_filter = await b.get_header_blocks_in_range(0, 10, tx_filter=True)
        blocks_without_filter = await b.get_header_blocks_in_range(0, 10, tx_filter=False)
        header_hash = blocks[-1].header_hash
        assert (
            blocks_with_filter[header_hash].transactions_filter
            != blocks_without_filter[header_hash].transactions_filter
        )
        assert blocks_with_filter[header_hash].header_hash == blocks_without_filter[header_hash].header_hash

    @pytest.mark.asyncio
    async def test_get_blocks_at(self, empty_blockchain, default_1000_blocks):
        b = empty_blockchain
        heights = []
        for block in default_1000_blocks[:200]:
            heights.append(block.height)
            result, error_code, _ = await b.receive_block(block)
            assert error_code is None and result == ReceiveBlockResult.NEW_PEAK

        blocks = await b.get_block_records_at(heights, batch_size=2)
        assert blocks
        assert len(blocks) == 200
        assert blocks[-1].height == 199
