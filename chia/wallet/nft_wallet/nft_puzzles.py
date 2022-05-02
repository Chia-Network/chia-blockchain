import logging
from typing import List, Optional, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.load_clvm import load_clvm

log = logging.getLogger(__name__)
SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
DID_MOD = load_clvm("did_innerpuz.clvm")
NFT_MOD = load_clvm("nft_innerpuz.clvm")
NFT_STATE_LAYER_MOD = load_clvm("nft_state_layer.clvm")
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
NFT_MOD_HASH = NFT_MOD.get_tree_hash()
NFT_STATE_LAYER_MOD_HASH = NFT_STATE_LAYER_MOD.get_tree_hash()
NFT_TRANSFER_PROGRAM = load_clvm("nft_transfer_program.clvm")
OFFER_MOD = load_clvm("settlement_payments.clvm")


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
        NFT_MOD_HASH,
        metadata,
        metadata_updater_hash,
    )
    return NFT_STATE_LAYER_MOD.curry(NFT_MOD_HASH, metadata, metadata_updater_hash, inner_puzzle)


def create_full_puzzle(
    singleton_id: bytes32, metadata: Program, metadata_updater_puzhash: bytes32, inner_puzzle: Program
) -> Program:
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))
    singleton_inner_puzzle = create_nft_layer_puzzle_with_curry_params(metadata, metadata_updater_puzhash, inner_puzzle)
    log.debug(
        "Creating full NFT puzzle with: singleton struct: %s, inner_puzzle: %s",
        singleton_struct,
        singleton_inner_puzzle,
    )
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, singleton_inner_puzzle)


def match_nft_puzzle(puzzle: Program) -> Tuple[bool, List[Program], List[Program]]:
    """
    Given a puzzle test if it's an NFT and, if it is, return the curried arguments
    """
    try:
        mod, singleton_curried_args = puzzle.uncurry()
        if mod == SINGLETON_TOP_LAYER_MOD:
            log.debug("Got a singleton matched")
            mod, curried_args = singleton_curried_args.rest().first().uncurry()
            if mod == NFT_STATE_LAYER_MOD:
                log.debug("Got a NFT MOD matched")
                return True, list(singleton_curried_args.as_iter()), list(curried_args.as_iter())
    except Exception:
        log.exception("Error extracting NFT puzzle arguments")
        return False, [], []
    return False, [], []


def get_nft_id_from_puzzle(puzzle: Program) -> Optional[bytes32]:
    """
    Given a puzzle test if it's an NFT and, if it is, return the curried arguments
    """
    try:
        mod, curried_args = puzzle.uncurry()
        if mod == SINGLETON_TOP_LAYER_MOD:
            arg = curried_args.first().rest().first().atom
            if arg is not None:
                nft_id: bytes32 = bytes32(arg)
                return nft_id
            return None
    except Exception:
        return None
    return None


def get_metadata_from_puzzle(puzzle: Program) -> Optional[Program]:
    try:
        curried_args = match_nft_puzzle(puzzle)[1]
        (_, metadata, _, _) = curried_args
        return metadata
    except Exception:
        return None


def get_uri_list_from_puzzle(puzzle: Program) -> Optional[List[str]]:
    try:
        uri_list = []
        metadata = get_metadata_from_puzzle(puzzle)
        assert metadata is not None
        for kv_pair in metadata.as_iter():
            if kv_pair.first().as_atom() == b"u":
                for uri in kv_pair.rest().as_iter():
                    uri_list.append(uri.as_atom())
        return uri_list
    except Exception:
        return None
