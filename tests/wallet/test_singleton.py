from chia.wallet.puzzles.load_clvm import load_clvm
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32

SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
SINGLETON_LAUNCHER_MOD = load_clvm("singleton_launcher.clvm")
P2_SINGLETON_MOD = load_clvm("p2_singleton.clvm")
POOL_COMMITED_MOD = load_clvm("pool_member_innerpuz.clvm")
POOL_ESCAPING_MOD = load_clvm("pool_escaping_innerpuz.clvm")


def test_only_odd_coins():
    did_core_hash = SINGLETON_MOD.get_tree_hash()
    # (MOD_HASH GENESIS_ID INNERPUZ parent_info my_amount inner_solution)
    solution = Program.to(
        [
            did_core_hash,
            did_core_hash,
            1,
            [0xDEADBEEF, 0xCAFEF00D, 200],
            200,
            [[51, 0xCAFEF00D, 200]],
        ]
    )
    try:
        cost, result = SINGLETON_MOD.run_with_cost(INFINITE_COST, solution)
    except Exception as e:
        assert e.args == ("clvm raise",)
    else:
        assert False

    solution = Program.to(
        [
            did_core_hash,
            did_core_hash,
            1,
            [0xDEADBEEF, 0xCAFEF00D, 210],
            205,
            [[51, 0xCAFEF00D, 205]],
        ]
    )
    try:
        cost, result = SINGLETON_MOD.run_with_cost(INFINITE_COST, solution)
    except Exception:
        assert False


def test_only_one_odd_coin_created():
    did_core_hash = SINGLETON_MOD.get_tree_hash()
    solution = Program.to(
        [
            did_core_hash,
            did_core_hash,
            1,
            [0xDEADBEEF, 0xCAFEF00D, 411],
            411,
            [[51, 0xCAFEF00D, 203], [51, 0xFADEDDAB, 203]],
        ]
    )
    try:
        cost, result = SINGLETON_MOD.run_with_cost(INFINITE_COST, solution)
    except Exception as e:
        assert e.args == ("clvm raise",)
    else:
        assert False
    solution = Program.to(
        [
            did_core_hash,
            did_core_hash,
            1,
            [0xDEADBEEF, 0xCAFEF00D, 411],
            411,
            [[51, 0xCAFEF00D, 203], [51, 0xFADEDDAB, 202], [51, 0xFADEDDAB, 4]],
        ]
    )
    try:
        cost, result = SINGLETON_MOD.run_with_cost(INFINITE_COST, solution)
    except Exception:
        assert False


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


def test_pool_puzzles():
    singleton_mod_hash = SINGLETON_MOD.get_tree_hash()
    genesis_coin = Coin(SINGLETON_LAUNCHER_MOD.get_tree_hash(), SINGLETON_LAUNCHER_MOD.get_tree_hash(), 200)
    genesis_id = genesis_coin.name()

    genesis_challenge = bytes.fromhex("ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb")
    block_height = 101  # 0x65
    pool_reward_parent_id = bytes32(genesis_challenge[:16] + block_height.to_bytes(16, "big"))

    p2_singleton_full = P2_SINGLETON_MOD.curry(
        singleton_mod_hash, Program.to(singleton_mod_hash).get_tree_hash(), genesis_id
    )

    p2_singleton_full_puzhash = p2_singleton_full.get_tree_hash()
    p2_singlton_coin_amount = 2000000000
    p2_singleton_coin_id = Coin(pool_reward_parent_id, p2_singleton_full_puzhash, p2_singlton_coin_amount).name()

    pool_puzhash = 0xd34db33f
    relative_lock_height = 600
    owner_pubkey = 0xFADEDDAB

    # Curry params are POOL_PUZHASH, RELATIVE_LOCK_HEIGHT, OWNER_PUBKEY, P2_SINGLETON_PUZHASH
    escape_innerpuz = POOL_ESCAPING_MOD.curry(pool_puzhash, relative_lock_height, owner_pubkey, p2_singleton_full_puzhash)
    # Curry params are POOL_PUZHASH, RELATIVE_LOCK_HEIGHT, ESCAPE_MODE_PUZHASH, P2_SINGLETON_PUZHASH, PUBKEY
    committed_innerpuz = POOL_COMMITED_MOD.curry(pool_puzhash, escape_innerpuz.get_tree_hash(), p2_singleton_full_puzhash, owner_pubkey)

    singleton_full = SINGLETON_MOD.curry(singleton_mod_hash, genesis_id, committed_innerpuz)
    singleton_amount = 3
    singleton_coin = Coin(genesis_id, singleton_full.get_tree_hash(), singleton_amount)

    # innersol = spend_type, my_puzhash, my_amount, pool_reward_amount, pool_reward_height
    inner_sol = Program.to([0, singleton_full.get_tree_hash(), singleton_amount, p2_singlton_coin_amount, block_height])
    # full_sol = parent_info, my_amount, inner_solution
    full_sol = Program.to([[genesis_coin.parent_coin_info, genesis_coin.amount], singleton_amount, inner_sol])

    cost, result = singleton_full.run_with_cost(INFINITE_COST, full_sol)

    assert bytes32(result.first().rest().first().as_atom()) == singleton_coin.name()
    assert bytes32(result.rest().rest().first().rest().first().as_atom()) == singleton_full.get_tree_hash()
    assert bytes32(result.rest().rest().rest().rest().rest().rest().first().rest().first().as_atom()) == Announcement(p2_singleton_coin_id, bytes.fromhex("80")).name()

    # result = '((70 0x3ca5a8530504c46ecd1cc11cacd3bd656d110ba33dff346c95015e33a358d4f4) (51 0x01527389c9be48a11b4e0620e9fb1663907776fc15b426e616c458c24ea304d5 3) (72 0x01527389c9be48a11b4e0620e9fb1663907776fc15b426e616c458c24ea304d5) (73 3) (51 0x00d34db33f 0x77359400) (62 0x706f0c47e87d9d0c85b688b16330d1d158329756432e88f9229ad31600121868) (61 0x34c9ba15ce7b40081ae7bd2c120ba88069fddb023814d42f793c255f8785b1df))'
