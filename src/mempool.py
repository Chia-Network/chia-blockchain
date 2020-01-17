from typing import Dict, Optional
from src.consensus.constants import constants as consensus_constants
from src.types.full_block import FullBlock
from src.types.hashable import SpendBundle
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.chain_utils import name_puzzle_conditions_list


class Pool:
    header_block: HeaderBlock
    spends: Dict

#TODO keep some mempool spendbundle history for the purpose of restoring in case of reorg
class Mempool:
    def __init__(self, override_constants: Dict = {}):
        # Allow passing in custom overrides
        self.constants: Dict = consensus_constants
        for key, value in override_constants.items():
            self.constants[key] = value

        # Transactions that were unable to enter mempool
        self.potential_transactions = dict()
        self.allSpend: Dict[bytes32: SpendBundle] = []
        self.allSeen: Dict[bytes32: bytes32] = []
        # Mempool for each tip
        self.mempools = []

    # TODO implement creating block from mempool
    # TODO Maximize transaction fees, handle conflicting transactions
    # TODO Aggregate all SpendBundles for the tip and return only one
    async def create_bundle_for_tip(self, header_block: HeaderBlock) -> Optional[SpendBundle]:

        return None

    """async def get_spendbundle_for_tip(self, header_block: HeaderBlock) -> Optional[SpendBundle]:
        mempool = self.mempools[header_block.header_hash]
        all: [SpendBundle] = mempool
        agg: SpendBundle = SpendBundle.aggregate(all)
        return agg
    """

    async def add_spendbundle(self, new_spend: SpendBundle):
        self.allSeen[new_spend.name()] = new_spend.name()
        # TODO calculate the cost of spendbundle
        npc_list = name_puzzle_conditions_list()

        cost = new_spend.
        # TODO calculate the fees of spendbundle
        # TODO check conditions
        # TODO check coins being spent and created
        return True

    # Return is we saw this spendbundle before
    async def seen(self, bundle_hash: bytes32) -> bool:
        if self.allSeen[bundle_hash] is None:
            return False
        else:
            return True

    # Returns a full spendbundle for bundle
    async def get_spendbundle(self, bundle_hash: bytes32) -> Optional[SpendBundle]:
        return self.allSpend[bundle_hash]

    # TODO create new mempool for this tip
    # TODO If it's extending already existing mempool remove spent coins and use that one ?
    async def add_tip(self, add_tip: FullBlock, remove_tip: FullBlock):
        await self.remove_tip(remove_tip)

    # TODO
    async def remove_tip(self, removed_tip: HeaderBlock):
        if removed_tip in self.mempools:
            remove = self.mempools.pop(removed_tip])
