import logging
from typing import List, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
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


def get_uri_list_from_puzzle(puzzle: Program) -> List[Tuple[bytes, bytes]]:
    matched, singleton_args, curried_args = match_nft_puzzle(puzzle)
    if matched:
        return list(curried_args[1].as_iter())
    raise ValueError("Not an NFT puzzle ")


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


def match_nft_puzzle(puzzle: Program) -> Tuple[bool, Program, List[Program]]:
    """
    Given a puzzle test if it's an NFT and, if it is, return the curried arguments
    """
    try:
        mod, singleton_curried_args = puzzle.uncurry()
        if mod == SINGLETON_TOP_LAYER_MOD:
            mod, curried_args = singleton_curried_args.rest().first().uncurry()
            log.debug("Got a singleton matched: %r", singleton_curried_args)
            if mod == NFT_STATE_LAYER_MOD:
                log.debug("Got a NFT MOD matched: %s", curried_args)
                return True, singleton_curried_args, list(curried_args.as_iter())
    except Exception:
        log.exception("Error extracting NFT puzzle arguments")
        return False, Program.to([]), []
    return False, Program.to([]), []
