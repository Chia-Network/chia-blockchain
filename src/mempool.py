from typing import Dict, Optional
from src.consensus.constants import constants as consensus_constants
from src.types.full_block import FullBlock
from src.types.hashable import SpendBundle, Hash
from src.types.header_block import HeaderBlock
from src.util.ints import uint32


class Pool:
    header_block: HeaderBlock
    spends: Dict[uint32:SpendBundle]


class Mempool:
    def __init__(self, override_constants: Dict = {}):
        # Allow passing in custom overrides
        self.constants: Dict = consensus_constants
        for key, value in override_constants.items():
            self.constants[key] = value

        # Transactions that were unable to enter mempool
        self.potential_transactions: Dict[Hash: SpendBundle] = dict()

        # Mempool for each tip
        self.mempools: Dict[HeaderBlock: Dict] = dict()

    # Aggregate all SpendBundles for THE tip and return only one
    # TODO
    async def get_spendbundle_for_tip(self, header_block: HeaderBlock) -> Optional[SpendBundle]:
        mempool = self.mempools[header_block.header_hash]
        all: [SpendBundle] = mempool
        agg: SpendBundle = SpendBundle.aggregate(all)
        return agg

    # TODO
    async def add_spendbundle_to_mempool(self, new_spend: SpendBundle):
        for hash, mempool in self.mempools.items():
            print("trying to add to mempool")
            # check if unspents are valid in this SpendBundle
        return True

    # TODO
    async def add_tip(self, add_tip: FullBlock, remove_tip: FullBlock):
        await self.remove_tip(remove_tip)

    # TODO
    async def remove_tip(self, tip: HeaderBlock):
        if tip.header_hash in self.mempools:
            del self.mempools[tip.header_hash]
