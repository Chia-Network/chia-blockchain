# flake8: noqa: E501
from secrets import token_bytes
from typing import List

from blspy import AugSchemeMPL, G1Element

from chia.clvm.singleton import SINGLETON_LAUNCHER
from chia.pools.pool_wallet_info import PoolState, LEAVING_POOL, PoolWalletInfo
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import parse_sexp_to_conditions
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.coin_solution import CoinSolution
from chia.types.announcement import Announcement
from chia.pools.pool_puzzles import (
    create_full_puzzle,
    create_escaping_inner_puzzle,
    create_pooling_inner_puzzle,
    uncurry_pool_member_inner_puzzle,
    POOL_REWARD_PREFIX_MAINNET,
    pool_state_to_inner_puzzle,
    is_pool_member_inner_puzzle,
    is_pool_waitingroom_inner_puzzle,
    create_absorb_spend,
    solution_to_extra_data,
)
from chia.util.ints import uint32, uint64
from tests.wallet.test_singleton import LAUNCHER_PUZZLE_HASH, LAUNCHER_ID, singleton_puzzle, p2_singleton_puzzle, P2_SINGLETON_MOD, SINGLETON_MOD_HASH

# same challenge for every P2_SINGLETON puzzle
# P2_SINGLETON_GENESIS_CHALLENGE = bytes32.fromhex("ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb")

GENESIS_CHALLENGE = bytes32.fromhex("ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb")

GENESIS_CHALLENGE = bytes32.fromhex("ccd5bb71183532bff220ba46c268991a00000000000000000000000000000000")


def test_p2_singleton():
    # create a singleton. This should call driver code.
    launcher_id: bytes32 = LAUNCHER_ID
    owner_puzzle_hash: bytes32 = 32 * b"3"
    owner_pubkey: G1Element = AugSchemeMPL.key_gen(b"2" * 32).get_g1()
    pool_waiting_room_inner_hash: bytes32 = create_escaping_inner_puzzle(
        owner_puzzle_hash, uint32(0), owner_pubkey, launcher_id
    ).get_tree_hash()
    inner_puzzle: Program = create_pooling_inner_puzzle(
        owner_puzzle_hash, pool_waiting_room_inner_hash, owner_pubkey, launcher_id, GENESIS_CHALLENGE
    )
    singleton_full_puzzle: Program = singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH, inner_puzzle)

    # create a fake coin id for the `p2_singleton`
    p2_singleton_coin_id: bytes32 = Program.to(["test_hash"]).get_tree_hash()
    expected_announcement: bytes32 = Announcement(singleton_full_puzzle.get_tree_hash(), p2_singleton_coin_id).name()

    # create a `p2_singleton` puzzle. This should call driver code.
    p2_singleton_full: Program = p2_singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH)
    solution: Program = Program.to([inner_puzzle.get_tree_hash(), p2_singleton_coin_id])
    cost, result = p2_singleton_full.run_with_cost(INFINITE_COST, solution)
    err, conditions = parse_sexp_to_conditions(result)
    assert err is None

    p2_singleton_full = p2_singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH)
    solution = Program.to([inner_puzzle.get_tree_hash(), p2_singleton_coin_id])
    cost, result = p2_singleton_full.run_with_cost(INFINITE_COST, solution)
    assert result.first().rest().first().as_atom() == expected_announcement
    assert conditions[0].vars[0] == expected_announcement


def test_create():
    inner_puzzle: Program = Program.to(1)
    genesis_id: bytes32 = bytes32(b"2" * 32)
    genesis_puzzle_hash: bytes32 = genesis_id
    create_full_puzzle(inner_puzzle, genesis_puzzle_hash)


def test_uncurry():
    target_puzzle_hash: bytes32 = 32 * b"3"
    relative_lock_height = uint32(10)
    owner_pubkey: G1Element = AugSchemeMPL.key_gen(b"2" * 32).get_g1()
    escaping_inner_puzzle: Program = create_escaping_inner_puzzle(
        target_puzzle_hash, relative_lock_height, owner_pubkey, token_bytes(32)
    )
    pooling_inner_puzzle = create_pooling_inner_puzzle(
        target_puzzle_hash, escaping_inner_puzzle.get_tree_hash(), owner_pubkey, token_bytes(32), GENESIS_CHALLENGE
    )
    inner_f, target_puzzle_hash, p2_singleton_hash, owner_pubkey, pool_reward_prefix, escape_puzzlehash = uncurry_pool_member_inner_puzzle(pooling_inner_puzzle)
    # pool_puzzle_hash, pubkey = uncurry_pool_member_inner_puzzle(pooling_inner_puzzle)
    none = uncurry_pool_member_inner_puzzle(escaping_inner_puzzle)
    assert none is None


def test_pool_state_to_inner_puzzle():
    pool_state = PoolState(
        owner_pubkey=bytes.fromhex(
            "b286bbf7a10fa058d2a2a758921377ef00bb7f8143e1bd40dd195ae918dbef42cfc481140f01b9eae13b430a0c8fe304"
        ),
        pool_url="",
        relative_lock_height=0,
        state=1,
        target_puzzle_hash=bytes.fromhex("738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7"),
        version=1,
    )
    puzzle = pool_state_to_inner_puzzle(pool_state, token_bytes(32), GENESIS_CHALLENGE)
    assert is_pool_member_inner_puzzle(puzzle)

    target_puzzle_hash: bytes32 = bytes32(b"2" * 32)
    owner_pubkey: G1Element = AugSchemeMPL.key_gen(b"2" * 32).get_g1()
    relative_lock_height: uint32
    pool_state = PoolState(0, LEAVING_POOL.value, target_puzzle_hash, owner_pubkey, None, 0)

    puzzle = pool_state_to_inner_puzzle(pool_state, token_bytes(32), GENESIS_CHALLENGE)
    assert is_pool_waitingroom_inner_puzzle(puzzle)


def test_member_solution_to_extra_data():
    target_puzzle_hash = bytes.fromhex("738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7")
    owner_pubkey = bytes.fromhex("b286bbf7a10fa058d2a2a758921377ef00bb7f8143e1bd40dd195ae918dbef42cfc481140f01b9eae13b430a0c8fe304")
    relative_lock_height = 10
    starting_state = PoolState(
        owner_pubkey=owner_pubkey,
        pool_url="",
        relative_lock_height=relative_lock_height,
        state=1,
        target_puzzle_hash=target_puzzle_hash,
        version=1)

    escaping_inner_puzzle: Program = create_escaping_inner_puzzle(
        target_puzzle_hash, relative_lock_height, owner_pubkey, token_bytes(32)
    )
    pooling_inner_puzzle = create_pooling_inner_puzzle(
        target_puzzle_hash, escaping_inner_puzzle.get_tree_hash(), owner_pubkey, token_bytes(32), GENESIS_CHALLENGE
    )
    singleton_full_puzzle: Program = singleton_puzzle(LAUNCHER_ID, LAUNCHER_PUZZLE_HASH, pooling_inner_puzzle)

    coin = Coin(bytes32(b"2" * 32), singleton_full_puzzle.get_tree_hash(), 201)
    inner_sol: Program = Program.to([1, 0, 0, bytes(starting_state)])
    full_solution: Program = Program.to([[], 201, inner_sol])
    coin_sol = CoinSolution(coin, singleton_full_puzzle, full_solution)
    recovered_state: PoolState = solution_to_extra_data(coin_sol)

    assert recovered_state == starting_state


def test_escaping_solution_to_extra_data():
    target_puzzle_hash = bytes.fromhex("738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7")
    owner_pubkey = bytes.fromhex("b286bbf7a10fa058d2a2a758921377ef00bb7f8143e1bd40dd195ae918dbef42cfc481140f01b9eae13b430a0c8fe304")
    relative_lock_height = 10
    starting_state = PoolState(
        owner_pubkey=owner_pubkey,
        pool_url="",
        relative_lock_height=relative_lock_height,
        state=1,
        target_puzzle_hash=target_puzzle_hash,
        version=1)

    escaping_inner_puzzle: Program = create_escaping_inner_puzzle(
        target_puzzle_hash, relative_lock_height, owner_pubkey, token_bytes(32)
    )
    singleton_full_puzzle: Program = singleton_puzzle(LAUNCHER_ID, LAUNCHER_PUZZLE_HASH, escaping_inner_puzzle)

    coin = Coin(bytes32(b"2" * 32), singleton_full_puzzle.get_tree_hash(), 201)

    inner_sol: Program = Program.to([1, target_puzzle_hash, 0, 0, bytes(starting_state)])
    full_solution: Program = Program.to([[], 201, inner_sol])
    coin_sol = CoinSolution(coin, singleton_full_puzzle, full_solution)
    recovered_state: PoolState = solution_to_extra_data(coin_sol)

    assert recovered_state == starting_state


# This test is broken and does not work yet.
# TODO: FIX THIS TEST
def test_create_absorb_spend():
    launcher_coin = Coin(bytes32(b"f" * 32), LAUNCHER_PUZZLE_HASH, 201)
    owner_pubkey = bytes.fromhex("b286bbf7a10fa058d2a2a758921377ef00bb7f8143e1bd40dd195ae918dbef42cfc481140f01b9eae13b430a0c8fe304")
    target_puzzle_hash = bytes.fromhex("738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7")
    # curry params are SINGLETON_MOD_HASH LAUNCHER_ID LAUNCHER_PUZZLE_HASH
    p2_singleton_puzzle = P2_SINGLETON_MOD.curry(SINGLETON_MOD_HASH, launcher_coin.name(), LAUNCHER_PUZZLE_HASH)
    current_inner = create_escaping_inner_puzzle(target_puzzle_hash, 0, owner_pubkey, launcher_coin.name())
    full_puz = create_full_puzzle(current_inner, launcher_coin.name())
    parent_coin = Coin(launcher_coin.name(), full_puz.get_tree_hash(), 201)
    current_coin = Coin(parent_coin.name(), full_puz.get_tree_hash(), 201)
    current = PoolState(
        owner_pubkey=owner_pubkey,
        pool_url="",
        relative_lock_height=0,
        state=1,
        target_puzzle_hash=target_puzzle_hash,
        version=1)
    pool_info = PoolWalletInfo(
        current=current,
        target=current,
        launcher_coin=launcher_coin,
        launcher_id=launcher_coin.name(),
        p2_singleton_puzzle_hash=p2_singleton_puzzle.get_tree_hash(),
        current_inner=current_inner,
        tip_singleton_coin_id=current_coin.name()
    )

    inner_sol: Program = Program.to([1, current_inner.get_tree_hash(), 0, 0, bytes(pool_info.current)])
    last_parent_info = [launcher_coin.parent_coin_info, launcher_coin.amount]
    last_full_solution: Program = Program.to([last_parent_info, 201, inner_sol])
    last_coin_solution: CoinSolution = CoinSolution(parent_coin, full_puz, last_full_solution)
    spends: List[CoinSolution] = create_absorb_spend(
        last_coin_solution, pool_info.current, pool_info.launcher_coin, 1000, GENESIS_CHALLENGE
    )
    assert len(spends) > 0


'''
def test_create_escape_spend():
    last_coin_solution: CoinSolution = {'coin': {'amount': 1,
          'parent_coin_info': '0x7eafe79ac873ad528287f905620ee0eefb3bd1b70274a4c1a4817ca1db952007',
          'puzzle_hash': '0xeff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9'},
 'puzzle_reveal': '0xff02ffff01ff04ffff04ff04ffff04ff05ffff04ff0bff80808080ffff04ffff04ff0affff04ffff02ff0effff04ff02ffff04ffff04ff05ffff04ff0bffff04ff17ff80808080ff80808080ff808080ff808080ffff04ffff01ff33ff3cff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff0effff04ff02ffff04ff09ff80808080ffff02ff0effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080',
 'solution': '0xffa08eb5a4893f62881c6244604a79c36b23c06e8ae691f88322801b89c2dfaa8ae8ff01ffc05b0101738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7b286bbf7a10fa058d2a2a758921377ef00bb7f8143e1bd40dd195ae918dbef42cfc481140f01b9eae13b430a0c8fe30401000000000000000080'}
    pool_info: PoolWalletInfo =
    create_escape_spend(last_coin_solution, pool_info)
"""

"""
def test_singleton_creation_with_eve_and_launcher():
    amount: uint64 = uint64(1)
    genesis_launcher_puz: Program = SINGLETON_LAUNCHER
    origin_coin: Coin = Coin(b"\1" * 32, b"\1" * 32, uint64(1234))
    our_puzzle_hash: bytes32 = b"\1" * 32
    pool_puzzle_hash: bytes = b"\2" * 32
    private_key: PrivateKey = AugSchemeMPL.key_gen(bytes([2] * 32))
    owner_pubkey: G1Element = private_key.get_g1()

    # sk = BasicSchemeMPL.key_gen(b"\1" * 32)
    # pk = sk.get_g1()

    launcher_coin: Coin = Coin(origin_coin.name(), genesis_launcher_puz.get_tree_hash(), amount)
    genesis_id: bytes32 = launcher_coin.name()

    pool_waitingroom_inner_hash: bytes32 = create_escaping_inner_puzzle(
        our_puzzle_hash, uint32(0), owner_pubkey
    ).get_tree_hash()
    self_pooling_inner_puzzle = create_self_pooling_inner_puzzle(
        our_puzzle_hash, pool_waitingroom_inner_hash, owner_pubkey
    )
    full_puzzle = create_full_puzzle(self_pooling_inner_puzzle, genesis_id)
    eve_coin = Coin(launcher_coin.name(), full_puzzle.get_tree_hash(), amount)

    # pubkey = did_wallet_puzzles.get_pubkey_from_inner_puzzle(inner_puzzle)
    # index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
    # private = master_sk_to_wallet_sk(self.wallet_state_manager.private_key, index)

    pool_reward_amount = 4000000000000
    pool_reward_height = 101
    relative_lock_height = uint32(10)


def test_singleton_creation_with_eve_and_launcher():
    from chia.consensus.constants import ConsensusConstants

    launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), amount)

    # inner: Program = await self.get_new_inner_puzzle()
    # full_puz = pool_wallet_puzzles.create_full_puzzle(did_inner, launcher_coin.name())

    # inner always starts in "member" state; either self or pooled
    # our_pubkey, our_puzzle_hash = await self._get_pubkey_and_puzzle_hash()
    our_pubkey, our_puzzle_hash = self.current_rewards_pubkey, self.current_rewards_puzzle_hash

    self_pooling_inner_puzzle = create_self_pooling_inner_puzzle(our_puzzle_hash, our_pubkey)
    genesis_puzzle_hash = genesis_launcher_puz.get_tree_hash()  # or should this be the coin id?
    full_self_pooling_puzzle = create_full_puzzle(self_pooling_inner_puzzle, genesis_puzzle_hash)
    inner = self_pooling_inner_puzzle
    full_puz = full_self_pooling_puzzle
    coin = {
        "amount": 1,
        "parent_coin_info": "0x4ed5f1195300d479237070d095101a138142caa24c731d8de99b6c4e8d7f7b3d",
        "puzzle_hash": "0x924175b2583440413221321541e672989fe6d201ee0643d945b6679671f20d74",
    }
    origin_coin_puzzle_hash = 32 * b"\0"
    origin_coin = Coin(
        hexstr_to_bytes(
            "7eafe79ac873ad528287f905620ee0eefb3bd1b70274a4c1a4817ca1db952007", origin_coin_puzzle_hash, 100
        )
    )
    current_rewards_pubkey = hexstr_to_bytes(
        "844ab45b6bb8e674c8452de2a018209cf8a05ee25782fd12c6a202ffd953a28caa560f20a3838d4f31a1ad4fed573e94"
    )
    current_rewards_puzzle_hash = hexstr_to_bytes("738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7")
    owner_pubkey = coin.amount, current_rewards_pubkey
    innersol = Program.to(
        # Note: The Pool MUST check the reveal of the new singleton
        # to confirm e.g. that the escape puzzle_hash is what they expect
        # TODO: update rewards puzzle_hash after state transition
        [
            0,
            inner_puzzle.get_tree_hash(),
            coin.amount,
            current_rewards_puzzle_hash,
            POOL_WAITINGROOM_INNER_HASH,
            P2_SINGLETON_HASH,
            owner_pubkey,
        ]
    )

    # full solution is (parent_info my_amount inner_solution)
    fullsol = Program.to(
        [
            [self.pool_info.origin_coin.parent_coin_info, self.pool_info.origin_coin.amount],
            coin.amount,
            innersol,
        ]
    )
    list_of_solutions = [CoinSolution(coin, full_puzzle, fullsol)]
    # sign for AGG_SIG_ME
    message = (
        Program.to([coin.amount, coin.puzzle_hash]).get_tree_hash()
        + coin.name()
        + ConsensusConstants.AGG_SIG_ME_ADDITIONAL_DATA
    )
    pubkey = get_pubkey_from_member_inner_puzzle(inner_puzzle)
    #index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
    #private = master_sk_to_wallet_sk(self.wallet_state_manager.private_key, index)
    signature = AugSchemeMPL.sign(private, message)
    sigs = [signature]
    aggsig = AugSchemeMPL.aggregate(sigs)
    spend_bundle = SpendBundle(list_of_solutions, aggsig)
    return spend_bundle
"""


def test_pooling():
    pass
