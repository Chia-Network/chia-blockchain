from blspy import AugSchemeMPL, G1Element, PrivateKey

from chia.clvm.singleton import P2_SINGLETON_MOD, SINGLETON_TOP_LAYER_MOD, SINGLETON_LAUNCHER
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_solution import CoinSolution
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes
from chia.util.condition_tools import parse_sexp_to_conditions
from chia.wallet.derive_keys import master_sk_to_wallet_sk
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.announcement import Announcement
from chia.pools.pool_puzzles import (
    POOL_OUTER_MOD,
    POOL_ESCAPING_MOD,
    POOL_MEMBER_MOD,
    create_pool_member_innerpuz,
    create_fullpuz,
    get_pubkey_from_member_innerpuz,
    POOL_ESCAPING_INNER_HASH,
    P2_SINGLETON_HASH,
    generate_pool_eve_spend,
    create_self_pooling_innerpuz,
)
from chia.util.ints import uint32, uint64
from tests.core.full_node.test_conditions import check_conditions, initial_blocks, check_spend_bundle_validity
from tests.wallet.test_singleton import LAUNCHER_PUZZLE_HASH, LAUNCHER_ID, singleton_puzzle, p2_singleton_puzzle


def test_p2_singleton():
    # create a singleton. This should call driver code.
    launcher_id = LAUNCHER_ID
    owner_puzzlehash = 32 * "b\1"
    owner_pubkey = 32 * b"\2"
    innerpuz = create_self_pooling_innerpuz(owner_puzzlehash, owner_pubkey)
    singleton_full_puzzle = singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH, innerpuz)

    # create a fake coin id for the `p2_singleton`
    p2_singleton_coin_id = Program.to(["test_hash"]).get_tree_hash()
    expected_announcement = Announcement(singleton_full_puzzle.get_tree_hash(), p2_singleton_coin_id).name()

    # create a `p2_singleton` puzzle. This should call driver code.
    p2_singleton_full = p2_singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH)
    solution = Program.to([innerpuz.get_tree_hash(), p2_singleton_coin_id])
    cost, result = p2_singleton_full.run_with_cost(INFINITE_COST, solution)
    err, conditions = parse_sexp_to_conditions(result)
    assert err is None

    p2_singleton_full = p2_singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH)
    solution = Program.to([innerpuz.get_tree_hash(), p2_singleton_coin_id])
    cost, result = p2_singleton_full.run_with_cost(INFINITE_COST, solution)
    assert result.first().rest().first().as_atom() == expected_announcement
    assert conditions[0].vars[0] == expected_announcement


def test_create():
    innerpuz = Program.to(1)
    genesis_id = 0xCAFEF00D
    genesis_puzhash = genesis_id
    create_fullpuz(innerpuz, genesis_puzhash)


def test_uncurry():
    pass


def test_singleton_creation_with_eve_and_launcher():
    amount = uint64(1)
    genesis_launcher_puz = SINGLETON_LAUNCHER
    origin_coin = Coin(b"\1" * 32, b"\1" * 32, uint64(1234))
    our_puzzle_hash: bytes32 = b"\1" * 32
    pool_puzhash: bytes = b"\2" * 32
    private_key: PrivateKey = AugSchemeMPL.key_gen(bytes([2] * 32))
    owner_pubkey = private_key.get_g1()

    # sk = BasicSchemeMPL.key_gen(b"\1" * 32)
    # pk = sk.get_g1()

    launcher_coin = Coin(origin_coin.name(), genesis_launcher_puz.get_tree_hash(), amount)
    genesis_id = launcher_coin.name()
    self_pooling_inner_puzzle = create_self_pooling_innerpuz(our_puzzle_hash, owner_pubkey)
    full_puzzle = create_fullpuz(self_pooling_inner_puzzle, genesis_id)
    eve_coin = Coin(launcher_coin.name(), full_puzzle.get_tree_hash(), amount)

    # pubkey = did_wallet_puzzles.get_pubkey_from_innerpuz(innerpuz)
    # index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
    # private = master_sk_to_wallet_sk(self.wallet_state_manager.private_key, index)


    pool_reward_amount = 4000000000000
    pool_reward_height = 101
    relative_lock_height = uint32(10)
    eve_spend: SpendBundle = generate_pool_eve_spend(
        origin_coin,
        eve_coin,
        launcher_coin,
        private_key,
        owner_pubkey,
        our_puzzle_hash,
        pool_reward_amount,
        pool_reward_height,
        pool_puzhash,
        relative_lock_height,
    )
    assert eve_spend
    """
def test_singleton_creation_with_eve_and_launcher():
    from chia.consensus.constants import ConsensusConstants

    launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), amount)

    # inner: Program = await self.get_new_innerpuz()
    # full_puz = pool_wallet_puzzles.create_fullpuz(did_inner, launcher_coin.name())

    # inner always starts in "member" state; either self or pooled
    # our_pubkey, our_puzzle_hash = await self._get_pubkey_and_puzzle_hash()
    our_pubkey, our_puzzle_hash = self.current_rewards_pubkey, self.current_rewards_puzhash

    self_pooling_inner_puzzle = create_self_pooling_innerpuz(our_puzzle_hash, our_pubkey)
    genesis_puzhash = genesis_launcher_puz.get_tree_hash()  # or should this be the coin id?
    full_self_pooling_puzzle = create_fullpuz(self_pooling_inner_puzzle, genesis_puzhash)
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
    current_rewards_puzhash = hexstr_to_bytes("738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7")
    owner_pubkey = coin.amount, current_rewards_pubkey
    innersol = Program.to(
        # Note: The Pool MUST check the reveal of the new singleton
        # to confirm e.g. that the escape puzhash is what they expect
        # TODO: update rewards puzhash after state transition
        [
            0,
            innerpuz.get_tree_hash(),
            coin.amount,
            current_rewards_puzhash,
            POOL_ESCAPING_INNER_HASH,
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
    pubkey = get_pubkey_from_member_innerpuz(innerpuz)
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
