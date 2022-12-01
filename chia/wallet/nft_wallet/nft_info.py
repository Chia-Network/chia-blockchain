from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile

LAUNCHER_PUZZLE = load_clvm_maybe_recompile("singleton_launcher.clvm")
IN_TRANSACTION_STATUS = "IN_TRANSACTION"
DEFAULT_STATUS = "DEFAULT"


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

    minter_did: Optional[bytes32] = None
    """DID of the NFT minter"""

    launcher_puzhash: bytes32 = LAUNCHER_PUZZLE.get_tree_hash()
    """Puzzle hash of the singleton launcher in hex"""

    off_chain_metadata: Optional[str] = None
    """Serialized off-chain metadata"""


@streamable
@dataclass(frozen=True)
class NFTCoinInfo(Streamable):
    """The launcher coin ID of the NFT"""

    nft_id: bytes32
    """The latest coin of the NFT"""
    coin: Coin
    """NFT lineage proof"""
    lineage_proof: Optional[LineageProof]
    """NFT full puzzle"""
    full_puzzle: Program
    """NFT minting block height"""
    mint_height: uint32
    """The DID of the NFT minter"""
    minter_did: Optional[bytes32] = None
    """The block height of the latest coin"""
    latest_height: uint32 = uint32(0)
    """If the NFT is in the transaction"""
    pending_transaction: bool = False


@streamable
@dataclass(frozen=True)
class NFTWalletInfo(Streamable):
    did_id: Optional[bytes32] = None
