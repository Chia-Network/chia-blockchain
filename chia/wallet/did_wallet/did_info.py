from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint64

from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import NIL, Program
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.util.curry_and_treehash import NIL_TREEHASH

# hardcode values to use for supporting DIDs from third party wallet
# that use an actually empty recovery list instead of the hash of an empty list
# For DB reasons, the reference wallet needs somethign to store in the DB
# This was randomly generated and doesn't correspond to any real recovery list
# and cannot be used to recover anything
# alternate_wallet_nil_recovery_list_bytes = bytes32.fromhex(
#    "1e56bb33a795ec7d8039708d2783491c22e55b94c9cec43911807064353ddbb8"
# )


# def did_recovery_as_bytes(recovery_program: Program) -> bytes:
#    try:
#        return recovery_program.as_atom()
#    except ValueError:
#        return bytes(Program.to(None))


def did_recovery_is_nil(recovery_program: Program) -> bool:
    # cannot use set as not hashable
    if recovery_program in (NIL, NIL_TREEHASH):  # noqa: PLR6201
        return True
    else:
        return False


@streamable
@dataclass(frozen=True)
class DIDInfo(Streamable):
    origin_coin: Optional[Coin]  # Coin ID of this coin is our DID
    backup_ids: list[bytes32]
    num_of_backup_ids_needed: uint64
    parent_info: list[tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): LineageProof}
    current_inner: Optional[Program]  # represents a Program as bytes
    temp_coin: Optional[Coin]  # partially recovered wallet uses these to hold info
    temp_puzhash: Optional[bytes32]
    temp_pubkey: Optional[bytes]
    sent_recovery_transaction: bool
    metadata: str  # JSON of the user defined metadata


@streamable
@dataclass(frozen=True)
class DIDCoinData(Streamable):
    p2_puzzle: Program
    recovery_list_hash: bytes
    num_verification: uint16
    singleton_struct: Program
    metadata: Program
    inner_puzzle: Optional[Program]
    coin_state: CoinState
