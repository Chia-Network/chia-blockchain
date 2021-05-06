from chia.wallet.puzzles.load_clvm import load_clvm
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.announcement import Announcement

SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
P2_SINGLETON_MOD = load_clvm("p2_singleton.clvm")


def test_only_odd_coins():
    did_core_hash = SINGLETON_MOD.get_tree_hash()
    solution = Program.to(
        [
            did_core_hash,
            did_core_hash,
            1,
            [0xFADEDDAB, 203],
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
            [0xFADEDDAB, 203],
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
            [0xFADEDDAB, 203],
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
            [0xFADEDDAB, 203],
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
