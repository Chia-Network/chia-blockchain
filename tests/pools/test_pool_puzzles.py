from blspy import AugSchemeMPL

from chia.types.blockchain_format.coin import Coin
from chia.types.coin_solution import CoinSolution
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes
from chia.wallet.derive_keys import master_sk_to_wallet_sk
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.announcement import Announcement
from chia.pools.pool_puzzles import (
    POOL_OUTER_MOD,
    POOL_ESCAPING_MOD,
    POOL_MEMBER_MOD,
    create_innerpuz,
    create_fullpuz, get_pubkey_from_member_innerpuz, POOL_ESCAPING_INNER_HASH, P2_SINGLETON_HASH,
)  # , get_pubkey_from_innerpuz
from chia.util.ints import uint32


# tests/wallet/test_singleton
SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
P2_SINGLETON_MOD = load_clvm("p2_singleton.clvm")


def test_p2_singleton():
    singleton_mod_hash = SINGLETON_MOD.get_tree_hash()
    genesis_id = 0xCAFEF00D
    innerpuz = Program.to(1)
    singleton_full = SINGLETON_MOD.curry(singleton_mod_hash, genesis_id, innerpuz)

    p2_singleton_coin_id = Program.to(["test_hash"]).get_tree_hash()
    expected_announcement = Announcement(singleton_full.get_tree_hash(), p2_singleton_coin_id).name()

    p2_singleton_full = P2_SINGLETON_MOD.curry(
        singleton_mod_hash, Program.to(singleton_mod_hash).get_tree_hash(), genesis_id
    )
    cost, result = p2_singleton_full.run_with_cost(
        INFINITE_COST, Program.to([innerpuz.get_tree_hash(), p2_singleton_coin_id])
    )
    assert result.first().rest().first().as_atom() == expected_announcement


def test_create():
    innerpuz = Program.to(1)
    genesis_id = 0xCAFEF00D
    genesis_puzhash = genesis_id
    create_fullpuz(innerpuz, genesis_puzhash)


def test_uncurry():
    pass

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
    coin = {'amount': 1,
     'parent_coin_info': '0x4ed5f1195300d479237070d095101a138142caa24c731d8de99b6c4e8d7f7b3d',
    'puzzle_hash': '0x924175b2583440413221321541e672989fe6d201ee0643d945b6679671f20d74'}
    origin_coin_puzzle_hash = 32 * b"\0"
    origin_coin = Coin(hexstr_to_bytes("7eafe79ac873ad528287f905620ee0eefb3bd1b70274a4c1a4817ca1db952007", origin_coin_puzzle_hash, 100))
    current_rewards_pubkey = hexstr_to_bytes("844ab45b6bb8e674c8452de2a018209cf8a05ee25782fd12c6a202ffd953a28caa560f20a3838d4f31a1ad4fed573e94")
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
    index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
    private = master_sk_to_wallet_sk(self.wallet_state_manager.private_key, index)
    signature = AugSchemeMPL.sign(private, message)
    sigs = [signature]
    aggsig = AugSchemeMPL.aggregate(sigs)
    spend_bundle = SpendBundle(list_of_solutions, aggsig)
    return spend_bundle

def test_pooling():
    pass