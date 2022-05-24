from dataclasses import dataclass
from typing import List

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable
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

    launcher_puzhash: bytes32 = LAUNCHER_PUZZLE.get_tree_hash()
    """Puzzle hash of the singleton launcher in hex"""
