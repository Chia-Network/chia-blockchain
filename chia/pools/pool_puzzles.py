from typing import Optional, Tuple
from blspy import G1Element, AugSchemeMPL, PrivateKey

from chia.clvm.singleton import P2_SINGLETON_MOD
from chia.consensus.default_constants import DEFAULT_CONSTANTS

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_solution import CoinSolution
from chia.types.spend_bundle import SpendBundle
from chia.wallet.puzzles.load_clvm import load_clvm

from chia.util.ints import uint32, uint64

# "Full" is the outer singleton, with the inner puzzle filled in
from tests.wallet.test_singleton import singleton_puzzle, LAUNCHER_PUZZLE_HASH

SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
POOL_ESCAPING_MOD = load_clvm("pool_escaping_innerpuz.clvm")
POOL_MEMBER_MOD = load_clvm("pool_member_innerpuz.clvm")
P2_SINGLETON_MOD = load_clvm("p2_singleton.clvm")
POOL_OUTER_MOD = SINGLETON_MOD
SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clvm")

POOL_MEMBER_HASH = POOL_MEMBER_MOD.get_tree_hash()
P2_SINGLETON_HASH = P2_SINGLETON_MOD.get_tree_hash()
POOL_OUTER_MOD_HASH = POOL_OUTER_MOD.get_tree_hash()
SINGLETON_LAUNCHER_HASH = SINGLETON_LAUNCHER.get_tree_hash()
SINGLETON_MOD_HASH = POOL_OUTER_MOD_HASH

SINGLETON_MOD_HASH_HASH = Program.to(SINGLETON_MOD_HASH).get_tree_hash()

# same challenge for every P2_SINGLETON puzzle
P2_SINGLETON_GENESIS_CHALLENGE = bytes32.fromhex("ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb")


def create_escaping_inner_puzzle(
    target_puzzle_hash: bytes32, relative_lock_height: uint32, owner_pubkey: G1Element
) -> Program:
    return POOL_ESCAPING_MOD.curry(target_puzzle_hash, relative_lock_height, bytes(owner_pubkey), P2_SINGLETON_HASH)


def create_pooling_inner_puzzle(
    target_puzzle_hash: bytes, pool_escaping_inner_hash: bytes32, owner_pubkey: G1Element
) -> Program:
    return POOL_MEMBER_MOD.curry(target_puzzle_hash, pool_escaping_inner_hash, P2_SINGLETON_HASH, bytes(owner_pubkey))


def create_full_puzzle(inner_puzzle: Program, launcher_id: bytes32) -> Program:
    return POOL_OUTER_MOD.curry(POOL_OUTER_MOD_HASH, launcher_id, inner_puzzle)


def create_p2_singleton_puzzle(singleton_mod_hash: bytes, launcher_id: bytes32) -> Program:
    # TODO: Test these hash conversions
    return P2_SINGLETON_MOD.curry(POOL_OUTER_MOD_HASH, Program.to(singleton_mod_hash).get_tree_hash(), launcher_id)


def launcher_id_to_p2_puzzle_hash(launcher_id: bytes32) -> bytes32:
    return create_p2_singleton_puzzle(SINGLETON_MOD_HASH, launcher_id).get_tree_hash()


######################################


def is_escaping_inner_puzzle(inner_f: Program) -> bool:
    return inner_f == POOL_ESCAPING_MOD


def is_pooling_inner_puzzle(inner_f: Program) -> bool:
    return inner_f == POOL_MEMBER_MOD


def is_pool_protocol_inner_puzzle(inner_f: Program) -> bool:
    return is_pooling_inner_puzzle(inner_f) or is_escaping_inner_puzzle(inner_f)


# Verify that a puzzle is a Pool Wallet Singleton
def is_pool_singleton_inner_puzzle(puzzle: Program) -> bool:
    r = puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r
    return is_escaping_inner_puzzle(inner_f) or is_pooling_inner_puzzle(inner_f)


# Here is how to get a private key in the wallet framework:
# pubkey = get_pubkey_from_member_inner_puzzle(inner_puzzle)
# index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
# private_key = master_sk_to_wallet_sk(self.wallet_state_manager.private_key, index)
def generate_pool_eve_spend(
    origin_coin: Coin,
    launcher_coin: Coin,
    private_key: PrivateKey,
    owner_pubkey: G1Element,
    pool_puzzlehash: bytes32,
    relative_lock_height: uint32,
) -> SpendBundle:
    # Note: The Pool MUST check the reveal of the new singleton
    # to confirm that the escape puzzle_hash is what they expect
    # def create_pool_member_inner_puzzle(pool_puzzle_hash: bytes, relative_lock_height: uint32, pubkey: bytes) -> Program:
    launcher_id = launcher_coin.name()

    pool_escaping_inner_hash: bytes32 = create_escaping_inner_puzzle(
        pool_puzzlehash, relative_lock_height, owner_pubkey
    )
    committed_inner_puzzle: Program = create_pooling_inner_puzzle(
        pool_puzzlehash, pool_escaping_inner_hash, owner_pubkey
    )
    # full_puzzle: Program = create_full_puzzle(inner_puzzle, genesis_id)

    full_puzzle = singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH, committed_inner_puzzle)

    # inner_solution is:
    # ((singleton_id is_eve)
    # spend_type outer_puzzle_hash my_amount pool_puzzle_hash, escape_inner_puzzle_hash, p2_singleton_full_puzzle_hash, owner_pubkey

    spend_type: int = 0
    my_amount: int = 1
    # Sanity check puzzles
    # inner_ret = committed_inner_puzzlezle.run(inner_solution)
    # full_ret = full_puzzle.run_with_cost(1e18, full_solution)

    return generate_eve_spend(origin_coin, launcher_coin, full_puzzle, committed_inner_puzzle, private_key)


######################################

# TODO: Move these to a common singleton file.


def generate_eve_spend(
    origin_coin: Coin, coin: Coin, full_puzzle: Program, inner_puzzle: Program, private_key: PrivateKey
) -> SpendBundle:
    assert origin_coin is not None
    # inner_puzzle solution is (mode amount message my_id new_puzzle_hash)
    innersol = Program.to([1, coin.amount, [], coin.name(), inner_puzzle.get_tree_hash()])
    # res = inner_puzzle.run(innersol)
    # print(res)
    # full solution is (parent_info my_amount innersolution)
    fullsol = Program.to(
        [
            [origin_coin.parent_coin_info, origin_coin.amount],
            coin.amount,
            innersol,
        ]
    )
    list_of_solutions = [CoinSolution(coin, full_puzzle, fullsol)]

    # res = full_puzzle.run(fullsol)

    # sign for AGG_SIG_ME
    message = (
        Program.to([inner_puzzle.get_tree_hash(), coin.amount, []]).get_tree_hash()
        + coin.name()
        + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
    )

    return SpendBundle(list_of_solutions, AugSchemeMPL.sign(private_key, message))


def get_pubkey_from_member_inner_puzzle(inner_puzzle: Program) -> G1Element:
    args = uncurry_pool_member_inner_puzzle(inner_puzzle)
    if args is not None:
        pool_puzzle_hash, relative_lock_height, pubkey_program = args
        # pubkey_program = args[0]
    else:
        raise ValueError("Unable to extract pubkey")
    pubkey = G1Element.from_bytes(pubkey_program.as_atom())
    return pubkey


def uncurry_pool_member_inner_puzzle(puzzle: Program) -> Optional[Tuple[Program, Program]]:
    """
    Take a puzzle and return `None` if it's not a "pool member" inner puzzle, or
    a triple of `mod_hash, relative_lock_height, pubkey` if it is.
    """
    r = puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r
    if not is_pooling_inner_puzzle(inner_f):
        return None

    pool_puzzle_hash, relative_lock_height, pool_escaping_inner_hash, p2_singleton_hash, pubkey = list(args.as_iter())
    assert p2_singleton_hash == P2_SINGLETON_HASH

    return pool_puzzle_hash, relative_lock_height, pubkey


def uncurry_pool_escaping_inner_puzzle(puzzle: Program) -> Optional[Tuple[Program, Program]]:
    pass


def get_inner_puzzle_from_puzzle(puzzle: Program) -> Optional[Program]:
    r = puzzle.uncurry()
    if r is None:
        return None
    inner_f, args = r
    if not is_pool_protocol_inner_puzzle(inner_f):
        return None
    mod_hash, genesis_id, inner_puzzle = list(args.as_iter())
    return inner_puzzle


"""
def create_spend_for_message(parent_of_message, recovering_coin, newpuz, pubkey):
    puzzle = create_recovery_message_puzzle(recovering_coin, newpuz, pubkey)
    coin = Coin(parent_of_message, puzzle.get_tree_hash(), uint64(0))
    solution = Program.to([])
    coinsol = CoinSolution(coin, puzzle, solution)
    return coinsol


"""
