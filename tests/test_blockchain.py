import time
import pytest
from blspy import PrivateKey
from src.types.coinbase import CoinbaseInfo
from src.types.block_body import BlockBody
from src.types.proof_of_space import ProofOfSpace
from src.types.block_header import BlockHeader
from src.types.trunk_block import TrunkBlock
from src.types.full_block import FullBlock
from src.types.block_header import BlockHeaderData
from src.blockchain import Blockchain, ReceiveBlockResult
from src.util.ints import uint64
from tests.block_tools import BlockTools


bt = BlockTools()


class TestGenesisBlock():
    def test_basic_blockchain(self):
        bc1: Blockchain = Blockchain()
        assert len(bc1.get_current_heads()) == 1
        genesis_block = bc1.get_current_heads()[0]
        assert genesis_block.height == 0
        assert bc1.get_trunk_blocks_by_height([uint64(0)], genesis_block.header_hash)[0] == genesis_block
        assert bc1.get_difficulty(genesis_block.header_hash) == genesis_block.challenge.total_weight
        assert bc1.get_difficulty(genesis_block.header_hash) == bc1.get_next_difficulty(genesis_block.header_hash)
        assert bc1.get_vdf_rate_estimate() is None


class TestBlockValidation():
    @pytest.fixture(scope="module")
    def initial_blockchain(self):
        """
        Provides a list of 3 valid blocks, as well as a blockchain with 2 blocks added to it.
        """
        blocks = bt.get_consecutive_blocks(3)
        b: Blockchain = Blockchain(blocks[0])
        assert b.receive_block(blocks[1]) == ReceiveBlockResult.ADDED_TO_HEAD
        return (blocks, b)

    def test_prev_pointer(self, initial_blockchain):
        blocks, b = initial_blockchain
        block_bad = FullBlock(TrunkBlock(
                blocks[2].trunk_block.proof_of_space,
                blocks[2].trunk_block.proof_of_time,
                blocks[2].trunk_block.challenge,
                BlockHeader(BlockHeaderData(
                        bytes([1]*32),
                        blocks[2].trunk_block.header.data.timestamp,
                        blocks[2].trunk_block.header.data.filter_hash,
                        blocks[2].trunk_block.header.data.proof_of_space_hash,
                        blocks[2].trunk_block.header.data.body_hash,
                        blocks[2].trunk_block.header.data.extension_data
                ), blocks[2].trunk_block.header.plotter_signature)
                ), blocks[2].body)
        assert b.receive_block(block_bad) == ReceiveBlockResult.INVALID_BLOCK

    def test_timestamp(self, initial_blockchain):
        blocks, b = initial_blockchain
        # Time too far in the past
        block_bad = FullBlock(TrunkBlock(
                blocks[2].trunk_block.proof_of_space,
                blocks[2].trunk_block.proof_of_time,
                blocks[2].trunk_block.challenge,
                BlockHeader(BlockHeaderData(
                        blocks[2].trunk_block.header.data.prev_header_hash,
                        blocks[2].trunk_block.header.data.timestamp - 1000,
                        blocks[2].trunk_block.header.data.filter_hash,
                        blocks[2].trunk_block.header.data.proof_of_space_hash,
                        blocks[2].trunk_block.header.data.body_hash,
                        blocks[2].trunk_block.header.data.extension_data
                ), blocks[2].trunk_block.header.plotter_signature)
                ), blocks[2].body)
        assert b.receive_block(block_bad) == ReceiveBlockResult.INVALID_BLOCK

        # Time too far in the future
        block_bad = FullBlock(TrunkBlock(
                blocks[2].trunk_block.proof_of_space,
                blocks[2].trunk_block.proof_of_time,
                blocks[2].trunk_block.challenge,
                BlockHeader(BlockHeaderData(
                        blocks[2].trunk_block.header.data.prev_header_hash,
                        time.time() + 3600 * 3,
                        blocks[2].trunk_block.header.data.filter_hash,
                        blocks[2].trunk_block.header.data.proof_of_space_hash,
                        blocks[2].trunk_block.header.data.body_hash,
                        blocks[2].trunk_block.header.data.extension_data
                ), blocks[2].trunk_block.header.plotter_signature)
                ), blocks[2].body)

        assert b.receive_block(block_bad) == ReceiveBlockResult.INVALID_BLOCK

    def test_body_hash(self, initial_blockchain):
        blocks, b = initial_blockchain
        # Time too far in the past
        block_bad = FullBlock(TrunkBlock(
                blocks[2].trunk_block.proof_of_space,
                blocks[2].trunk_block.proof_of_time,
                blocks[2].trunk_block.challenge,
                BlockHeader(BlockHeaderData(
                        blocks[2].trunk_block.header.data.prev_header_hash,
                        blocks[2].trunk_block.header.data.timestamp,
                        blocks[2].trunk_block.header.data.filter_hash,
                        blocks[2].trunk_block.header.data.proof_of_space_hash,
                        bytes([1]*32),
                        blocks[2].trunk_block.header.data.extension_data
                ), blocks[2].trunk_block.header.plotter_signature)
                ), blocks[2].body)
        assert b.receive_block(block_bad) == ReceiveBlockResult.INVALID_BLOCK

    def test_plotter_signature(self, initial_blockchain):
        blocks, b = initial_blockchain
        # Time too far in the past
        block_bad = FullBlock(TrunkBlock(
                blocks[2].trunk_block.proof_of_space,
                blocks[2].trunk_block.proof_of_time,
                blocks[2].trunk_block.challenge,
                BlockHeader(
                        blocks[2].trunk_block.header.data,
                        PrivateKey.from_seed(b'0').sign_prepend(b"random junk"))
                ), blocks[2].body)
        assert b.receive_block(block_bad) == ReceiveBlockResult.INVALID_BLOCK

    def test_invalid_pos(self, initial_blockchain):
        blocks, b = initial_blockchain

        bad_pos = blocks[2].trunk_block.proof_of_space.proof
        bad_pos[0] = (bad_pos[0] + 1) % 256
        # Proof of space invalid
        block_bad = FullBlock(TrunkBlock(
                ProofOfSpace(
                    blocks[2].trunk_block.proof_of_space.pool_pubkey,
                    blocks[2].trunk_block.proof_of_space.plot_pubkey,
                    blocks[2].trunk_block.proof_of_space.size,
                    bad_pos
                ),
                blocks[2].trunk_block.proof_of_time,
                blocks[2].trunk_block.challenge,
                blocks[2].trunk_block.header
        ), blocks[2].body)
        assert b.receive_block(block_bad) == ReceiveBlockResult.INVALID_BLOCK

    def test_invalid_coinbase_height(self, initial_blockchain):
        blocks, b = initial_blockchain

        # Coinbase height invalid
        block_bad = FullBlock(blocks[2].trunk_block, BlockBody(
                CoinbaseInfo(
                        3,
                        blocks[2].body.coinbase.amount,
                        blocks[2].body.coinbase.puzzle_hash
                ),
                blocks[2].body.coinbase_signature,
                blocks[2].body.fees_target_info,
                blocks[2].body.aggregated_signature,
                blocks[2].body.solutions_generator
        ))
        assert b.receive_block(block_bad) == ReceiveBlockResult.INVALID_BLOCK
