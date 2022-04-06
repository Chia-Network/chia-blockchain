from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict

from chia.consensus.coinbase import pool_parent_id, farmer_parent_id
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import encode_puzzle_hash, decode_puzzle_hash
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.util.transaction_type import TransactionType


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
    memos: List[Tuple[bytes32, List[bytes]]]

    def is_in_mempool(self) -> bool:
        # If one of the nodes we sent it to responded with success, we set it to success
        for (_, mis, _) in self.sent_to:
            if MempoolInclusionStatus(mis) == MempoolInclusionStatus.SUCCESS:
                return True
        # Note, transactions pending inclusion (pending) return false
        return False

    def height_farmed(self, genesis_challenge: bytes32) -> Optional[uint32]:
        if not self.confirmed:
            return None
        if self.type == TransactionType.FEE_REWARD or self.type == TransactionType.COINBASE_REWARD:
            for block_index in range(self.confirmed_at_height, self.confirmed_at_height - 100, -1):
                if block_index < 0:
                    return None
                pool_parent = pool_parent_id(uint32(block_index), genesis_challenge)
                farmer_parent = farmer_parent_id(uint32(block_index), genesis_challenge)
                if pool_parent == self.additions[0].parent_coin_info:
                    return uint32(block_index)
                if farmer_parent == self.additions[0].parent_coin_info:
                    return uint32(block_index)
        return None

    def get_memos(self) -> Dict[bytes32, List[bytes]]:
        return {coin_id: ms for coin_id, ms in self.memos}

    @classmethod
    def from_json_dict_convenience(cls, modified_tx_input: Dict):
        modified_tx = modified_tx_input.copy()
        if "to_address" in modified_tx:
            modified_tx["to_puzzle_hash"] = decode_puzzle_hash(modified_tx["to_address"]).hex()
        if "to_address" in modified_tx:
            del modified_tx["to_address"]
        # Converts memos from a flat dict into a nested list
        memos_dict: Dict[str, List[str]] = {}
        memos_list: List = []
        if "memos" in modified_tx:
            for coin_id, memo in modified_tx["memos"].items():
                if coin_id not in memos_dict:
                    memos_dict[coin_id] = []
                memos_dict[coin_id].append(memo)
        for coin_id, memos in memos_dict.items():
            memos_list.append((coin_id, memos))
        modified_tx["memos"] = memos_list
        return cls.from_json_dict(modified_tx)

    def to_json_dict_convenience(self, config: Dict) -> Dict:
        selected = config["selected_network"]
        prefix = config["network_overrides"]["config"][selected]["address_prefix"]
        formatted = self.to_json_dict()
        formatted["to_address"] = encode_puzzle_hash(self.to_puzzle_hash, prefix)
        formatted["memos"] = {
            coin_id.hex(): memo.hex()
            for coin_id, memos in self.get_memos().items()
            for memo in memos
            if memo is not None
        }
        return formatted
