from dataclasses import dataclass
from typing import List, Optional, Tuple

from deafwave.consensus.coinbase import pool_parent_id, farmer_parent_id, postfarm_parent_id
from deafwave.types.blockchain_format.coin import Coin
from deafwave.types.blockchain_format.sized_bytes import bytes32
from deafwave.types.mempool_inclusion_status import MempoolInclusionStatus
from deafwave.types.spend_bundle import SpendBundle
from deafwave.util.ints import uint8, uint32, uint64
from deafwave.util.streamable import Streamable, streamable
from deafwave.wallet.util.transaction_type import TransactionType


@dataclass(frozen=True)
@streamable
class TransactionRecord(Streamable):
    """
    Used for storing transaction data and status in wallets.
    """

    confirmed_at_height: uint32
    created_at_time: uint64
    to_puzzle_hash: bytes32
    amount: uint64
    fee_amount: uint64
    confirmed: bool
    sent: uint32
    spend_bundle: Optional[SpendBundle]
    additions: List[Coin]
    removals: List[Coin]
    wallet_id: uint32

    # Represents the list of peers that we sent the transaction to, whether each one
    # included it in the mempool, and what the error message (if any) was
    sent_to: List[Tuple[str, uint8, Optional[str]]]
    trade_id: Optional[bytes32]
    type: uint32  # TransactionType
    name: bytes32

    def is_in_mempool(self) -> bool:
        # If one of the nodes we sent it to responded with success, we set it to success
        for (_, mis, _) in self.sent_to:
            if MempoolInclusionStatus(mis) == MempoolInclusionStatus.SUCCESS:
                return True
        # Note, transactions pending inclusion (pending) return false
        return False

    def height_farmed(self, genesis_challenge) -> Optional[uint32]:
        if not self.confirmed:
            return None
        if self.type == TransactionType.FEE_REWARD or self.type == TransactionType.COINBASE_REWARD:
            for block_index in range(self.confirmed_at_height, self.confirmed_at_height - 100, -1):
                if block_index < 0:
                    return None
                pool_parent = pool_parent_id(
                    uint32(block_index), genesis_challenge)
                farmer_parent = farmer_parent_id(
                    uint32(block_index), genesis_challenge)
                postfarm_parent = postfarm_parent_id(
                    uint32(block_index), genesis_challenge)
                if pool_parent == self.additions[0].parent_coin_info:
                    return uint32(block_index)
                if farmer_parent == self.additions[0].parent_coin_info:
                    return uint32(block_index)
                if postfarm_parent == self.additions[0].parent_coin_info:
                    return uint32(block_index)
        return uint32(block_index)
