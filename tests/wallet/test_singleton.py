from chia.wallet.puzzles.load_clvm import load_clvm
from chia.types.blockchain_format.program import Program, INFINITE_COST

DID_CORE_MOD = load_clvm("singleton_top_layer.clvm")


def test_only_odd_coins():
    did_core_hash = DID_CORE_MOD.get_tree_hash()
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
        result, cost = DID_CORE_MOD.run_with_cost(INFINITE_COST, solution)
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
        result, cost = DID_CORE_MOD.run_with_cost(INFINITE_COST, solution)
    except Exception:
        assert False


def test_only_one_odd_coin_created():
    did_core_hash = DID_CORE_MOD.get_tree_hash()
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
        result, cost = DID_CORE_MOD.run_with_cost(INFINITE_COST, solution)
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
        result, cost = DID_CORE_MOD.run_with_cost(INFINITE_COST, solution)
    except Exception:
        assert False
