from dataclasses import dataclass
from typing import List

from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class NFTInfo(Streamable):
    """NFT Info for displaying NFT on the UI"""

    launcher_id: str
    """Launcher coin ID"""

    nft_coin_id: str
    """Current NFT coin ID"""

    did_owner: str
    """Owner DID"""

    royalty: uint64
    """Percentage of the transaction fee paid to the author, e.g. 1000 = 1%"""

    data_uris: List[str]
    """ A list of content URIs"""

    data_hash: str
    """Hash of the content"""

    metadata_uris: List[str]
    """A list of metadata URIs"""

    metadata_hash: str
    """Hash of the metadata"""

    license_uris: List[str]
    """A list of license URIs"""

    license_hash: str
    """Hash of the license"""

    version: str
    """Current NFT version"""

    edition_count: uint64
    """How many NFTs in the current series"""

    edition_number: uint64
    """Number of the current NFT in the series"""
