from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64, uint32
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof
from chia.types.blockchain_format.coin import Coin


@streamable
@dataclass(frozen=True)
class ProposalInfo(Streamable):
    proposal_id: bytes32  # this is launcher_id
    inner_puzzle: Program
    amount_voted: uint64
    is_yes_vote: Optional[bool]
    current_coin: Coin
    current_innerpuz: Optional[Program]
    timer_coin: Optional[Coin]  # if this is None then the proposal has finished
    singleton_block_height: uint32  # Block height that current proposal singleton coin was created in


@streamable
@dataclass(frozen=True)
class DAOInfo(Streamable):
    treasury_id: bytes32
    cat_wallet_id: uint64
    dao_cat_wallet_id: uint64
    proposals_list: List[ProposalInfo]
    parent_info: List[Tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): LineageProof}
    current_treasury_coin: Optional[Coin]
    current_treasury_innerpuz: Optional[Program]
    singleton_block_height: uint32  # the block height that the current treasury singleton was created in
    filter_below_vote_amount: uint64  # we ignore proposals with fewer votes than this - defaults to 1
