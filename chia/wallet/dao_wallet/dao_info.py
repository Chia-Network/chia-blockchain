from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.dao_wallet.dao_wallet import ProposalInfo
from chia.wallet.lineage_proof import LineageProof


@streamable
@dataclass(frozen=True)
class DAOInfo(Streamable):
    treasury_id: bytes32
    cat_wallet_id: uint64
    proposals_list: List[ProposalInfo]
    parent_info: List[Tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): LineageProof}
