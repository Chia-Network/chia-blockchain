import unittest
from src.blockchain import Blockchain
# from src.util.genesis_block import genesis_block_hardcoded
from src.util.ints import uint64


class GenesisBlockTest(unittest.TestCase):
    def test_basic_blockchain(self):
        bc1: Blockchain = Blockchain()
        assert len(bc1.get_current_heads()) == 1
        genesis_block = bc1.get_current_heads()[0]
        assert genesis_block.height == 0
        assert bc1.get_trunk_blocks_by_height([uint64(0)], genesis_block.header_hash) == genesis_block
        assert bc1.get_difficulty(genesis_block.header_hash) == genesis_block.trunk_block.challenge.total_weight
        assert bc1.get_difficulty(genesis_block.header_hash) == bc1.get_next_difficulty(genesis_block.header_hash)
        assert bc1.get_vdf_rate_estimate() is None


class ValidateBlock(unittest.TestCase):
    # sample_block =
    def test_prev_pointer(self):
        pass
