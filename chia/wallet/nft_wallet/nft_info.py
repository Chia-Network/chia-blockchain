from dataclasses import dataclass
from typing import List, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.load_clvm import load_clvm

LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
IN_TRANSACTION_STATUS = "IN_TRANSACTION"
DEFAULT_STATUS = "DEFAULT"

NFT_HRP = "nft"


@streamable
@dataclass(frozen=True)
class NFTInfo(Streamable):
    """NFT Info for displaying NFT on the UI"""

    launcher_id: bytes32
    """Launcher coin ID"""

    nft_coin_id: bytes32
    """Current NFT coin ID"""

    owner_did: Optional[bytes32]
    """Owner DID"""

    royalty_percentage: Optional[uint16]
    """Percentage of the transaction fee paid to the author, e.g. 1000 = 1%"""

    royalty_puzzle_hash: Optional[bytes32]
    """Puzzle hash where royalty will be sent to"""
    data_uris: List[str]
    """ A list of content URIs"""

    data_hash: bytes
    """Hash of the content"""

    metadata_uris: List[str]
    """A list of metadata URIs"""

    metadata_hash: bytes
    """Hash of the metadata"""

    license_uris: List[str]
    """A list of license URIs"""

    license_hash: bytes
    """Hash of the license"""

    series_total: uint64
    """How many NFTs in the current series"""

    series_number: uint64
    """Number of the current NFT in the series"""

    updater_puzhash: bytes32
    """Puzzle hash of the metadata updater in hex"""

    chain_info: str
    """Information saved on the chain in hex"""

    mint_height: uint32
    """Block height of the NFT minting"""

    supports_did: bool
    """If the inner puzzle supports DID"""

    pending_transaction: bool = False
    """Indicate if the NFT is pending for a transaction"""

    launcher_puzhash: bytes32 = LAUNCHER_PUZZLE.get_tree_hash()
    """Puzzle hash of the singleton launcher in hex"""


@streamable
@dataclass(frozen=True)
class NFTCoinInfo(Streamable):
    nft_id: bytes32
    coin: Coin
    lineage_proof: Optional[LineageProof]
    full_puzzle: Program
    mint_height: uint32
    pending_transaction: bool = False


@streamable
@dataclass(frozen=True)
class NFTWalletInfo(Streamable):
    did_id: Optional[bytes32] = None
