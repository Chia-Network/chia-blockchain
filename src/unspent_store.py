from typing import Dict
from src.consensus.constants import constants as consensus_constants
from src.types.hashable import Hash, Unspent


class UnspentStore:
    def __init__(self, override_constants: Dict = {}):
        # Allow passing in custom overrides
        self.constants: Dict = consensus_constants
        for key, value in override_constants.items():
            self.constants[key] = value

        # Unspents for lce
        self._lce_unspent_coins: Dict[Hash: Unspent] = dict()

    async def unspent_for_coin_name(self, coin_name: Hash) -> Unspent:
        return self._lce_unspent_coins.get(coin_name)

    async def set_unspent_for_coin_name(self, coin_name: Hash, unspent: Unspent) -> None:
        self._lce_unspent_coins[coin_name] = unspent

    async def all_unspents(self):
        for coin_name, unspent in self._lce_unspent_coins.items():
            yield coin_name, unspent

    async def rollback_to_block(self, block_index):
        for v in self._lce_unspent_coins.values():
            if v.spent_block_index > block_index:
                v.spent_block_index = 0
            if v.confirmed_block_index > block_index:
                v.confirmed_block_index = 0
