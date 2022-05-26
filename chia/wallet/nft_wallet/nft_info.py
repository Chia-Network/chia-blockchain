from dataclasses import dataclass
from typing import List, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.load_clvm import load_clvm

LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")


@streamable
@dataclass(frozen=True)
class NFTInfo(Streamable):
    """NFT Info for displaying NFT on the UI"""

    launcher_id: bytes32
    """Launcher coin ID"""

    nft_coin_id: bytes32
    """Current NFT coin ID"""

    did_owner: str
    """Owner DID"""

    royalty: uint64
    """Percentage of the transaction fee paid to the author, e.g. 1000 = 1%"""

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

    pending_transaction: bool = False
    """Indicate if the NFT is pending for a transaction"""

    launcher_puzhash: bytes32 = LAUNCHER_PUZZLE.get_tree_hash()
    """Puzzle hash of the singleton launcher in hex"""


@streamable
@dataclass(frozen=True)
class NFTCoinInfo(Streamable):
    coin: Coin
    lineage_proof: Optional[LineageProof]
    full_puzzle: Program
    pending_transaction: bool = False


@streamable
@dataclass(frozen=True)
class NFTWalletInfo(Streamable):
    my_nft_coins: List[NFTCoinInfo]
    did_wallet_id: Optional[uint32] = None
