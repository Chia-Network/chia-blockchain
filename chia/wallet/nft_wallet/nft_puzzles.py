from typing import Iterator, List, Optional, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
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


def match_nft_puzzle(puzzle: Program) -> Tuple[bool, Iterator[Program]]:
    """
    Given a puzzle test if it's an NFT and, if it is, return the curried arguments
    """
    try:
        mod, curried_args = puzzle.uncurry()
        if mod == SINGLETON_TOP_LAYER_MOD:
            mod, curried_args = curried_args.rest().first().uncurry()
            if mod == NFT_MOD:
                return True, curried_args.as_iter()
    except Exception:
        import traceback

        print(f"exception: {traceback.format_exc()}")
        return False, iter(())
    return False, iter(())


def get_nft_id_from_puzzle(puzzle: Program) -> Optional[bytes32]:
    """
    Given a puzzle test if it's an NFT and, if it is, return the curried arguments
    """
    try:
        mod, curried_args = puzzle.uncurry()
        if mod == SINGLETON_TOP_LAYER_MOD:
            nft_id: bytes32 = curried_args.first().rest().first().as_atom()
            return nft_id
    except Exception:
        return None
    return None


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
    return None


def get_transfer_program_curried_args_from_puzzle(puzzle: Program) -> Optional[Program]:
    try:
        curried_args = match_nft_puzzle(puzzle)[1]
        (
            NFT_MOD_HASH,
            singleton_struct,
            current_owner_did,
            nft_transfer_program_hash,
            transfer_program_curry_params,
            metadata,
        ) = curried_args
        return transfer_program_curry_params
    except Exception:
        return None
    return None


def get_royalty_address_from_puzzle(puzzle: Program) -> Optional[bytes32]:
    try:
        transfer_program_curry_params = get_transfer_program_curried_args_from_puzzle(puzzle)
        if transfer_program_curry_params is not None:
            (
                ROYALTY_ADDRESS,
                TRADE_PRICE_PERCENTAGE,
                SETTLEMENT_MOD_HASH,
                CAT_MOD_HASH,
            ) = transfer_program_curry_params.as_iter()
            assert ROYALTY_ADDRESS is not None
            royalty_address: bytes32 = ROYALTY_ADDRESS.as_atom()
            return royalty_address
    except Exception:
        return None
    return None


def get_percentage_from_puzzle(puzzle: Program) -> Optional[uint64]:
    try:
        transfer_program_curry_params = get_transfer_program_curried_args_from_puzzle(puzzle)
        if transfer_program_curry_params is not None:
            (
                ROYALTY_ADDRESS,
                TRADE_PRICE_PERCENTAGE,
                SETTLEMENT_MOD_HASH,
                CAT_MOD_HASH,
            ) = transfer_program_curry_params.as_iter()
            assert TRADE_PRICE_PERCENTAGE is not None
            percentage: uint64 = TRADE_PRICE_PERCENTAGE.as_int()
            return percentage
    except Exception:
        return None
    return None


def get_metadata_from_puzzle(puzzle: Program) -> Optional[Program]:
    try:
        curried_args = match_nft_puzzle(puzzle)[1]
        (
            NFT_MOD_HASH,
            singleton_struct,
            current_owner_did,
            nft_transfer_program_hash,
            transfer_program_curry_params,
            metadata,
        ) = curried_args
        return metadata
    except Exception:
        return None
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
    return None


def get_trade_prices_list_from_inner_solution(solution: Program) -> Optional[Program]:
    try:
        prog: Program = solution.rest().rest().rest().rest().first().first()
        return prog
    except Exception:
        return None
    return None


def get_transfer_program_solution_from_solution(solution: Program) -> Optional[Program]:
    try:
        prog_sol: Program = solution.rest().rest().rest().rest().first()
        return prog_sol
    except Exception:
        return None
    return None
