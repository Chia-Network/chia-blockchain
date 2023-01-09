from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof
from chia.types.blockchain_format.coin import Coin


@streamable
@dataclass(frozen=True)
class ProposalInfo(Streamable):
    proposal_id: bytes32
    inner_puzzle: Program
    voted: bool
    current_coin: Coin
    current_innerpuz: Optional[Program]


@streamable
@dataclass(frozen=True)
class DAOInfo(Streamable):
    treasury_id: bytes32
    cat_wallet_id: uint64
    proposals_list: List[ProposalInfo]
    parent_info: List[Tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): LineageProof}
    current_treasury_coin: Optional[Coin]
    current_treasury_innerpuz: Optional[Program]
