from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof


@streamable
@dataclass(frozen=True)
class ProposalInfo(Streamable):
    proposal_id: bytes32  # this is launcher_id
    inner_puzzle: Program
    amount_voted: uint64
    yes_votes: uint64
    current_coin: Coin
    current_innerpuz: Optional[Program]
    timer_coin: Optional[Coin]  # if this is None then the proposal has finished
    singleton_block_height: uint32  # Block height that current proposal singleton coin was created in
    passed: bool
    closed: bool


@streamable
@dataclass(frozen=True)
class DAOInfo(Streamable):
    treasury_id: bytes32
    cat_wallet_id: uint32
    dao_cat_wallet_id: uint32
    proposals_list: List[ProposalInfo]
    parent_info: List[Tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): LineageProof}
    current_treasury_coin: Optional[Coin]
    current_treasury_innerpuz: Optional[Program]
    singleton_block_height: uint32  # the block height that the current treasury singleton was created in
    filter_below_vote_amount: uint64  # we ignore proposals with fewer votes than this - defaults to 1
    assets: List[Optional[bytes32]]
    current_height: uint64


@streamable
@dataclass(frozen=True)
class DAORules(Streamable):
    proposal_timelock: uint64
    soft_close_length: uint64
    attendance_required: uint64
    pass_percentage: uint64
    self_destruct_length: uint64
    oracle_spend_delay: uint64
    proposal_minimum_amount: uint64


class ProposalType(Enum):
    SPEND = "s"
    UPDATE = "u"
    MINT = "m"
