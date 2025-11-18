from __future__ import annotations

from dataclasses import dataclass

from chia_rs import CoinState
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint64

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.util.curry_and_treehash import NIL_TREEHASH


def did_recovery_is_nil(recovery_program: Program) -> bool:
    # cannot use set as not hashable
    if recovery_program in (Program.NIL, NIL_TREEHASH):  # noqa: PLR6201
        return True
    else:
        return False


@streamable
@dataclass(frozen=True)
class DIDInfo(Streamable):
    origin_coin: Coin | None  # Coin ID of this coin is our DID
    backup_ids: list[bytes32]
    num_of_backup_ids_needed: uint64
    parent_info: list[tuple[bytes32, LineageProof | None]]  # {coin.name(): LineageProof}
    current_inner: Program | None  # represents a Program as bytes
    temp_coin: Coin | None  # partially recovered wallet uses these to hold info
    temp_puzhash: bytes32 | None
    temp_pubkey: bytes | None
    sent_recovery_transaction: bool
    metadata: str  # JSON of the user defined metadata


@streamable
@dataclass(frozen=True)
class DIDCoinData(Streamable):
    p2_puzzle: Program
    recovery_list_hash: bytes32 | None
    num_verification: uint16
    singleton_struct: Program
    metadata: Program
    inner_puzzle: Program | None
    coin_state: CoinState
