from __future__ import annotations

from dataclasses import dataclass

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.singleton import SINGLETON_LAUNCHER_PUZZLE_HASH

IN_TRANSACTION_STATUS = "IN_TRANSACTION"
DEFAULT_STATUS = "DEFAULT"


@streamable
@dataclass(frozen=True)
class NFTInfo(Streamable):
    """NFT Info for displaying NFT on the UI"""

    nft_id: str

    launcher_id: bytes32
    """Launcher coin ID"""

    nft_coin_id: bytes32
    """Current NFT coin ID"""

    nft_coin_confirmation_height: uint32
    """Current NFT coin confirmation height"""

    owner_did: bytes32 | None
    """Owner DID"""

    royalty_percentage: uint16 | None
    """Percentage of the transaction fee paid to the author, e.g. 1000 = 1%"""

    royalty_puzzle_hash: bytes32 | None
    """Puzzle hash where royalty will be sent to"""
    data_uris: list[str]
    """ A list of content URIs"""

    data_hash: bytes
    """Hash of the content"""

    metadata_uris: list[str]
    """A list of metadata URIs"""

    metadata_hash: bytes
    """Hash of the metadata"""

    license_uris: list[str]
    """A list of license URIs"""

    license_hash: bytes
    """Hash of the license"""

    edition_total: uint64
    """How many NFTs in the current edition"""

    edition_number: uint64
    """Number of the current NFT in the edition"""

    updater_puzhash: bytes32
    """Puzzle hash of the metadata updater in hex"""

    chain_info: str
    """Information saved on the chain in hex"""

    mint_height: uint32
    """Block height of the NFT minting"""

    supports_did: bool
    """If the inner puzzle supports DID"""

    p2_address: bytes32
    """The innermost puzzle hash of the NFT"""

    pending_transaction: bool = False
    """Indicate if the NFT is pending for a transaction"""

    minter_did: bytes32 | None = None
    """DID of the NFT minter"""

    launcher_puzhash: bytes32 = SINGLETON_LAUNCHER_PUZZLE_HASH
    """Puzzle hash of the singleton launcher in hex"""

    off_chain_metadata: str | None = None
    """Serialized off-chain metadata"""


@streamable
@dataclass(frozen=True)
class NFTCoinInfo(Streamable):
    """The launcher coin ID of the NFT"""

    nft_id: bytes32
    """The latest coin of the NFT"""
    coin: Coin
    """NFT lineage proof"""
    lineage_proof: LineageProof | None
    """NFT full puzzle"""
    full_puzzle: Program
    """NFT minting block height"""
    mint_height: uint32
    """The DID of the NFT minter"""
    minter_did: bytes32 | None = None
    """The block height of the latest coin"""
    latest_height: uint32 = uint32(0)
    """If the NFT is in the transaction"""
    pending_transaction: bool = False


@streamable
@dataclass(frozen=True)
class NFTWalletInfo(Streamable):
    did_id: bytes32 | None = None
