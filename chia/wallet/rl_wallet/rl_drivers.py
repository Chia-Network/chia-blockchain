from typing import Dict

from chia.types.blockchain_format.program import Program
from chia.util.ints import uint64, uint32
from chia.clvm.load_clvm import load_clvm

RL_MOD = load_clvm("rl.clsp", package_or_requirement="chia.wallet.rl_wallet.puzzles")


def create_rl_puzzle(
    amount_per: uint64,
    interval_time: uint32,
    earnings_cap: uint64,
    initial_credit: uint64,
    inner_puzzle: Program,
) -> Program:
    return RL_MOD.curry(
        RL_MOD.get_tree_hash(),
        amount_per,
        interval_time,
        earnings_cap,
        initial_credit,
        inner_puzzle,
    )


def create_rl_solution(
    blocks_since_last: uint32,
    inner_solution: Program,
) -> Program:
    return Program.to([blocks_since_last, inner_solution])


def uncurry_rl_puzzle(
    rl_puzzle: Program,
) -> Dict:
    mod, args = rl_puzzle.uncurry()
    mod_hash, amount_per, interval_time, earnings_cap, credit, inner_puzzle = args.as_python()
    return {
        "mod_hash": mod_hash,
        "amount_per": int.from_bytes(amount_per, "big"),
        "interval_time": int.from_bytes(interval_time, "big"),
        "earnings_cap": int.from_bytes(earnings_cap, "big"),
        "credit": int.from_bytes(credit, "big"),
        "inner_puzzle": Program.to(inner_puzzle),
    }
