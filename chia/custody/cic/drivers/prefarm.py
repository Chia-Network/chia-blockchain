import dataclasses
import enum

from blspy import G1Element, G2Element
from clvm.casts import int_from_bytes
from typing import List, Optional, Tuple

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.spend_bundle import SpendBundle
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.p2_conditions import puzzle_for_conditions
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_delegated_puzzle
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint64

from cic.drivers.drop_coins import (
    construct_rekey_puzzle,
    construct_rekey_clawback,
    construct_ach_puzzle,
    curry_rekey_puzzle,
    curry_ach_puzzle,
    solve_rekey_completion,
    solve_rekey_clawback,
    solve_ach_completion,
    solve_ach_clawback,
)
from cic.drivers.filters import (
    construct_payment_and_rekey_filter,
    construct_rekey_filter,
    solve_filter_for_payment,
    solve_filter_for_rekey,
)
from cic.drivers.merkle_utils import simplify_merkle_proof
from cic.drivers.prefarm_info import PrefarmInfo
from cic.drivers.puzzle_root_construction import RootDerivation, construct_lock_puzzle, solve_lock_puzzle
from cic.drivers.singleton import construct_singleton, solve_singleton, construct_p2_singleton, solve_p2_singleton
from cic.load_clvm import load_clvm


PREFARM_INNER = load_clvm("prefarm_inner.clsp", package_or_requirement="cic.clsp.singleton")


class SpendType(int, enum.Enum):
    FINISH_REKEY = 0
    START_REKEY = 1
    HANDLE_PAYMENT = 2


# ((REKEY_MOD_HASH . ACH_MOD_HASH) . (ACH_TIMELOCK . (BASE_REKEY_TIMELOCK . SLOW_REKEY_PENALTY)))
def construct_prefarm_inner_puzzle(prefarm_info: PrefarmInfo) -> Program:
    return PREFARM_INNER.curry(
        PREFARM_INNER.get_tree_hash(),
        prefarm_info.puzzle_root,
        (
            (construct_rekey_puzzle(prefarm_info).get_tree_hash(), construct_ach_puzzle(prefarm_info).get_tree_hash()),
            (
                prefarm_info.withdrawal_timelock,
                (
                    prefarm_info.rekey_increments,
                    prefarm_info.slow_rekey_timelock,
                ),
            ),
        ),
    )


def solve_prefarm_inner(spend_type: SpendType, prefarm_amount: uint64, **kwargs) -> Program:
    spend_solution: Program
    if spend_type in [SpendType.START_REKEY, SpendType.FINISH_REKEY]:
        spend_solution = Program.to(
            [
                kwargs["timelock"],
                kwargs["puzzle_root"],
            ]
        )
    elif spend_type == SpendType.HANDLE_PAYMENT:
        spend_solution = Program.to(
            [
                kwargs["out_amount"],
                kwargs["in_amount"],
                kwargs["p2_ph"],
            ]
        )
    else:
        raise ValueError("An invalid spend type was specified")

    return Program.to(
        [
            prefarm_amount,
            spend_type.value,
            spend_solution,
            kwargs.get("puzzle_reveal"),
            kwargs.get("proof_of_inclusion"),
            kwargs.get("puzzle_solution"),
        ]
    )


def construct_singleton_inner_puzzle(prefarm_info: PrefarmInfo) -> Program:
    return construct_prefarm_inner_puzzle(prefarm_info)


def construct_full_singleton(
    prefarm_info: PrefarmInfo,
) -> Program:
    return construct_singleton(
        prefarm_info.launcher_id,
        construct_singleton_inner_puzzle(prefarm_info),
    )


def get_withdrawal_spend_info(
    singleton: Coin,
    pubkeys: List[G1Element],
    derivation: RootDerivation,
    lineage_proof: LineageProof,
    amount: uint64,
    clawforward_ph: bytes32,
    p2_singletons_to_claim: List[Coin] = [],
    additional_conditions: List[Program] = [],
) -> Tuple[SpendBundle, bytes]:
    assert len(pubkeys) > 0
    agg_pk = G1Element()
    for pk in pubkeys:
        agg_pk += pk

    payment_amount: int = amount - sum(c.amount for c in p2_singletons_to_claim)

    # Info to claim the p2_singletons
    singleton_inner_puzhash: bytes32 = construct_singleton_inner_puzzle(derivation.prefarm_info).get_tree_hash()
    p2_singleton_spends: List[CoinSpend] = []
    p2_singleton_claim_conditions: List[Program] = []
    for p2_singleton in p2_singletons_to_claim:
        p2_singleton_spends.append(
            CoinSpend(
                p2_singleton,
                construct_p2_singleton(derivation.prefarm_info.launcher_id),
                solve_p2_singleton(p2_singleton, singleton_inner_puzhash),
            )
        )
        p2_singleton_claim_conditions.append(Program.to([62, p2_singleton.name()]))  # create
        p2_singleton_claim_conditions.append(Program.to([61, std_hash(p2_singleton.name() + b"$")]))  # assert

    # Proofs of inclusion
    filter_proof, leaf_proof = (list(proof.items())[0][1] for proof in derivation.get_proofs_of_inclusion(agg_pk))

    # Construct the puzzle reveals
    inner_puzzle: Program = puzzle_for_pk(agg_pk)
    filter_puzzle: Program = construct_payment_and_rekey_filter(
        derivation.prefarm_info,
        simplify_merkle_proof(inner_puzzle.get_tree_hash(), leaf_proof),
        uint8(1),
    )

    # Construct ACH creation solution
    if amount == 0:
        ach_conditions: List[Program] = []
    else:
        ach_conditions = [
            Program.to([51, curry_ach_puzzle(derivation.prefarm_info, clawforward_ph).get_tree_hash(), amount])
        ]
    delegated_puzzle: Program = puzzle_for_conditions(
        [
            [
                51,
                construct_prefarm_inner_puzzle(derivation.prefarm_info).get_tree_hash(),
                singleton.amount - payment_amount,
            ],
            *ach_conditions,
            *p2_singleton_claim_conditions,
            *additional_conditions,
        ]
    )
    inner_solution: Program = solution_for_delegated_puzzle(delegated_puzzle, Program.to([]))
    full_sb = (
        SpendBundle(
            [
                CoinSpend(
                    singleton,
                    construct_full_singleton(derivation.prefarm_info),
                    solve_singleton(
                        lineage_proof,
                        singleton.amount,
                        solve_prefarm_inner(
                            SpendType.HANDLE_PAYMENT,
                            singleton.amount,
                            out_amount=amount,
                            in_amount=uint64(sum(c.amount for c in p2_singletons_to_claim)),
                            p2_ph=clawforward_ph,
                            puzzle_reveal=filter_puzzle,
                            proof_of_inclusion=filter_proof,
                            puzzle_solution=solve_filter_for_payment(
                                inner_puzzle,
                                Program.to(leaf_proof),
                                inner_solution,
                                derivation.prefarm_info.puzzle_root,
                                clawforward_ph,
                            ),
                        ),
                    ),
                ),
                *p2_singleton_spends,
            ],
            G2Element(),
        ),
        (delegated_puzzle.get_tree_hash() + singleton.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA),  # TODO
    )
    return full_sb


def get_ach_clawback_spend_info(
    ach_coin: Coin,
    pubkeys: List[G1Element],
    derivation: RootDerivation,
    clawforward_ph: bytes32,
    additional_conditions: List[Program] = [],
) -> Tuple[SpendBundle, bytes]:
    assert len(pubkeys) > 0
    agg_pk = G1Element()
    for pk in pubkeys:
        agg_pk += pk
    # Proofs of inclusion
    filter_proof, leaf_proof = (list(proof.items())[0][1] for proof in derivation.get_proofs_of_inclusion(agg_pk))

    # Construct the puzzle reveals
    inner_puzzle: Program = puzzle_for_pk(agg_pk)
    filter_puzzle: Program = construct_payment_and_rekey_filter(
        derivation.prefarm_info,
        simplify_merkle_proof(inner_puzzle.get_tree_hash(), leaf_proof),
        uint8(1),
    )

    # Construct inner solution
    delegated_puzzle: Program = puzzle_for_conditions(
        [
            [51, construct_p2_singleton(derivation.prefarm_info.launcher_id).get_tree_hash(), ach_coin.amount],
            *additional_conditions,
        ]
    )
    inner_solution: Program = solution_for_delegated_puzzle(delegated_puzzle, Program.to([]))

    return (
        SpendBundle(
            [
                CoinSpend(
                    ach_coin,
                    curry_ach_puzzle(derivation.prefarm_info, clawforward_ph),
                    solve_ach_clawback(
                        derivation.prefarm_info,
                        ach_coin.amount,
                        filter_puzzle,
                        Program.to(filter_proof),
                        solve_filter_for_payment(
                            inner_puzzle,
                            Program.to(leaf_proof),
                            inner_solution,
                            derivation.prefarm_info.puzzle_root,
                            clawforward_ph,
                        ),
                    ),
                ),
            ],
            G2Element(),
        ),
        (delegated_puzzle.get_tree_hash() + ach_coin.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA),  # TODO
    )


def get_ach_clawforward_spend_bundle(
    ach_coin: Coin,
    derivation: RootDerivation,
    clawforward_ph: bytes32,
) -> SpendBundle:
    return SpendBundle(
        [
            CoinSpend(
                ach_coin,
                curry_ach_puzzle(derivation.prefarm_info, clawforward_ph),
                solve_ach_completion(derivation.prefarm_info, ach_coin.amount),
            ),
        ],
        G2Element(),
    )


# This is some extracted shared functionality from the next three functions
def calculate_rekey_args(
    coin: Coin,
    pubkeys: List[G1Element],
    derivation: RootDerivation,
    new_derivation: Optional[RootDerivation] = None,  # None means this is a lock level increase
    additional_conditions: List[Program] = [],
) -> Tuple[uint8, bytes32, Program, Program, Program, bytes]:
    agg_pk = G1Element()
    for pk in pubkeys:
        agg_pk += pk
    # Proofs of inclusion
    filter_proof, leaf_proof = (
        list(proof.items())[0][1] for proof in derivation.get_proofs_of_inclusion(agg_pk, lock=(new_derivation is None))
    )

    # A lot of information is conditional based on the filter we're in
    if new_derivation is None:
        assert derivation.next_root is not None
        new_puzzle_root: bytes32 = derivation.next_root
        inner_puzzle: Program = construct_lock_puzzle(agg_pk, derivation.prefarm_info, new_puzzle_root)
    else:
        new_puzzle_root = new_derivation.prefarm_info.puzzle_root
        inner_puzzle = puzzle_for_pk(agg_pk)

    if new_derivation is None:
        timelock = uint8(0)
        filter_puzzle: Program = construct_rekey_filter(
            derivation.prefarm_info,
            simplify_merkle_proof(inner_puzzle.get_tree_hash(), leaf_proof),
            timelock,
        )
    elif len(pubkeys) == derivation.required_pubkeys:
        timelock = uint8(1)
        filter_puzzle = construct_payment_and_rekey_filter(
            derivation.prefarm_info,
            simplify_merkle_proof(inner_puzzle.get_tree_hash(), leaf_proof),
            timelock,
        )
    elif len(pubkeys) < derivation.required_pubkeys:
        timelock = uint8(1 + derivation.required_pubkeys - len(pubkeys))
        filter_puzzle = construct_rekey_filter(
            derivation.prefarm_info,
            simplify_merkle_proof(inner_puzzle.get_tree_hash(), leaf_proof),
            timelock,
        )
    else:
        raise ValueError("An invalid number of pubkeys was specified")

    if new_derivation is None:
        inner_solution: Program = solve_lock_puzzle(
            derivation.prefarm_info.puzzle_root,
            construct_prefarm_inner_puzzle(derivation.prefarm_info).get_tree_hash(),
            coin.amount,
        )
        signed_message: bytes = b""
    else:
        conditions = [
            [
                51,
                curry_rekey_puzzle(timelock, derivation.prefarm_info, new_derivation.prefarm_info).get_tree_hash(),
                0,
            ],
            *additional_conditions,
        ]
        if coin.amount != 0:
            conditions.append(
                [
                    51,
                    construct_prefarm_inner_puzzle(derivation.prefarm_info).get_tree_hash(),
                    coin.amount,
                ]
            )
        delegated_puzzle: Program = puzzle_for_conditions(conditions)
        inner_solution = solution_for_delegated_puzzle(delegated_puzzle, Program.to([]))
        signed_message = delegated_puzzle.get_tree_hash()

    filter_solution = solve_filter_for_rekey(
        inner_puzzle,
        Program.to(leaf_proof),
        inner_solution,
        derivation.prefarm_info.puzzle_root,
        new_puzzle_root,
        timelock,
    )

    data_to_sign: bytes = signed_message + coin.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA  # TODO

    return timelock, new_puzzle_root, filter_puzzle, Program.to(filter_proof), filter_solution, data_to_sign


def get_rekey_spend_info(
    singleton: Coin,
    pubkeys: List[G1Element],
    derivation: RootDerivation,
    lineage_proof: LineageProof,
    new_derivation: Optional[RootDerivation] = None,  # None means this is a lock level increase
    additional_conditions: List[Program] = [],
) -> Tuple[SpendBundle, bytes]:
    assert len(pubkeys) > 0

    timelock, new_puzzle_root, filter_puzzle, filter_proof, filter_solution, data_to_sign = calculate_rekey_args(
        singleton,
        pubkeys,
        derivation,
        new_derivation,
        additional_conditions,
    )

    lock_spends: List[CoinSpend] = []
    if new_derivation is None:
        rekey_puzzle: Program = curry_rekey_puzzle(
            uint8(0),
            derivation.prefarm_info,
            dataclasses.replace(derivation.prefarm_info, puzzle_root=derivation.next_root),
        )
        lock_spends = [
            CoinSpend(
                Coin(
                    singleton.name(),
                    rekey_puzzle.get_tree_hash(),
                    uint64(0),
                ),
                rekey_puzzle,
                solve_rekey_completion(
                    derivation.prefarm_info,
                    LineageProof(
                        singleton.parent_coin_info,
                        construct_singleton_inner_puzzle(derivation.prefarm_info).get_tree_hash(),
                        singleton.amount,
                    ),
                ),
            ),
            CoinSpend(
                Coin(
                    singleton.name(),
                    singleton.puzzle_hash,
                    singleton.amount,
                ),
                construct_full_singleton(derivation.prefarm_info),
                solve_singleton(
                    LineageProof(
                        singleton.parent_coin_info,
                        construct_singleton_inner_puzzle(derivation.prefarm_info).get_tree_hash(),
                        singleton.amount,
                    ),
                    singleton.amount,
                    solve_prefarm_inner(
                        SpendType.FINISH_REKEY,
                        singleton.amount,
                        timelock=uint64(0),
                        puzzle_root=new_puzzle_root,
                    ),
                ),
            ),
        ]

    return (
        SpendBundle(
            [
                CoinSpend(
                    singleton,
                    construct_full_singleton(derivation.prefarm_info),
                    solve_singleton(
                        lineage_proof,
                        singleton.amount,
                        solve_prefarm_inner(
                            SpendType.START_REKEY,
                            singleton.amount,
                            timelock=timelock,
                            puzzle_root=new_puzzle_root,
                            puzzle_reveal=filter_puzzle,
                            proof_of_inclusion=filter_proof,
                            puzzle_solution=filter_solution,
                        ),
                    ),
                ),
                *lock_spends,
            ],
            G2Element(),
        ),
        data_to_sign,
    )


def get_rekey_clawback_spend_info(
    rekey_coin: Coin,
    pubkeys: List[G1Element],
    derivation: RootDerivation,
    timelock_multiple: uint8,
    new_derivation: Optional[RootDerivation] = None,  # None means we're performing a lock
    additional_conditions: List[Program] = [],
) -> Tuple[SpendBundle, bytes]:

    timelock, new_puzzle_root, filter_puzzle, filter_proof, filter_solution, data_to_sign = calculate_rekey_args(
        rekey_coin,
        pubkeys,
        derivation,
        new_derivation,
        additional_conditions,
    )

    return (
        SpendBundle(
            [
                CoinSpend(
                    rekey_coin,
                    curry_rekey_puzzle(
                        timelock_multiple,
                        derivation.prefarm_info,
                        dataclasses.replace(derivation.prefarm_info, puzzle_root=new_puzzle_root),
                    ),
                    solve_rekey_clawback(
                        derivation.prefarm_info,
                        rekey_coin.puzzle_hash,
                        filter_puzzle,
                        filter_proof,
                        filter_solution,
                    ),
                ),
            ],
            G2Element(),
        ),
        data_to_sign,
    )


def get_rekey_completion_spend(
    singleton: Coin,
    rekey_coin: Coin,
    pubkeys: List[G1Element],
    derivation: RootDerivation,
    singleton_lineage: LineageProof,
    rekey_lineage: LineageProof,
    new_derivation: Optional[RootDerivation] = None,  # None means we're performing a lock
) -> SpendBundle:

    timelock, new_puzzle_root, _, _, _, _ = calculate_rekey_args(
        rekey_coin,
        pubkeys,
        derivation,
        new_derivation,
    )

    return SpendBundle(
        [
            CoinSpend(
                singleton,
                construct_full_singleton(derivation.prefarm_info),
                solve_singleton(
                    singleton_lineage,
                    singleton.amount,
                    solve_prefarm_inner(
                        SpendType.FINISH_REKEY,
                        singleton.amount,
                        timelock=timelock,
                        puzzle_root=new_puzzle_root,
                    ),
                ),
            ),
            CoinSpend(
                rekey_coin,
                curry_rekey_puzzle(
                    timelock,
                    derivation.prefarm_info,
                    dataclasses.replace(derivation.prefarm_info, puzzle_root=new_puzzle_root),
                ),
                solve_rekey_completion(derivation.prefarm_info, rekey_lineage),
            ),
        ],
        G2Element(),
    )


def get_puzzle_root_from_puzzle(puzzle: Program) -> bytes32:
    _, pf_inner_puzzle = puzzle.uncurry()[1].as_iter()
    _, root, _ = pf_inner_puzzle.uncurry()[1].as_iter()
    return bytes32(root.as_python())


def get_new_puzzle_root_from_solution(solution: Program) -> bytes32:
    prefarm_inner_solution = solution.at("rrf")
    spend_solution = prefarm_inner_solution.at("rrf")
    new_puzzle_root = spend_solution.at("rf")
    return bytes32(new_puzzle_root.as_python())


def get_spend_type_for_solution(solution: Program) -> SpendType:
    prefarm_inner_solution = solution.at("rrf")
    spend_type = prefarm_inner_solution.at("rf")
    return SpendType(int_from_bytes(spend_type.as_python()))


def get_spending_pubkey_for_solution(solution: Program) -> G1Element:
    if get_spend_type_for_solution(solution) == SpendType.FINISH_REKEY:
        return None
    else:
        prefarm_inner_solution = solution.at("rrf")
        filter_solution = prefarm_inner_solution.at("rrrrrf")
        leaf_reveal = filter_solution.at("f")
        pubkey = list(leaf_reveal.uncurry())[1].as_python()[0]
        return G1Element.from_bytes(pubkey)


def get_spend_params_for_ach_creation(solution: Program) -> Tuple[uint64, uint64, bytes32]:
    prefarm_inner_solution = solution.at("rrf")
    spend_solution = prefarm_inner_solution.at("rrf")
    out_amount = uint64(int_from_bytes(spend_solution.at("f").as_python()))
    in_amount = uint64(int_from_bytes(spend_solution.at("rf").as_python()))
    p2_ph = bytes32(spend_solution.at("rrf").as_python())
    return out_amount, in_amount, p2_ph


def get_spend_params_for_rekey_creation(solution: Program) -> Tuple[uint8, bytes32]:
    prefarm_inner_solution = solution.at("rrf")
    spend_solution = prefarm_inner_solution.at("rrf")
    timelock = uint8(int_from_bytes(spend_solution.at("f").as_python()))
    new_root = bytes32(spend_solution.at("rf").as_python())
    return timelock, new_root


def get_info_for_rekey_drop(puzzle: Program) -> Tuple[bytes32, bytes32, uint8]:
    curried_args = list(puzzle.uncurry()[1].as_iter())[0]
    new_root, old_root, timelock = curried_args.as_iter()
    return bytes32(new_root.as_python()), bytes32(old_root.as_python()), uint8(int_from_bytes(timelock.as_python()))


def get_info_for_ach_drop(puzzle: Program) -> Tuple[bytes32, bytes32]:
    curried_args = list(puzzle.uncurry()[1].as_iter())[0]
    from_root = curried_args.first()
    p2_ph = curried_args.rest()
    return bytes32(from_root.as_python()), bytes32(p2_ph.as_python())


def get_spending_pubkey_for_drop_coin(solution: Program) -> G1Element:
    clawback_solution = solution.at("rrf")
    filter_solution = clawback_solution.at("rrrf")
    puzzle_reveal = filter_solution.at("f")
    pubkey = list(puzzle_reveal.uncurry())[1].as_python()[0]
    return G1Element.from_bytes(pubkey)


def was_rekey_completed(solution: Program) -> bool:
    puzzle_reveal = solution.at("f")
    if puzzle_reveal == construct_rekey_clawback():
        return False
    else:
        return True
