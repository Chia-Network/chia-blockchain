import asyncio
import itertools

import pytest

from chia.util.merkle_set import MerkleSet, confirm_included_already_hashed
from tests.setup_nodes import bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestMerkleSet:
    @pytest.mark.asyncio
    async def test_basics(self):
        num_blocks = 20
        blocks = bt.get_consecutive_blocks(num_blocks)

        merkle_set = MerkleSet()
        merkle_set_reverse = MerkleSet()
        coins = list(itertools.chain.from_iterable(map(lambda block: block.get_included_reward_coins(), blocks)))

        # excluded coin (not present in 'coins' and Merkle sets)
        excl_coin = coins.pop()

        for coin in reversed(coins):
            merkle_set_reverse.add_already_hashed(coin.name())

        for coin in coins:
            merkle_set.add_already_hashed(coin.name())

        for coin in coins:
            result, proof = merkle_set.is_included_already_hashed(coin.name())
            assert result is True
            result_excl, proof_excl = merkle_set.is_included_already_hashed(excl_coin.name())
            assert result_excl is False
            validate_proof = confirm_included_already_hashed(merkle_set.get_root(), coin.name(), proof)
            validate_proof_excl = confirm_included_already_hashed(merkle_set.get_root(), excl_coin.name(), proof_excl)
            assert validate_proof is True
            assert validate_proof_excl is False

        # Test if the order of adding items changes the outcome
        assert merkle_set.get_root() == merkle_set_reverse.get_root()
