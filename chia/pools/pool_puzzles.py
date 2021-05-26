from typing import List, Optional, Tuple
from blspy import G1Element, G2Element, AugSchemeMPL

# from clvm_tools import binutils
from chia.clvm.singleton import P2_SINGLETON_MOD, SINGLETON_TOP_LAYER_MOD, SINGLETON_LAUNCHER
from chia.consensus.default_constants import DEFAULT_CONSTANTS
# from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program

# from chia.types.coin_solution import CoinSolution
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_solution import CoinSolution
from chia.types.spend_bundle import SpendBundle
from chia.wallet.puzzles.load_clvm import load_clvm

# from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint32, uint64
# "Full" is the outer singleton, with the inner puzzle filled in
SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
POOL_ESCAPING_MOD = load_clvm("pool_escaping_innerpuz.clvm")
POOL_MEMBER_MOD = load_clvm("pool_member_innerpuz.clvm")
P2_SINGLETON_MOD = load_clvm("p2_singleton.clvm")
POOL_OUTER_MOD = SINGLETON_MOD
SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clvm")

POOL_ESCAPING_INNER_HASH = POOL_ESCAPING_MOD.get_tree_hash()
POOL_MEMBER_HASH = POOL_MEMBER_MOD.get_tree_hash()
P2_SINGLETON_HASH = P2_SINGLETON_MOD.get_tree_hash()
POOL_OUTER_MOD_HASH = POOL_OUTER_MOD.get_tree_hash()
SINGLETON_MOD_HASH = POOL_OUTER_MOD_HASH

SINGLETON_MOD_HASH_HASH = Program.to(SINGLETON_MOD_HASH).get_tree_hash()

# same challenge for every P2_SINGLETON puzzle
P2_SINGLETON_GENESIS_CHALLENGE = bytes.fromhex("ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb")


# TODO in pool_util create_p2_singleton_tx
def create_p2_singleton_puz():
    genesis_coin = Coin(SINGLETON_MOD_HASH, SINGLETON_MOD_HASH_HASH, uint64(200))
    genesis_id = genesis_coin.name()
    p2_singleton_full = P2_SINGLETON_MOD.curry(SINGLETON_MOD_HASH, SINGLETON_MOD_HASH_HASH, genesis_id)
    return p2_singleton_full


P2_SINGLETON_FULL = create_p2_singleton_puz()
P2_SINGLETON_FULL_HASH = P2_SINGLETON_FULL.get_tree_hash()


# TODO: Constrain "bytes" types in this file to a specific number of bytes.


def create_escaping_innerpuz(pool_puzhash: bytes, relative_lock_height: uint32, owner_pubkey: bytes) -> Program:
    return POOL_ESCAPING_MOD.curry(pool_puzhash, relative_lock_height, owner_pubkey, P2_SINGLETON_HASH)


def create_self_pooling_innerpuz(our_puzhash: bytes, pubkey: bytes) -> Program:
    relative_lock_height = 0  # TODO: test zero lock height
    return POOL_MEMBER_MOD.curry(our_puzhash, relative_lock_height, POOL_ESCAPING_INNER_HASH, P2_SINGLETON_HASH, pubkey)

    # New arguments
    '''
        [
            0,
            innerpuz.get_tree_hash(),  # should this be the singleton puz hash, or the inner puz hash?
            eve_coin.amount,
            our_puzzle_hash,  # should this be the p2_singleton puz hash, or the one from our main_wallet?
            POOL_ESCAPING_INNER_HASH,
            P2_SINGLETON_HASH,
            owner_pubkey,
        ]
    '''
def create_pool_member_innerpuz(pool_puzhash: bytes, relative_lock_height: uint32, owner_pubkey: bytes) -> Program:
    return POOL_MEMBER_MOD.curry(
        pool_puzhash, relative_lock_height, POOL_ESCAPING_INNER_HASH, P2_SINGLETON_HASH, owner_pubkey
    )


def create_fullpuz(innerpuz: Program, genesis_puzhash: bytes) -> Program:
    return POOL_OUTER_MOD.curry(POOL_OUTER_MOD_HASH, genesis_puzhash, innerpuz)


def create_p2_singleton_puzzle(singleton_mod_hash: bytes, genesis_id: bytes):
    # TODO: Test these hash conversions
    return P2_SINGLETON_MOD.curry(POOL_OUTER_MOD_HASH, Program.to(singleton_mod_hash).get_tree_hash(), genesis_id)


######################################


def is_escaping_innerpuz(inner_f: Program):
    return inner_f == POOL_ESCAPING_MOD


def is_pooling_innerpuz(inner_f: Program):
    return inner_f == POOL_MEMBER_MOD


def is_pool_protocol_innerpuz(inner_f: Program):
    return is_pooling_innerpuz(inner_f) or is_escaping_innerpuz(inner_f)


# Verify that a puzzle is a Pool Wallet Singleton
def is_pool_singleton_inner_puzzle(puzzle: Program):
    r = puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r
    return is_escaping_innerpuz(inner_f) or is_pooling_innerpuz(inner_f)

# Here is how to get a private key in the wallet framework:
# pubkey = get_pubkey_from_member_innerpuz(inner_puzzle)
# index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
# private_key = master_sk_to_wallet_sk(self.wallet_state_manager.private_key, index)
def generate_pool_eve_spend(origin_coin: Coin, eve_coin: Coin, launcher_coin: Coin,
                            private_key: G2Element, owner_pubkey: G1Element, our_puzzle_hash: bytes32,
                            pool_reward_amount, pool_reward_height,
                            pool_puzhash: bytes, relative_lock_height: uint32) -> SpendBundle:
    # Note: The Pool MUST check the reveal of the new singleton
    # to confirm that the escape puzhash is what they expect
    # def create_pool_member_innerpuz(pool_puzhash: bytes, relative_lock_height: uint32, pubkey: bytes) -> Program:
    genesis_id = launcher_coin.name()
    inner_puzzle: Program = create_pool_member_innerpuz(pool_puzhash, relative_lock_height, owner_pubkey)
    full_puzzle: Program = create_fullpuz(inner_puzzle, genesis_id)

    # inner_solution is:
    # ((singleton_id is_eve)
    # spend_type outer_puzhash my_amount pool_puzhash, escape_innerpuz_hash, p2_singleton_full_puzhash, owner_pubkey

    spend_type = 0
    my_amount = 1
    inner_solution = Program.to(
        [spend_type, inner_puzzle.get_tree_hash(), my_amount, pool_reward_amount, pool_reward_height]
    )

    # full solution is (parent_info my_amount inner_solution)
    full_solution = Program.to(
        [
            [origin_coin.parent_coin_info, origin_coin.amount],
            eve_coin.amount,
            inner_solution,
        ]
    )

    return generate_eve_spend(origin_coin, eve_coin, full_puzzle, inner_puzzle, private_key, owner_pubkey, our_puzzle_hash, full_solution)

######################################

# TODO: Move these to a common singleton file.


def generate_eve_spend(origin_coin: Coin, eve_coin: Coin, full_puzzle: Program, inner_puzzle: Program,
                       private_key: G2Element, owner_pubkey: G1Element, our_puzzle_hash: bytes32,
                       full_solution) -> SpendBundle:
    assert origin_coin is not None

    list_of_solutions = [CoinSolution(eve_coin, full_puzzle, full_solution)]
    # sign for AGG_SIG_ME
    message = (
            Program.to([eve_coin.amount, eve_coin.puzzle_hash]).get_tree_hash()
            + eve_coin.name()
            + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
    )

    signature = AugSchemeMPL.sign(private_key, message)
    sigs = [signature]
    aggsig = AugSchemeMPL.aggregate(sigs)
    spend_bundle = SpendBundle(list_of_solutions, aggsig)
    return spend_bundle


def get_pubkey_from_member_innerpuz(innerpuz: Program) -> G1Element:
    args = uncurry_pool_member_innerpuz(innerpuz)
    if args is not None:
        pool_puzhash, relative_lock_height, pubkey_program = args
        # pubkey_program = args[0]
    else:
        raise ValueError("Unable to extract pubkey")
    pubkey = G1Element.from_bytes(pubkey_program.as_atom())
    return pubkey


def uncurry_pool_member_innerpuz(puzzle: Program) -> Optional[Tuple[Program, Program]]:
    """
    Take a puzzle and return `None` if it's not a "pool member" inner puzzle, or
    a triple of `mod_hash, relative_lock_height, pubkey` if it is.
    """
    r = puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r
    if not is_pooling_innerpuz(inner_f):
        return None

    pool_puzhash, relative_lock_height, pool_escaping_inner_hash, p2_singleton_hash, pubkey = list(args.as_iter())
    assert pool_escaping_inner_hash == POOL_ESCAPING_INNER_HASH
    assert p2_singleton_hash == P2_SINGLETON_HASH

    return pool_puzhash, relative_lock_height, pubkey


def uncurry_pool_escaping_innerpuz(puzzle: Program) -> Optional[Tuple[Program, Program]]:
    pass


def get_innerpuzzle_from_puzzle(puzzle: Program) -> Optional[Program]:
    r = puzzle.uncurry()
    if r is None:
        return None
    inner_f, args = r
    if not is_pool_protocol_innerpuz(inner_f):
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
