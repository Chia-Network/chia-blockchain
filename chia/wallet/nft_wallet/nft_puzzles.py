import logging
from typing import Any, Dict

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.nft_wallet.nft_info import NFTInfo
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.puzzles.load_clvm import load_clvm

log = logging.getLogger(__name__)
SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
NFT_STATE_LAYER_MOD = load_clvm("nft_state_layer.clvm")
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
NFT_STATE_LAYER_MOD_HASH = NFT_STATE_LAYER_MOD.get_tree_hash()
NFT_TRANSFER_PROGRAM = load_clvm("nft_transfer_program.clvm")
OFFER_MOD = load_clvm("settlement_payments.clvm")
NFT_METADATA_UPDATER = load_clvm("nft_metadata_updater_default.clvm")


def create_nft_layer_puzzle_with_curry_params(
    metadata: Program, metadata_updater_hash: bytes32, inner_puzzle: Program
) -> Program:
    """Curries params into nft_state_layer.clvm

    Args to curry:
        NFT_STATE_LAYER_MOD_HASH
        METADATA
        METADATA_UPDATER_PUZZLE_HASH
        INNER_PUZZLE"""
    log.debug(
        "Creating nft layer puzzle curry: mod_hash: %s, metadata: %r, metadata_hash: %s",
        NFT_STATE_LAYER_MOD_HASH,
        metadata,
        metadata_updater_hash,
    )
    return NFT_STATE_LAYER_MOD.curry(NFT_STATE_LAYER_MOD_HASH, metadata, metadata_updater_hash, inner_puzzle)


def create_full_puzzle_with_nft_puzzle(singleton_id: bytes32, inner_puzzle: Program) -> Program:
    log.debug(
        "Creating full NFT puzzle with inner puzzle: \n%r\n%r",
        singleton_id,
        inner_puzzle.get_tree_hash(),
    )
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))

    full_puzzle = SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, inner_puzzle)
    log.debug("Created NFT full puzzle with inner: %s", full_puzzle.get_tree_hash())
    return full_puzzle


def create_full_puzzle(
    singleton_id: bytes32, metadata: Program, metadata_updater_puzhash: bytes32, inner_puzzle: Program
) -> Program:
    log.debug(
        "Creating full NFT puzzle with: \n%r\n%r\n%r\n%r",
        singleton_id,
        metadata.get_tree_hash(),
        metadata_updater_puzhash,
        inner_puzzle.get_tree_hash(),
    )
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))
    singleton_inner_puzzle = create_nft_layer_puzzle_with_curry_params(metadata, metadata_updater_puzhash, inner_puzzle)

    full_puzzle = SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, singleton_inner_puzzle)
    log.debug("Created NFT full puzzle: %s", full_puzzle.get_tree_hash())
    return full_puzzle


def get_nft_info_from_puzzle(puzzle: Program, nft_coin: Coin) -> NFTInfo:
    """
    Extract NFT info from a full puzzle
    :param puzzle: NFT full puzzle
    :param nft_coin: NFT coin
    :return: NFTInfo
    """
    # TODO Update this method after the NFT code finalized
    uncurried_nft: UncurriedNFT = UncurriedNFT.uncurry(puzzle)
    data_uris = []
    for uri in uncurried_nft.data_uris.as_python():
        data_uris.append(str(uri, "utf-8"))

    nft_info = NFTInfo(
        uncurried_nft.singleton_launcher_id.as_python().hex().upper(),
        nft_coin.name().hex().upper(),
        uncurried_nft.owner_did.as_python().hex().upper(),
        uint64(uncurried_nft.trade_price_percentage.as_int()),
        data_uris,
        uncurried_nft.data_hash.as_python().hex().upper(),
        [],
        "",
        [],
        "",
        "NFT0",
        uint64(1),
        uint64(1),
    )
    return nft_info


def metadata_to_program(metadata: Dict[bytes, Any]) -> Program:
    """
    Convert the metadata dict to a Chialisp program
    :param metadata: User defined metadata
    :return: Chialisp program
    """
    kv_list = []
    for key, value in metadata.items():
        kv_list.append((key, value))
    program: Program = Program.to(kv_list)
    return program


def program_to_metadata(program: Program) -> Dict[bytes, Any]:
    """
    Convert a program to a metadata dict
    :param program: Chialisp program contains the metadata
    :return: Metadata dict
    """
    metadata = {}
    for kv_pair in program.as_iter():
        metadata[kv_pair.first().as_atom()] = kv_pair.rest().as_python()
    return metadata


def update_metadata(metadata: Program, update_condition: Program) -> Program:
    """
    Apply conditions of metadata updater to the previous metadata
    :param metadata: Previous metadata
    :param update_condition: Update metadata conditions
    :return: Updated metadata
    """
    new_metadata = program_to_metadata(metadata)
    # TODO Modify this for supporting other fields
    new_metadata[b"u"].insert(0, update_condition.rest().rest().first().atom)
    return metadata_to_program(new_metadata)
