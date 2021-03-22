# import asyncio
#
# import pytest
#
# from chia.util.merkle_set import MerkleSet, confirm_included_already_hashed
# from tests.setup_nodes import bt
#
#
# @pytest.fixture(scope="module")
# def event_loop():
#     loop = asyncio.get_event_loop()
#     yield loop
#
#
# class TestMerkleSet:
#     @pytest.mark.asyncio
#     async def test_basics(self):
#         num_blocks = 10
#         blocks = bt.get_consecutive_blocks(
#             num_blocks,
#         )
#
#         merkle_set = MerkleSet()
#         merkle_set_reverse = MerkleSet()
#
#         for block in reversed(blocks):
#             merkle_set_reverse.add_already_hashed(block.get_coinbase().name())
#
#         for block in blocks:
#             merkle_set.add_already_hashed(block.get_coinbase().name())
#
#         for block in blocks:
#             result, proof = merkle_set.is_included_already_hashed(block.get_coinbase().name())
#             assert result is True
#             result_fee, proof_fee = merkle_set.is_included_already_hashed(block.get_fees_coin().name())
#             assert result_fee is False
#             validate_proof = confirm_included_already_hashed(merkle_set.get_root(), block.get_coinbase().name(),
#             proof)
#             validate_proof_fee = confirm_included_already_hashed(
#                 merkle_set.get_root(), block.get_fees_coin().name(), proof_fee
#             )
#             assert validate_proof is True
#             assert validate_proof_fee is False
#
#         # Test if order of adding items change the outcome
#         assert merkle_set.get_root() == merkle_set_reverse.get_root()
