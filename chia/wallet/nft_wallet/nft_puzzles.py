
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.types.blockchain_format.program import Program
from typing import Tuple, Iterator, Optional
from chia.wallet.puzzles.load_clvm import load_clvm

SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
DID_MOD = load_clvm("did_innerpuz.clvm")
NFT_MOD = load_clvm("nft_innerpuz.clvm")
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
NFT_MOD_HASH = NFT_MOD.get_tree_hash()
NFT_PERCENTAGE_MOD = load_clvm("nft_percentage_program.clvm")
NFT_TRANSFER_PROGRAM = load_clvm("nft_transfer_program.clvm")


def create_nft_layer_puzzle(
    singleton_id: bytes32,
    current_owner_did: bytes32,
    nft_transfer_program_hash: bytes32
) -> Program:
    # NFT_MOD_HASH
    # SINGLETON_STRUCT ; ((SINGLETON_MOD_HASH, (NFT_SINGLETON_LAUNCHER_ID, LAUNCHER_PUZZLE_HASH)))
    # CURRENT_OWNER_DID
    # NFT_TRANSFER_PROGRAM_HASH
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))
    return NFT_MOD.curry(NFT_MOD_HASH, singleton_struct, current_owner_did, nft_transfer_program_hash)


def create_full_puzzle(singleton_id, current_owner_did, nft_transfer_program_hash):
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))
    innerpuz = create_nft_layer_puzzle(singleton_id, current_owner_did, nft_transfer_program_hash)
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, innerpuz)


def create_transfer_puzzle(uri, percentage, backpayment_address):
    ret = NFT_TRANSFER_PROGRAM.curry(Program.to([backpayment_address, percentage, uri]))
    return ret


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
        return False, iter(())
    return False, iter(())


def get_nft_id_from_puzzle(puzzle: Program) -> Optional[bytes32]:
    """
    Given a puzzle test if it's an NFT and, if it is, return the curried arguments
    """
    try:
        mod, curried_args = puzzle.uncurry()
        if mod == SINGLETON_TOP_LAYER_MOD:
            return curried_args.first().rest().first().as_atom()
    except Exception:
        return None
    return None


def get_transfer_program_from_solution(solution: Program) -> Program:
    try:
        prog = solution.rest().rest().rest().rest().rest().rest().rest().rest().rest().first()
        return prog
    except Exception:
        return None
    return None


def get_backpayment_amount_from_solution(solution: Program) -> uint64:
    try:
        transfer_prog = get_transfer_program_from_solution(solution)
        mod, curried_args = transfer_prog.uncurry()
        assert mod == NFT_TRANSFER_PROGRAM
        percentage = curried_args.first().rest().first().as_int()
        amount = (get_trade_price_from_solution(solution) * percentage) // 100
        return uint64(amount)
    except Exception:
        return None
    return None


def get_trade_price_from_solution(solution: Program) -> uint64:
    try:
        prog = solution.rest().rest().rest().rest().rest().rest().rest().rest().first()
        return prog.as_int()
    except Exception:
        return None
    return None
