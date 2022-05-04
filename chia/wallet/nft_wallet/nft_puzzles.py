from typing import Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.nft_wallet.nft_info import NFTInfo
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm

SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
DID_MOD = load_clvm("did_innerpuz.clvm")
NFT_MOD = load_clvm("nft_innerpuz.clvm")
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
NFT_MOD_HASH = NFT_MOD.get_tree_hash()
NFT_TRANSFER_PROGRAM = load_clvm("nft_transfer_program.clvm")
OFFER_MOD = load_clvm("settlement_payments.clvm")


def create_nft_layer_puzzle(
    singleton_id: bytes32,
    current_owner_did: bytes32,
    nft_transfer_program_mod_hash: bytes32,
    metadata: Program,
    backpayment_address: bytes32,
    percentage: uint64,
) -> Program:
    transfer_program_curry_params = [
        backpayment_address,
        percentage,
        OFFER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
    ]
    return create_nft_layer_puzzle_with_curry_params(
        singleton_id,
        current_owner_did,
        nft_transfer_program_mod_hash,
        metadata,
        Program.to(transfer_program_curry_params),
    )


def create_nft_layer_puzzle_with_curry_params(
    singleton_id: bytes32,
    current_owner_did: bytes32,
    nft_transfer_program_mod_hash: bytes32,
    metadata: Program,
    transfer_program_curry_params: Program,
) -> Program:
    # NFT_MOD_HASH
    # SINGLETON_STRUCT ; ((SINGLETON_MOD_HASH, (SINGLETON_LAUNCHER_ID, LAUNCHER_PUZZLE_HASH)))
    # CURRENT_OWNER_DID
    # TRANSFER_PROGRAM_MOD_HASH
    # TRANSFER_PROGRAM_CURRY_PARAMS
    # METADATA

    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))
    return NFT_MOD.curry(
        NFT_MOD_HASH,
        singleton_struct,
        current_owner_did,
        nft_transfer_program_mod_hash,
        transfer_program_curry_params,
        metadata,
    )


def create_full_puzzle(
    singleton_id: bytes32,
    current_owner_did: bytes32,
    nft_transfer_program_hash: bytes32,
    metadata: Program,
    backpayment_address: bytes32,
    percentage: uint64,
) -> Program:
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))
    innerpuz = create_nft_layer_puzzle(
        singleton_id, current_owner_did, nft_transfer_program_hash, metadata, backpayment_address, percentage
    )
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, innerpuz)


def create_full_puzzle_with_curry_params(
    singleton_id: bytes32,
    current_owner_did: bytes32,
    nft_transfer_program_hash: bytes32,
    metadata: Program,
    transfer_program_curry_params: Program,
) -> Program:
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))
    innerpuz = create_nft_layer_puzzle_with_curry_params(
        singleton_id, current_owner_did, nft_transfer_program_hash, metadata, transfer_program_curry_params
    )
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, innerpuz)


def get_transfer_puzzle() -> Program:
    return NFT_TRANSFER_PROGRAM


def update_metadata(metadata: Program, solution: Program) -> Program:
    tp_solution: Optional[Program] = get_transfer_program_solution_from_solution(solution)
    if tp_solution is None or tp_solution.rest().first() == Program.to(0):
        return metadata
    new_metadata = []
    for kv_pair in metadata.as_iter():
        if kv_pair.first().as_atom() == b"u":
            new_metadata.append(["u", kv_pair.rest().cons(tp_solution.rest())])
        else:
            new_metadata.append(kv_pair)
    updated_metadata: Program = Program.to(new_metadata)
    return updated_metadata


def get_transfer_program_from_inner_solution(solution: Program) -> Optional[Program]:
    try:
        prog: Program = solution.rest().rest().rest().first()
        return prog
    except Exception:
        return None


def get_nft_info_from_puzzle(puzzle: Program, nft_coin: Coin) -> NFTInfo:
    """
    Extract NFT info from a full puzzle
    :param puzzle: NFT full puzzle
    :param nft_coin: NFT coin
    :return: NFTInfo
    """
    # TODO Update this method after the NFT code finalized
    uncurried_nft: UncurriedNFT = UncurriedNFT.uncurry(puzzle, True)
    data_uris = []
    for uri in uncurried_nft.data_uris.as_python():
        data_uris.append(str(uri, "utf-8"))

    nft_info = NFTInfo(
        uncurried_nft.singleton_launcher_id.as_python().hex(),
        nft_coin.name().hex(),
        uncurried_nft.owner_did.as_python(),
        uint64(uncurried_nft.trade_price_percentage.as_int()),
        data_uris,
        uncurried_nft.data_hash.as_python().hex(),
        [],
        "",
        [],
        "",
        "1.0.0",
        uint64(1),
    )
    return nft_info


def get_trade_prices_list_from_inner_solution(solution: Program) -> Optional[Program]:
    try:
        prog: Program = solution.rest().rest().rest().rest().first().first()
        return prog
    except Exception:
        return None


def get_transfer_program_solution_from_solution(solution: Program) -> Optional[Program]:
    try:
        prog_sol: Program = solution.rest().rest().rest().rest().first()
        return prog_sol
    except Exception:
        return None
