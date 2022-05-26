from dataclasses import dataclass
from typing import List, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof


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

    pending_transaction: bool
    """Indicate if the NFT is pending for a transaction"""


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
