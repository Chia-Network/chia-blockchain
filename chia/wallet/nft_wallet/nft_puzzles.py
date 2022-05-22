import logging
from typing import List, Set
from chia.types.announcement import Announcement

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.wallet.nft_wallet.nft_info import NFTInfo
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.puzzles.load_clvm import load_clvm

from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import solution_for_conditions
from chia.wallet.puzzles.puzzle_utils import make_create_coin_condition
from chia.wallet.util.debug_spend_bundle import disassemble

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
NFT_OWNERSHIP_LAYER = load_clvm("nft_ownership_layer.clvm")
NFT_TRANSFER_PROGRAM_DEFAULT = load_clvm("nft_ownership_transfer_program_one_way_claim_with_royalties.clvm")
NFT_INNER_INNERPUZ = load_clvm("nft_v1_innerpuz.clvm")
STANDARD_PUZZLE_MOD = load_clvm("p2_delegated_puzzle_or_hidden_puzzle.clvm")


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


def create_ownership_layer_puzzle(nft_id, did_id, p2_puzzle, percentage):
    log.debug(f"Creating ownership layer puzzle with {nft_id=} {did_id=} {percentage=} {p2_puzzle=}")
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (nft_id, LAUNCHER_PUZZLE_HASH)))
    transfer_program = NFT_TRANSFER_PROGRAM_DEFAULT.curry(
        singleton_struct,
        p2_puzzle.get_tree_hash(),
        percentage,
        OFFER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
    )
    nft_inner_puzzle = NFT_INNER_INNERPUZ.curry(
        NFT_INNER_INNERPUZ.get_tree_hash(), NFT_INNER_INNERPUZ.get_tree_hash(), p2_puzzle
    )
    nft_ownership_layer_puzzle = NFT_OWNERSHIP_LAYER.curry(
        NFT_OWNERSHIP_LAYER.get_tree_hash(), did_id, transfer_program, nft_inner_puzzle
    )
    return nft_ownership_layer_puzzle


def create_ownership_layer_transfer_solution(new_did, new_did_inner_hash, trade_prices_list, new_pubkey, conditions=[]):
    log.debug(f"Creating a transfer solution with: {new_did=} {new_did_inner_hash=} {trade_prices_list=} {new_pubkey=}")
    condition_list = [new_did, [trade_prices_list], new_pubkey, [new_did_inner_hash], 0, 0, conditions]
    log.debug("Condition list raw: %r", condition_list)
    solution = Program.to([[solution_for_conditions(condition_list)]])
    log.debug("Generated transfer solution: %s", disassemble(solution))
    return solution
